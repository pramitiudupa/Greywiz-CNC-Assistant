"""
FastAPI server for TableWIZ frontend.

Provides REST endpoints for:
  - Listing / uploading / processing documents
  - RAG-based chat queries
"""

import asyncio
import os
import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from src.parsers.storage import get_storage
from src.llm.provider_factory import get_summarizer
from src.parsers.vector_store import VectorStoreManager
from routes.rag_routes import process_documents, process_pdf_to_rag, query_rag

app = FastAPI(title="TableWIZ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_BASE = Path("extracted_tables")
PDFS_DIR = Path("assets/pdfs")


# ── Helpers ──────────────────────────────────────────────────────────────

def _get_tools(provider: str | None = None, storage_format: str = "json"):
    """Create summarizer, vector_mgr, and storage instances."""
    return {
        "summarizer": get_summarizer(provider=provider),
        "vector_mgr": VectorStoreManager(provider=provider),
        "storage": get_storage(storage_format),
    }


def _doc_summary(doc_name: str) -> dict:
    """Build a summary dict for a single document."""
    doc_dir = OUTPUT_BASE / doc_name
    has_index = (doc_dir / "faiss_index" / "index.faiss").exists()

    # Detect status
    table_files = [
        f for f in doc_dir.iterdir()
        if f.is_file() and f.suffix in (".json", ".md", ".html", ".xml")
    ] if doc_dir.exists() else []

    if has_index:
        status = "completed"
    elif table_files:
        status = "partial"
    else:
        status = "processing"

    # Try to find original PDF size
    pdf_path = PDFS_DIR / f"{doc_name}.pdf"
    size_bytes = pdf_path.stat().st_size if pdf_path.exists() else None

    tables = []
    for f in table_files:
        tables.append({
            "id": f.stem,
            "name": f.name,
            "format": f.suffix.lstrip("."),
            "size_bytes": f.stat().st_size,
        })

    return {
        "id": doc_name,
        "name": f"{doc_name}.pdf",
        "status": status,
        "size_bytes": size_bytes,
        "has_index": has_index,
        "table_count": len(table_files),
        "tables": tables,
    }


# ── Request / Response Models ────────────────────────────────────────────

class ChatRequest(BaseModel):
    document_id: str
    message: str
    retrieval_k: int = 1
    provider: Optional[str] = None
    enable_reranking: bool = True


class ChatResponse(BaseModel):
    answer: str
    table_context: str
    results: list


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/documents")
async def list_documents():
    """List all documents that have been processed or are in progress."""
    if not OUTPUT_BASE.exists():
        return {"documents": []}

    documents = []
    for d in sorted(OUTPUT_BASE.iterdir()):
        if d.is_dir():
            try:
                documents.append(_doc_summary(d.name))
            except Exception:
                pass
    return {"documents": documents}


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    process: str = Form("true"),
    storage_format: str = Form("json"),
    provider: Optional[str] = Form(None),
):
    """Upload a PDF and optionally process it immediately."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")

    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = PDFS_DIR / file.filename
    content = await file.read()
    pdf_path.write_bytes(content)

    doc_name = pdf_path.stem
    doc_dir = OUTPUT_BASE / doc_name
    faiss_path = doc_dir / "faiss_index"

    processed = False

    if process.lower() == "true":
        tools = _get_tools(provider=provider, storage_format=storage_format)
        try:
            await asyncio.to_thread(
                process_pdf_to_rag,
                pdf_path=pdf_path,
                output_dir=doc_dir,
                storage_format=storage_format,
                faiss_index_path=faiss_path,
                vector_mgr=tools["vector_mgr"],
                storage=tools["storage"],
                print_func=print,
            )
            processed = True
        except Exception as e:
            print(f"[ERROR] Processing failed for {doc_name}: {e}")
            # Still return the document even if processing fails
            raise HTTPException(500, f"Processing failed: {e}")

    return {
        "document": _doc_summary(doc_name),
        "processed": processed,
    }


@app.post("/api/documents/{document_id}/process")
async def process_document(document_id: str, body: dict = {}):
    """(Re-)process an already-uploaded document."""
    pdf_path = PDFS_DIR / f"{document_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, f"PDF not found for document '{document_id}'.")

    storage_format = body.get("storage_format", "json")
    provider = body.get("provider")
    force = body.get("force", False)

    doc_dir = OUTPUT_BASE / document_id
    faiss_path = doc_dir / "faiss_index"

    if force and doc_dir.exists():
        shutil.rmtree(doc_dir)

    tools = _get_tools(provider=provider, storage_format=storage_format)

    try:
        await asyncio.to_thread(
            process_pdf_to_rag,
            pdf_path=pdf_path,
            output_dir=doc_dir,
            storage_format=storage_format,
            faiss_index_path=faiss_path,
            vector_mgr=tools["vector_mgr"],
            storage=tools["storage"],
            print_func=print,
        )
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")

    return {
        "document": _doc_summary(document_id),
        "processed": True,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Answer a question against a processed document's table index."""
    doc_dir = OUTPUT_BASE / req.document_id
    faiss_path = doc_dir / "faiss_index"

    if not (faiss_path / "index.faiss").exists():
        raise HTTPException(404, f"No index found for document '{req.document_id}'.")

    tools = _get_tools(provider=req.provider)
    tools["vector_mgr"].load_local(str(faiss_path))

    k_before_rerank = int(os.getenv("RETRIEVAL_K_BEFORE_RERANK", "15"))

    def run_query():
        return query_rag(
            query_text=req.message,
            summarizer=tools["summarizer"],
            vector_mgr=tools["vector_mgr"],
            k_val=req.retrieval_k,
            k_before_rerank=k_before_rerank,
            enable_reranking=req.enable_reranking,
            print_func=print,
        )

    try:
        response = await asyncio.to_thread(run_query)
    except Exception as e:
        raise HTTPException(500, f"Query failed: {e}")

    # Serialize results for JSON response
    def clean_val(v):
        if hasattr(v, "item") and not isinstance(v, (str, int, float, bool, list, dict, type(None))):
            return v.item()
        if isinstance(v, dict):
            return {k: clean_val(val) for k, val in v.items()}
        if isinstance(v, list):
            return [clean_val(val) for val in v]
        return v

    serialized_results = []
    for r in response.get("results", []):
        metadata = {}
        if hasattr(r, "metadata"):
            metadata = {k: clean_val(v) for k, v in r.metadata.items()}
        serialized_results.append({
            "content": r.page_content if hasattr(r, "page_content") else str(r),
            "metadata": metadata,
        })

    return {
        "answer": response.get("answer", ""),
        "table_context": response.get("table_context", ""),
        "results": serialized_results,
        "latency": response.get("latency", 0.0),
    }


@app.get("/api/documents/{document_id}/pdf/origin")
async def get_origin_pdf(document_id: str):
    """Serve the original PDF of the document."""
    paths = [
        PDFS_DIR / f"{document_id}.pdf",
        Path("assets/markdown") / document_id / "auto" / f"{document_id}_origin.pdf",
        Path("assets/markdown") / document_id / document_id / "auto" / f"{document_id}_origin.pdf",
    ]
    for p in paths:
        if p.exists():
            return FileResponse(
                p,
                media_type="application/pdf",
                filename=f"{document_id}_origin.pdf",
                content_disposition_type="inline"
            )
    raise HTTPException(404, "Original PDF not found.")


@app.get("/api/documents/{document_id}/pdf/layout")
async def get_layout_pdf(document_id: str):
    """Serve the annotated layout PDF of the document."""
    paths = [
        Path("assets/markdown") / document_id / "auto" / f"{document_id}_layout.pdf",
        Path("assets/markdown") / document_id / document_id / "auto" / f"{document_id}_layout.pdf",
    ]
    for p in paths:
        if p.exists():
            return FileResponse(
                p,
                media_type="application/pdf",
                filename=f"{document_id}_layout.pdf",
                content_disposition_type="inline"
            )
    raise HTTPException(404, "Annotated layout PDF not found.")
