import os
from typing import List, Dict
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()


class VectorStoreManager:
    """
    FAISS vector store with pluggable embeddings backend.

    Supports:
      - "ollama"  → OllamaEmbeddings (local, default)
      - "gemini"  → GoogleGenerativeAIEmbeddings (cloud, requires GOOGLE_API_KEY)

    The provider is chosen via the `provider` constructor argument,
    falling back to the LLM_PROVIDER env var, then to "ollama".
    """

    def __init__(self, provider: str | None = None, model_name: str | None = None):
        provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()
        self.embeddings = self._build_embeddings(provider, model_name)
        self.vector_store = None

    @staticmethod
    def _build_embeddings(provider: str, model_name: str | None):
        if provider == "ollama":
            from langchain_ollama import OllamaEmbeddings

            model_name = model_name or os.getenv(
                "OLLAMA_EMBEDDING_MODEL", "qwen3-embedding"
            )
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
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
            return GoogleGenerativeAIEmbeddings(
                model=model_name, google_api_key=api_key
            )

        else:
            raise ValueError(
                f"Unknown embedding provider '{provider}'. "
                "Supported values: 'ollama', 'gemini'."
            )

    def create_index(self, chunks: List[str], metadatas: List[Dict]):
        documents = [
            Document(page_content=chunk, metadata=metadata)
            for chunk, metadata in zip(chunks, metadatas)
        ]
        self.vector_store = FAISS.from_documents(documents, self.embeddings)

    def search(self, query: str, k: int = 1) -> List[Document]:
        if not self.vector_store:
            raise ValueError("Vector store not initialized. Call create_index first.")
        return self.vector_store.similarity_search(query, k=k)

    def save_local(self, folder_path: str):
        if self.vector_store:
            self.vector_store.save_local(folder_path)

    def load_local(self, folder_path: str):
        self.vector_store = FAISS.load_local(folder_path, self.embeddings, allow_dangerous_deserialization=True)
