import argparse
from pathlib import Path
from src.parsers.storage import get_storage
from src.llm.providers.gemini.summarizer import TableSummarizer
from src.parsers.vector_store import VectorStoreManager
from routes.rag_routes import process_documents, query_rag
from dotenv import load_dotenv

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Extract tables from MD, summarize, and RAG.")
    parser.add_argument("--input", type=str, default="assets/markdown/test1_2page_output.md", help="Path to input MD file")
    parser.add_argument("--format", type=str, default="md", choices=["md", "json", "html", "xml"], help="Storage format for extracted tables")
    parser.add_argument("--output_dir", type=str, default="extracted_tables", help="Directory to store extracted tables")
    parser.add_argument("--query", type=str, help="Single query to run (optional)")
    args = parser.parse_args()

    # 1. Setup paths
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    faiss_index_path = Path("faiss_index")

    # 2. Initialize components
    storage = get_storage(args.format)
    summarizer = TableSummarizer()
    vector_mgr = VectorStoreManager()

    # 3 & 4. Process and Vectorize
    if faiss_index_path.exists():
        print("[*] Loading existing FAISS index...")
        vector_mgr.load_local(str(faiss_index_path))
    else:
        process_documents(
            input_path=input_path,
            output_dir=output_dir,
            storage_format=args.format,
            faiss_index_path=faiss_index_path,
            summarizer=summarizer,
            vector_mgr=vector_mgr,
            storage=storage,
            print_func=print
        )

    # 5. RAG Loop or single query
    def run_rag(query_text):
        res = query_rag(query_text, summarizer, vector_mgr, storage, print_func=print)
        if "answer" in res and res["answer"] != "No relevant tables found.":
            print(f"\n[Answer]:\n{res['answer']}\n")

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
