import argparse
import os
import json
from pathlib import Path
from table_processor import parse_bundles_from_md
from storage import get_storage
from summarizer import TableSummarizer
from vector_store import VectorStoreManager
from dotenv import load_dotenv

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Extract tables from MD, summarize, and RAG.")
    parser.add_argument("--input", type=str, required=True, help="Path to input MD file")
    parser.add_argument("--format", type=str, default="md", choices=["md", "json", "html", "xml"], help="Storage format for extracted tables")
    parser.add_argument("--output_dir", type=str, default="extracted_tables", help="Directory to store extracted tables")
    parser.add_argument("--query", type=str, help="Single query to run (optional)")
    args = parser.parse_args()

    # 1. Setup paths
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    faiss_index_path = "faiss_index"

    # 2. Initialize components
    storage = get_storage(args.format)
    summarizer = TableSummarizer()
    vector_mgr = VectorStoreManager()

    # 3. Process tables (Extraction & Summarization)
    cache_file = output_dir / "table_metadata.json"
    cached_data = {}
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_data = json.load(f)

    print(f"[*] Extracting bundles from {input_path}...")
    bundles = parse_bundles_from_md(input_path)
    
    summaries = []
    metadatas = []
    new_cache = {}
    
    print(f"[*] Found {len(bundles)} bundles. Processing...")
    for i, bundle in enumerate(bundles):
        table_id = f"table_{i}"
        grid = bundle["table"]
        context = bundle["context"]
        
        # Create a simple hash or key for the table content + context to detect changes
        content_to_hash = json.dumps(grid) + context
        content_hash = hash(content_to_hash)
        
        if table_id in cached_data and cached_data[table_id].get("content_hash") == content_hash:
            print(f"    - Using cached summary for bundle {i}...")
            summary = cached_data[table_id]["summary"]
            file_path = Path(cached_data[table_id]["file_path"])
        else:
            file_name = f"{table_id}"
            file_path = output_dir / file_name
            # Save table in chosen format
            storage.save(grid, file_path)
            # Generate intelligent summary
            print(f"    - Summarizing bundle {i} (with context)...")
            summary = summarizer.summarize_bundle(context, grid)
        
        summaries.append(summary)
        metadata = {
            "table_id": table_id,
            "file_path": str(file_path.with_suffix(f'.{args.format}')),
            "original_index": i,
            "summary": summary,
            "content_hash": content_hash,
            "context_snippet": context[:200] # Store a snippet for debugging
        }
        metadatas.append(metadata)
        new_cache[table_id] = metadata

    # Save cache
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(new_cache, f, indent=4)

    # 4. Vectorize and store
    if Path(faiss_index_path).exists():
        print("[*] Loading existing FAISS index...")
        vector_mgr.load_local(faiss_index_path)
    else:
        print("[*] Creating FAISS index...")
        vector_mgr.create_index(summaries, metadatas)
        vector_mgr.save_local(faiss_index_path)

    # 5. RAG Loop or single query
    def run_rag(query_text):
        print(f"\n[Query]: {query_text}")
        results = vector_mgr.search(query_text, k=4)
        if not results:
            print("No relevant tables found.")
            return

        retrieved_contexts = []
        for res in results:
            table_file_path = Path(res.metadata["file_path"])
            summary = res.metadata.get("summary", "")
            table_context = storage.load(table_file_path)
            retrieved_contexts.append({
                "name": table_file_path.name,
                "summary": summary,
                "table_data": table_context
            })
        
        print(f"[*] Found {len(results)} relevant tables.")
        print("[*] Generating answer...")
        answer = summarizer.answer_query(query_text, retrieved_contexts)
        print(f"\n[Answer]:\n{answer}\n")

    if args.query:
        run_rag(args.query)
    else:
        print("\n--- Interactive RAG Mode (type 'exit' to quit) ---")
        while True:
            user_query = input("Ask a question about the tables: ")
            if user_query.lower() in ["exit", "quit"]:
                break
            if not user_query.strip():
                continue
            run_rag(user_query)

if __name__ == "__main__":
    main()
