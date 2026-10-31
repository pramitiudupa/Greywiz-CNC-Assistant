"""
FastAPI server for TableWIZ frontend.

Provides REST endpoints for:
  - Listing / uploading / processing documents
  - RAG-based chat queries
"""

import asyncio
import os
import json
import re
import shutil
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from src.parsers.storage import get_storage
from src.llm.provider_factory import get_summarizer
from src.parsers.vector_store import IndexMismatchError, VectorStoreManager
from src.diagnosis import store as diagnosis_store
from src.diagnosis.engine import diagnose, prepare_photo
from routes.rag_routes import process_documents, process_pdf_to_rag, query_rag

app = FastAPI(title="Greywiz CNC API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_BASE = Path("extracted_tables")
PDFS_DIR = Path("assets/pdfs")
MARKDOWN_DIR = Path("assets/markdown")
MAX_PHOTO_BYTES = 15 * 1024 * 1024
UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9 ._()-]+")


# ── Helpers ──────────────────────────────────────────────────────────────

def _safe_stem(filename: str) -> str:
    """Turn an uploaded file name into a stem that cannot escape its folder."""
    stem = UNSAFE_NAME_CHARS.sub("_", Path(filename).stem).strip(" ._")
    if not stem:
        raise HTTPException(400, "File name is not usable; rename the file and try again.")
    return stem[:120]


def _remove_inside(base: Path, target: Path):
    """Delete a generated folder or file, only if it really sits inside *base*."""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if target_resolved == base_resolved or base_resolved not in target_resolved.parents:
        raise HTTPException(400, f"Refusing to delete {target}: it is outside {base}.")
    if target_resolved.is_dir():
        shutil.rmtree(target_resolved)
    elif target_resolved.exists():
        target_resolved.unlink()


def _document_dir(document_id: str) -> Path:
    if document_id != _safe_stem(document_id + ".pdf"):
        raise HTTPException(400, "Invalid document id.")
    return OUTPUT_BASE / document_id


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
    pdf_path = PDFS_DIR / f"{_safe_stem(file.filename)}.pdf"
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
async def process_document(document_id: str, body: dict = Body(default_factory=dict)):
    """(Re-)process an already-uploaded document."""
    doc_dir = _document_dir(document_id)
    pdf_path = PDFS_DIR / f"{document_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, f"PDF not found for document '{document_id}'.")

    storage_format = body.get("storage_format", "json")
    provider = body.get("provider")
    force = body.get("force", False)

    faiss_path = doc_dir / "faiss_index"

    if force and doc_dir.exists():
        _remove_inside(OUTPUT_BASE, doc_dir)

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
    doc_dir = _document_dir(req.document_id)
    faiss_path = doc_dir / "faiss_index"

    if not (faiss_path / "index.faiss").exists():
        raise HTTPException(404, f"No index found for document '{req.document_id}'.")

    tools = _get_tools(provider=req.provider)
    try:
        tools["vector_mgr"].load_local(str(faiss_path))
    except IndexMismatchError as e:
        raise HTTPException(409, str(e))

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


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "provider": os.getenv("LLM_PROVIDER", "ollama"),
        "gemini_key_set": bool(os.getenv("GOOGLE_API_KEY")),
    }


@app.get("/api/documents/{document_id}/tables")
async def get_document_tables(document_id: str):
    """Return every extracted table of a document as a grid."""
    doc_dir = _document_dir(document_id)
    if not doc_dir.exists():
        raise HTTPException(404, f"Document '{document_id}' not found.")
    tables = []
    for path in sorted(doc_dir.glob("table_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        tables.append({"id": path.stem, "grid": json.loads(path.read_text(encoding="utf-8"))})
    return {"document_id": document_id, "tables": tables}


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str):
    """Remove a document's PDF, MinerU output and index."""
    doc_dir = _document_dir(document_id)
    targets = [
        (OUTPUT_BASE, doc_dir),
        (PDFS_DIR, PDFS_DIR / f"{document_id}.pdf"),
        (MARKDOWN_DIR, MARKDOWN_DIR / document_id),
        (MARKDOWN_DIR, MARKDOWN_DIR / f"{document_id}.md"),
    ]
    found = [(base, target) for base, target in targets if target.exists()]
    if not found:
        raise HTTPException(404, f"Document '{document_id}' not found.")
    for base, target in found:
        _remove_inside(base, target)
    return {"deleted": document_id}


# ── CNC machine and fault diagnosis ──────────────────────────────────────

@app.get("/api/machine")
async def get_machine():
    return {"machine": diagnosis_store.load_machine()}


@app.put("/api/machine")
async def put_machine(body: dict = Body(...)):
    try:
        return {"machine": diagnosis_store.save_machine(body)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/diagnose")
async def diagnose_problem(
    description: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    provider: Optional[str] = Form(None),
):
    """Find the likely cause of a machine problem from a photo and/or description."""
    photo_bytes, photo_ext = None, ".jpg"
    if photo is not None and photo.filename:
        raw = await photo.read()
        if len(raw) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "Photo is larger than 15 MB.")
        if raw:
            try:
                photo_bytes, photo_ext = prepare_photo(raw)
            except ValueError as e:
                raise HTTPException(400, str(e))

    if not description.strip() and not photo_bytes:
        raise HTTPException(400, "Add a photo of the problem or describe it in words.")

    try:
        result = await asyncio.to_thread(
            diagnose, description, photo_bytes, OUTPUT_BASE, provider
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        print(f"[ERROR] Diagnosis failed: {e!r}")
        raise HTTPException(500, f"Diagnosis failed: {e}")

    case = diagnosis_store.create_case(description.strip(), photo_bytes, photo_ext, result)
    return {"case_id": case["id"], "created_at": case["created_at"], **result}


@app.get("/api/cases")
async def list_cases():
    cases = diagnosis_store.list_cases()
    return {"cases": [
        {
            "id": c["id"],
            "created_at": c["created_at"],
            "description": c["description"],
            "has_photo": bool(c.get("photo")),
            "status": c["status"],
            "fix_note": c.get("fix_note", ""),
            "summary": (c.get("result") or {}).get("summary", ""),
        }
        for c in cases
    ]}


@app.get("/api/cases/{case_id}")
async def get_case(case_id: str):
    try:
        case = diagnosis_store.get_case(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if case is None:
        raise HTTPException(404, "Case not found.")
    return case


@app.get("/api/cases/{case_id}/photo")
async def get_case_photo(case_id: str):
    try:
        case = diagnosis_store.get_case(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    path = diagnosis_store.photo_path(case) if case else None
    if path is None:
        raise HTTPException(404, "No photo for this case.")
    return FileResponse(path, media_type="image/jpeg")


class CaseUpdate(BaseModel):
    status: str
    fix_note: str = ""


@app.patch("/api/cases/{case_id}")
async def update_case(case_id: str, body: CaseUpdate):
    try:
        return diagnosis_store.update_case(case_id, body.status, body.fix_note)
    except KeyError:
        raise HTTPException(404, "Case not found.")
    except ValueError as e:
        raise HTTPException(400, str(e))
