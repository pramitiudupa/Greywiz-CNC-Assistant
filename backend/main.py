import argparse
import os
from pathlib import Path
from src.parsers.storage import get_storage
from src.llm.provider_factory import get_summarizer
from src.parsers.vector_store import VectorStoreManager
from routes.rag_routes import process_documents, process_pdf_to_rag, query_rag
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Extract tables from PDF/MD and RAG.")
    parser.add_argument("--pdf", type=str, help="Path to input PDF file (runs MinerU conversion first)")
    parser.add_argument("--input", type=str, default=None, help="Path to input MD file (skip MinerU)")
    parser.add_argument("--format", type=str, default="md", choices=["md", "json", "html", "xml"],
                        help="Storage format for extracted tables")
    parser.add_argument("--output_dir", type=str, default="extracted_tables",
                        help="Base directory for per-document storage")
    parser.add_argument("--query", type=str, help="Single query to run (optional)")
    parser.add_argument("--provider", type=str, default=None, choices=["ollama", "gemini"],
                        help="LLM provider (default: from LLM_PROVIDER env var, then gemini)")
    args = parser.parse_args()

    if not args.pdf and not args.input:
        args.input = "assets/markdown/test1_2page_output.md"
        print(f"[*] No --pdf or --input specified. Using default: {args.input}")

    input_source = Path(args.pdf or args.input)
    doc_name = input_source.stem
    output_base = Path(args.output_dir)
    doc_dir = output_base / doc_name
    faiss_index_path = doc_dir / "faiss_index"

    storage = get_storage(args.format)
    summarizer = get_summarizer(provider=args.provider)
    vector_mgr = VectorStoreManager(provider=args.provider)

    provider_label = (args.provider or os.getenv("LLM_PROVIDER", "gemini")).upper()
    print(f"[*] Using LLM provider: {provider_label}")
    print(f"[*] Document: {doc_name} -> {doc_dir}")

    if faiss_index_path.exists() and not args.pdf:
        print("[*] Loading existing FAISS index...")
        vector_mgr.load_local(str(faiss_index_path))
    elif args.pdf:
        pdf_path = Path(args.pdf)
        result = process_pdf_to_rag(
            pdf_path=pdf_path,
            output_dir=doc_dir,
            storage_format=args.format,
            faiss_index_path=faiss_index_path,
            vector_mgr=vector_mgr,
            storage=storage,
            print_func=print,
        )
        print(f"[*] Generated markdown at: {result['md_path']}")
    else:
        input_path = Path(args.input)
        process_documents(
            input_path=input_path,
            output_dir=doc_dir,
            storage_format=args.format,
            faiss_index_path=faiss_index_path,
            vector_mgr=vector_mgr,
            storage=storage,
            print_func=print
        )

    def run_rag(query_text):
        k_val = int(os.getenv("RETRIEVAL_K", "1"))
        k_before_rerank = int(os.getenv("RETRIEVAL_K_BEFORE_RERANK", "10"))
        res = query_rag(
            query_text, summarizer, vector_mgr,
            k_val=k_val, k_before_rerank=k_before_rerank,
            print_func=print,
        )
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
