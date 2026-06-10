import os
import json
from pathlib import Path
from typing import Dict, Any, List

from src.parsers.table_processor import parse_bundles_from_md
from src.parsers.storage import get_storage
from src.llm.providers.gemini.summarizer import TableSummarizer
from src.parsers.vector_store import VectorStoreManager

def process_documents(
    input_path: Path, 
    output_dir: Path, 
    storage_format: str, 
    faiss_index_path: Path,
    summarizer: TableSummarizer,
    vector_mgr: VectorStoreManager,
    storage: Any,
    print_func=print
) -> bool:
    """
    Process MD document, extract bundles, summarize, and create FAISS index.
    Returns True if successful.
    """
    output_dir.mkdir(exist_ok=True)
    cache_file = output_dir / "table_metadata.json"
    cached_data = {}
    
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_data = json.load(f)

    print_func(f"[*] Extracting bundles from {input_path}...")
    bundles = parse_bundles_from_md(input_path)
    
    summaries = []
    metadatas = []
    new_cache = {}
    
    print_func(f"[*] Found {len(bundles)} bundles. Processing...")
    for i, bundle in enumerate(bundles):
        table_id = f"table_{i}"
        grid = bundle["table"]
        context = bundle["context"]
        
        content_to_hash = json.dumps(grid) + context
        content_hash = hash(content_to_hash)
        
        if table_id in cached_data and cached_data[table_id].get("content_hash") == content_hash:
            print_func(f"    - Using cached summary for bundle {i}...")
            summary = cached_data[table_id]["summary"]
            file_path = Path(cached_data[table_id]["file_path"])
        else:
            file_name = f"{table_id}"
            file_path = output_dir / file_name
            storage.save(grid, file_path)
            print_func(f"    - Summarizing bundle {i} (with context)...")
            summary = summarizer.summarize_bundle(context, grid)
        
        summaries.append(summary)
        metadata = {
            "table_id": table_id,
            "file_path": str(file_path.with_suffix(f'.{storage_format}')),
            "original_index": i,
            "summary": summary,
            "content_hash": content_hash,
            "context_snippet": context[:200]
        }
        metadatas.append(metadata)
        new_cache[table_id] = metadata

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(new_cache, f, indent=4)

    print_func("[*] Creating FAISS index...")
    vector_mgr.create_index(summaries, metadatas)
    vector_mgr.save_local(str(faiss_index_path))
    
    return True

def query_rag(
    query_text: str,
    summarizer: TableSummarizer,
    vector_mgr: VectorStoreManager,
    storage: Any,
    print_func=print
) -> Dict[str, Any]:
    """
    Search the vector store and generate an answer for the query.
    """
    # Retrieve k from env, default to 1
    k_val = int(os.getenv("RETRIEVAL_K", "1"))
    
    print_func(f"\n[Query]: {query_text}")
    results = vector_mgr.search(query_text, k=k_val)
    if not results:
        print_func("No relevant tables found.")
        return {"answer": "No relevant tables found.", "results": []}

    top_result = results[0]
    table_file_path = Path(top_result.metadata["file_path"])
    summary = top_result.metadata.get("summary", "")
    
    table_context = storage.load(table_file_path)
    
    print_func(f"[*] Found relevant table: {table_file_path.name}")
    print_func("[*] Generating answer...")
    answer = summarizer.answer_query(query_text, table_context, summary=summary)
    
    return {
        "answer": answer,
        "table_context": table_context,
        "results": results
    }
