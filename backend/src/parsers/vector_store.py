"""
Hybrid retrieval engine: FAISS (dense) + BM25 (sparse) + FlashRank reranker.

Architecture overview:
  - Dense retrieval via FAISS with cosine similarity (matches how Gemini
    embedding models are trained — L2 distance was previously used, which
    degrades ranking quality for normalised embeddings).
  - Sparse retrieval via BM25 for exact keyword/term matching.
  - Reciprocal Rank Fusion (RRF) merges both result sets via LangChain's
    EnsembleRetriever.
  - FlashRank cross-encoder reranks the top-N candidates for precision.

Embedding providers:
  - "gemini"  → GoogleGenerativeAIEmbeddings with asymmetric task_type
                (RETRIEVAL_DOCUMENT for indexing, RETRIEVAL_QUERY for search).
  - "ollama"  → OllamaEmbeddings (task_type not supported — placeholder for
                future work).
"""

import hashlib
import time
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional

from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()


class IndexMismatchError(ValueError):
    """Saved index has no manifest, was modified, or was built with other embeddings."""


class VectorStoreManager:
    """
    Manages a hybrid retrieval pipeline: FAISS + BM25 + optional reranking.

    The pipeline is:
      1. create_index()  — builds both FAISS and BM25 indexes from chunks.
      2. search()        — runs hybrid retrieval (dense + sparse, fused via RRF),
                           then optionally reranks with a cross-encoder.
      3. save_local() / load_local() — persist/restore the FAISS index.
                           BM25 is rebuilt from the stored documents on load.
    """

    def __init__(self, provider: str | None = None, model_name: str | None = None):
        provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()
        self.provider = provider
        self.doc_embeddings = self._build_embeddings(provider, model_name, role="document")
        self.query_embeddings = self._build_embeddings(provider, model_name, role="query")
        self.embedding_model = self.doc_embeddings.model
        self.vector_store: Optional[FAISS] = None
        self.bm25_retriever: Optional[BM25Retriever] = None
        # Keep a reference to the documents for BM25 rebuild on load_local().
        self._documents: List[Document] = []
        self._reranker = None

    # ── Embedding construction ──────────────────────────────────────────

    @staticmethod
    def _build_embeddings(provider: str, model_name: str | None, role: str):
        """
        Build an embeddings instance for the given provider and role.

        For Gemini, `role` controls the task_type parameter:
          - "document" → RETRIEVAL_DOCUMENT (used during indexing)
          - "query"    → RETRIEVAL_QUERY   (used during search)
        This asymmetry improves retrieval accuracy because the model optimises
        the vector space differently for documents vs. queries.

        For Ollama, task_type is not supported — both roles return the same
        embeddings instance. This is a known limitation; Ollama embeddings
        will still work, just without task-specific optimisation.
        """
        if provider == "ollama":
            from langchain_ollama import OllamaEmbeddings

            model_name = model_name or os.getenv(
                "OLLAMA_EMBEDDING_MODEL", "qwen3-embedding"
            )
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            # Ollama does not support task_type — both roles use the same config.
            return OllamaEmbeddings(model=model_name, base_url=base_url)

        elif provider == "gemini":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            model_name = model_name or os.getenv(
                "GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001"
            )
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError(
                    "GOOGLE_API_KEY must be set in .env when using the Gemini provider."
                )

            task_type_map = {
                "document": os.getenv("EMBEDDING_TASK_TYPE_DOCUMENT", "RETRIEVAL_DOCUMENT"),
                "query": os.getenv("EMBEDDING_TASK_TYPE_QUERY", "RETRIEVAL_QUERY"),
            }

            return GoogleGenerativeAIEmbeddings(
                model=model_name,
                google_api_key=api_key,
                task_type=task_type_map.get(role, "RETRIEVAL_DOCUMENT"),
            )

        else:
            raise ValueError(
                f"Unknown embedding provider '{provider}'. "
                "Supported values: 'ollama', 'gemini'."
            )

    # ── Index creation ──────────────────────────────────────────────────

    def create_index(self, chunks: List[str], metadatas: List[Dict]):
        """
        Build both the FAISS vector index and the BM25 keyword index.

        Uses cosine distance for FAISS instead of the default L2, because
        Gemini (and most modern) embedding models produce normalised vectors
        that are trained with a cosine similarity objective.
        """
        documents = [
            Document(page_content=chunk, metadata=metadata)
            for chunk, metadata in zip(chunks, metadatas)
        ]
        self._documents = documents

        # Dense index — cosine similarity via FAISS.
        # LangChain handles L2-normalisation internally when COSINE is selected.
        # Embedded in batches: free-tier Gemini keys allow ~100 embedding
        # requests a minute, so a long manual is paced instead of failing.
        batch_size = int(os.getenv("EMBED_BATCH_SIZE", "80"))
        self.vector_store = None
        for start in range(0, len(documents), batch_size):
            batch = documents[start:start + batch_size]
            if start:
                time.sleep(float(os.getenv("EMBED_BATCH_PAUSE_SECONDS", "62")))
            self._embed_batch(batch)

        self._build_bm25(documents)

    def _embed_batch(self, batch: List[Document], attempts: int = 4):
        """Add one batch to the FAISS index, waiting out per-minute rate limits."""
        for attempt in range(attempts):
            try:
                if self.vector_store is None:
                    self.vector_store = FAISS.from_documents(
                        batch, self.doc_embeddings, distance_strategy=DistanceStrategy.COSINE
                    )
                else:
                    self.vector_store.add_documents(batch)
                return
            except Exception as e:
                rate_limited = "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e)
                if not rate_limited or attempt == attempts - 1:
                    raise
                print(f"[embed] rate limited; waiting 65 s before retrying ({attempt + 1}/{attempts - 1})")
                time.sleep(65)

    def _build_bm25(self, documents: List[Document]):
        """
        Build (or rebuild) the BM25 sparse retriever from document texts.

        BM25 is an in-memory index that cannot be serialised alongside FAISS,
        so it is rebuilt from the stored documents whenever the index is loaded.
        """
        if not documents:
            self.bm25_retriever = None
            return
        self.bm25_retriever = BM25Retriever.from_documents(documents)

    # ── Hybrid search with optional reranking ──────────────────────────

    def search(
        self,
        query: str,
        k: int = 1,
        k_before_rerank: int | None = None,
        enable_reranking: bool = True,
    ) -> List[Document]:
        """
        Run the full hybrid retrieval pipeline:
          1. FAISS (dense) + BM25 (sparse) → fused via Reciprocal Rank Fusion
          2. Cross-encoder reranking (FlashRank) on the fused candidates

        Args:
            query: The user's search query.
            k: Final number of documents to return.
            k_before_rerank: How many candidates to retrieve before reranking.
                Defaults to env RETRIEVAL_K_BEFORE_RERANK, then 10.
            enable_reranking: Whether to apply the cross-encoder reranker.
                If False, returns the top-k from hybrid search directly.
        """
        if not self.vector_store:
            raise ValueError("Vector store not initialised. Call create_index first.")

        if k_before_rerank is None:
            k_before_rerank = int(os.getenv("RETRIEVAL_K_BEFORE_RERANK", "10"))

        # Determine how many candidates to fetch from each retriever.
        # When reranking, we over-fetch to give the reranker a larger pool.
        fetch_k = k_before_rerank if enable_reranking else k

        candidates = self._hybrid_search(query, k=fetch_k)

        if enable_reranking and len(candidates) > 1:
            candidates = self._rerank(query, candidates, top_n=k)
        else:
            candidates = candidates[:k]

        return candidates

    def _hybrid_search(self, query: str, k: int) -> List[Document]:
        """
        Combine FAISS dense search and BM25 sparse search using
        Reciprocal Rank Fusion (RRF) via LangChain's EnsembleRetriever.

        Falls back to FAISS-only if BM25 is unavailable (e.g., empty corpus).
        """
        bm25_weight = float(os.getenv("HYBRID_BM25_WEIGHT", "0.4"))
        dense_weight = float(os.getenv("HYBRID_DENSE_WEIGHT", "0.6"))

        # FAISS retriever — uses query_embeddings for the query vector.
        # We pass query_embeddings here so that Gemini's RETRIEVAL_QUERY
        # task_type is used, while the index was built with RETRIEVAL_DOCUMENT.
        faiss_retriever = self.vector_store.as_retriever(
            search_kwargs={"k": k}
        )
        # Override the embedding function used for queries — the vector store
        # was built with doc_embeddings, but queries should use query_embeddings.
        self.vector_store.embedding_function = self.query_embeddings

        if self.bm25_retriever:
            self.bm25_retriever.k = k
            ensemble = EnsembleRetriever(
                retrievers=[self.bm25_retriever, faiss_retriever],
                weights=[bm25_weight, dense_weight],
            )
            return ensemble.invoke(query)
        else:
            return faiss_retriever.invoke(query)

    def _rerank(
        self, query: str, documents: List[Document], top_n: int
    ) -> List[Document]:
        """
        Rerank candidate documents using a cross-encoder model (FlashRank).

        FlashRank is a lightweight (~4MB), CPU-only, ONNX-based cross-encoder
        that scores each (query, document) pair jointly — unlike bi-encoders
        which encode them separately. This joint scoring captures deeper
        semantic interactions and significantly improves ranking precision.

        The reranker is lazily initialised on first use and cached for reuse.
        """
        if self._reranker is None:
            self._reranker = self._build_reranker(top_n)
        else:
            self._reranker.top_n = top_n

        return self._reranker.compress_documents(documents, query)

    @staticmethod
    def _build_reranker(top_n: int):
        """
        Initialise the FlashRank reranker.

        We import lazily to avoid a hard dependency — if flashrank is not
        installed, the rest of the retrieval pipeline still works (just
        without the reranking step).
        """
        try:
            from flashrank import Ranker  # noqa: F401 — must import before FlashrankRerank
            from langchain_community.document_compressors import FlashrankRerank
        except ImportError:
            raise ImportError(
                "FlashRank is required for reranking. "
                "Install it with: pip install flashrank"
            )

        model = os.getenv("RERANKER_MODEL", "ms-marco-MiniLM-L-12-v2")
        return FlashrankRerank(model=model, top_n=top_n)

    # ── Persistence ─────────────────────────────────────────────────────

    def save_local(self, folder_path: str):
        """Save FAISS index and document texts (for BM25 rebuild) to disk."""
        if self.vector_store:
            self.vector_store.save_local(folder_path)

        # Persist document texts separately so BM25 can be rebuilt on load.
        # FAISS's pkl already contains the docstore, but extracting from it
        # is fragile — a small JSON sidecar is more explicit.
        docs_path = os.path.join(folder_path, "bm25_documents.json")
        doc_data = [
            {"page_content": doc.page_content, "metadata": doc.metadata}
            for doc in self._documents
        ]
        with open(docs_path, "w", encoding="utf-8") as f:
            json.dump(doc_data, f, ensure_ascii=False)

        self._write_manifest(folder_path)

    # ── Index trust manifest ────────────────────────────────────────────
    # index.pkl is a pickle, and unpickling a tampered file can run code.
    # Every index this app writes gets a manifest with the SHA-256 of each
    # file plus the embedding provider/model. load_local() refuses anything
    # that does not match, so only indexes built here with the current
    # embeddings are ever deserialised.

    MANIFEST_NAME = "index_manifest.json"
    MANIFEST_FILES = ("index.faiss", "index.pkl", "bm25_documents.json")

    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    def _write_manifest(self, folder_path: str):
        manifest = {
            "provider": self.provider,
            "embedding_model": self.embedding_model,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                name: self._sha256(os.path.join(folder_path, name))
                for name in self.MANIFEST_FILES
                if os.path.exists(os.path.join(folder_path, name))
            },
        }
        with open(os.path.join(folder_path, self.MANIFEST_NAME), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def verify_index(self, folder_path: str) -> dict:
        """
        Confirm an index folder was written by this app with the current
        embedding settings and has not changed since. Raises IndexMismatchError.
        """
        manifest_path = os.path.join(folder_path, self.MANIFEST_NAME)
        if not os.path.exists(manifest_path):
            raise IndexMismatchError(
                "This index has no manifest (built by an older version). Re-process the document."
            )
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        if manifest.get("provider") != self.provider or \
                manifest.get("embedding_model") != self.embedding_model:
            raise IndexMismatchError(
                f"This index was built with {manifest.get('provider')} / "
                f"{manifest.get('embedding_model')}, but the current setting is "
                f"{self.provider} / {self.embedding_model}. Re-process the document."
            )
        for name in self.MANIFEST_FILES:
            expected = manifest.get("files", {}).get(name)
            path = os.path.join(folder_path, name)
            if name == "bm25_documents.json" and expected is None:
                continue
            if not expected or not os.path.exists(path) or self._sha256(path) != expected:
                raise IndexMismatchError(
                    f"{name} does not match its manifest; refusing to load it. Re-process the document."
                )
        return manifest

    def load_local(self, folder_path: str):
        """
        Load FAISS index from disk and rebuild the BM25 index from the
        saved document sidecar.
        """
        self.verify_index(folder_path)
        # Safe to unpickle: verify_index() confirmed these are the exact files
        # this app wrote, for the current embedding model.
        self.vector_store = FAISS.load_local(
            folder_path,
            self.doc_embeddings,
            allow_dangerous_deserialization=True,
            distance_strategy=DistanceStrategy.COSINE,
        )

        # Rebuild BM25 from the sidecar file.
        docs_path = os.path.join(folder_path, "bm25_documents.json")
        if os.path.exists(docs_path):
            with open(docs_path, "r", encoding="utf-8") as f:
                doc_data = json.load(f)
            self._documents = [
                Document(page_content=d["page_content"], metadata=d["metadata"])
                for d in doc_data
            ]
            self._build_bm25(self._documents)
        else:
            # Graceful fallback: if no sidecar exists (e.g., index created
            # before this feature), hybrid search will use FAISS only.
            self._documents = []
            self.bm25_retriever = None
