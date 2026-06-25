import os
import json
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, List

from src.parsers.table_processor import parse_bundles_from_md
from src.parsers.mineru_converter import MinerUConverter
from src.parsers.vector_store import VectorStoreManager

def process_documents(
    input_path: Path, 
    output_dir: Path, 
    storage_format: str, 
    faiss_index_path: Path,
    vector_mgr: VectorStoreManager,
    storage: Any,
    print_func=print
) -> bool:
    """
    Process MD document, extract bundles, vectorize table JSON directly,
    and create FAISS index.

    Tables are embedded as JSON chunks - no LLM summarization step.
    The table JSON string is stored as the Document page_content so it
    can be returned directly to the LLM at query time.

    Returns True if successful.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print_func(f"[*] Extracting bundles from {input_path}...")
    bundles = parse_bundles_from_md(input_path)
    
    chunks = []
    metadatas = []
    
    print_func(f"[*] Found {len(bundles)} bundles. Processing...")
    for i, bundle in enumerate(bundles):
        table_id = f"table_{i}"
        grid = bundle["table"]
        context = bundle["context"]
        

        table_json = json.dumps(grid, ensure_ascii=False)
        chunk_text = f"<context>\nCONTEXT:\n{context}\n\nTABLE (JSON):\n{table_json}\n</context>"
        
        file_path = output_dir / table_id
        storage.save(grid, file_path)
        print_func(f"    - Vectorizing bundle {i} directly...")
        
        chunks.append(chunk_text)
        metadata = {
            "table_id": table_id,
            "file_path": str((output_dir / f"{table_id}").with_suffix(f'.{storage_format}')),
            "original_index": i,
            "context_snippet": context[:200]
        }
        page_idx = bundle.get("page_idx")
        if page_idx is not None:
            metadata["page_idx"] = page_idx
        metadatas.append(metadata)

    print_func("[*] Building hybrid index (FAISS + BM25)...")
    vector_mgr.create_index(chunks, metadatas)
    vector_mgr.save_local(str(faiss_index_path))
    
    return True

def query_rag(
    query_text: str,
    summarizer,
    vector_mgr: VectorStoreManager,
    k_val: int = 1,
    k_before_rerank: int | None = None,
    enable_reranking: bool = True,
    print_func=print
) -> Dict[str, Any]:
    """
    Run the hybrid retrieval pipeline and generate an answer.

    Pipeline: hybrid search (FAISS + BM25 with RRF fusion)
              -> cross-encoder reranking (FlashRank)
              -> LLM answer generation from top-k table chunks.
    """
    print_func(f"\n[Query]: {query_text}")
    results = vector_mgr.search(
        query_text,
        k=k_val,
        k_before_rerank=k_before_rerank,
        enable_reranking=enable_reranking,
    )
    if not results:
        print_func("No relevant tables found.")
        return {"answer": "No relevant tables found.", "results": []}


    all_table_sections = []
    
    for i, result in enumerate(results):
        table_id = result.metadata.get("table_id", f"table_{i}")
        chunk_content = result.page_content
        page_idx = result.metadata.get("page_idx")
        
        print_func(f"[*] Retrieved chunk {i+1}/{len(results)}: {table_id}")
        
        table_title = f"=== Table {i+1}: {table_id} ==="
        if page_idx is not None:
            table_title = f"=== Table {i+1}: {table_id} (Page {page_idx + 1}) ==="
            
        all_table_sections.append(
            f"{table_title}\n<context>\n{chunk_content}\n</context>"
        )
    
    combined_tables = "\n\n".join(all_table_sections)
    
    print_func(f"[*] Generating answer using {len(results)} table(s) as context...")
    start_time = time.time()
    answer = summarizer.answer_query(query_text, combined_tables)
    latency = time.time() - start_time
    
    return {
        "answer": answer,
        "table_context": combined_tables,
        "results": results,
        "latency": latency
    }


def process_pdf_to_rag(
    pdf_path: Path,
    output_dir: Path,
    storage_format: str,
    faiss_index_path: Path,
    vector_mgr: VectorStoreManager,
    storage: Any,
    mineru_converter: MinerUConverter | None = None,
    md_output_dir: Path | None = None,
    print_func=print,
) -> Dict[str, Any]:
    """
    Full pipeline: PDF -> Markdown (via MinerU) -> Table extraction -> RAG index.

    Args:
        pdf_path: Path to the input PDF file.
        output_dir: Directory for extracted table files.
        storage_format: Format for saving tables (md, json, html, xml).
        faiss_index_path: Path for the FAISS index.
        vector_mgr: VectorStoreManager instance.
        storage: Storage backend instance.
        mineru_converter: MinerUConverter instance (created if None).
        md_output_dir: Directory for MinerU markdown output (default: assets/markdown/).
        print_func: Callable for progress messages.

    Returns:
        Dict with 'md_path' (Path), 'num_tables' (int), 'elapsed_seconds' (float).
    """
    start_time = time.time()


    if mineru_converter is None:
        mineru_converter = MinerUConverter()

    print_func("[Pipeline] Step 1/2: Converting PDF to Markdown...")
    md_path = mineru_converter.convert(
        pdf_path=pdf_path,
        output_dir=md_output_dir,
        print_func=print_func,
    )


    print_func("[Pipeline] Step 2/2: Processing tables from Markdown...")
    process_documents(
        input_path=md_path,
        output_dir=output_dir,
        storage_format=storage_format,
        faiss_index_path=faiss_index_path,
        vector_mgr=vector_mgr,
        storage=storage,
        print_func=print_func,
    )

    elapsed = time.time() - start_time
    print_func(f"[Pipeline] Complete in {elapsed:.1f}s - Markdown at: {md_path}")

    return {
        "md_path": md_path,
        "elapsed_seconds": elapsed,
    }
