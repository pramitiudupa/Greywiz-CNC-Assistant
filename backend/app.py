import streamlit as st
import os
import shutil
import base64
from pathlib import Path
from src.parsers.storage import get_storage
from src.llm.provider_factory import get_summarizer
from src.parsers.vector_store import VectorStoreManager
from routes.rag_routes import process_documents, process_pdf_to_rag, query_rag
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="TableRAG Chat", layout="wide")
st.title("TableRAG: Extract & Chat")

OUTPUT_BASE = Path("extracted_tables")


def get_processed_or_partial_docs():
    """Return names of documents that have either a FAISS index or extracted table files."""
    if not OUTPUT_BASE.exists():
        return []
    docs = []
    for d in OUTPUT_BASE.iterdir():
        if d.is_dir():
            has_index = (d / "faiss_index" / "index.faiss").exists()
            has_tables = any(
                f.suffix in (".json", ".md", ".html", ".xml")
                for f in d.iterdir()
                if f.is_file()
            )
            if has_index or has_tables:
                docs.append(d.name)
    return sorted(docs)


@st.cache_resource
def get_tools(storage_format: str, llm_provider: str):
    return {
        "summarizer": get_summarizer(provider=llm_provider),
        "vector_mgr": VectorStoreManager(provider=llm_provider),
        "storage": get_storage(storage_format)
    }


with st.sidebar:
    st.header("Settings")

    st.subheader("LLM Provider")
    default_provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    provider_options = ["gemini", "ollama"]
    llm_provider = st.selectbox(
        "Choose provider",
        options=provider_options,
        index=provider_options.index(default_provider),
        help="Gemini requires a GOOGLE_API_KEY and internet access. Ollama runs locally."
    )

    retrieval_k = st.slider(
        "Retrieved Chunks (k)", 
        min_value=1, 
        max_value=15, 
        value=int(os.getenv("RETRIEVAL_K", "5")), 
        help="Final number of table chunks returned after hybrid search and reranking."
    )

    enable_reranker = st.toggle(
        "Enable FlashRank Reranker",
        value=True,
        help="Use cross-encoder to rerank hybrid search results. Turn off if correct tables are being pushed down."
    )

    st.divider()

    st.subheader("Upload PDF")
    uploaded_pdf = st.file_uploader(
        "Upload a PDF to process",
        type=["pdf"],
        help="The PDF will be converted to Markdown via MinerU, then tables are extracted and indexed."
    )
    process_pdf_btn = st.button("Process Document")

    st.divider()

    st.subheader("Documents")
    available_docs = get_processed_or_partial_docs()
    if available_docs:
        default_idx = 0
        if st.session_state.get("active_doc") in available_docs:
            default_idx = available_docs.index(st.session_state["active_doc"])
        selected_doc = st.selectbox("Select Processed PDF", available_docs, index=default_idx)
    else:
        selected_doc = None
        st.caption("No processed PDFs yet.")


if "active_doc" not in st.session_state:
    st.session_state.active_doc = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_vector_mgr" not in st.session_state:
    st.session_state.active_vector_mgr = None
if "active_summarizer" not in st.session_state:
    st.session_state.active_summarizer = None
if "last_llm_provider" not in st.session_state:
    st.session_state.last_llm_provider = None

# Clear cached tools and reset session if provider changed
if st.session_state.last_llm_provider != llm_provider:
    get_tools.clear()
    st.session_state.last_llm_provider = llm_provider
    st.session_state.active_vector_mgr = None
    st.session_state.active_summarizer = None
    st.session_state.active_doc = None
    st.session_state.messages = []


def activate_doc(doc_name: str):
    """Load a document's FAISS index."""
    doc_dir = OUTPUT_BASE / doc_name
    faiss_path = doc_dir / "faiss_index"
    has_index = (faiss_path / "index.faiss").exists()
    
    # Hardcode JSON as storage format for processing
    current_tools = get_tools("json", llm_provider)

    if not has_index:
        st.error(f"Cannot activate '{doc_name}': FAISS index is missing.")
        return

    # Load the index
    current_tools["vector_mgr"].load_local(str(faiss_path))
    st.session_state.active_vector_mgr = current_tools["vector_mgr"]
    st.session_state.active_summarizer = current_tools["summarizer"]
    if st.session_state.active_doc != doc_name:
        st.session_state.messages = []
    st.session_state.active_doc = doc_name


def process_uploaded_pdf(uploaded_file):
    """Save uploaded PDF and run the full MinerU -> TableRAG pipeline."""
    pdfs_dir = Path("assets/pdfs")
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdfs_dir / uploaded_file.name
    pdf_path.write_bytes(uploaded_file.getvalue())

    doc_name = pdf_path.stem
    doc_dir = OUTPUT_BASE / doc_name
    faiss_path = doc_dir / "faiss_index"

    current_tools = get_tools("json", llm_provider)

    with st.status("Processing PDF...", expanded=True) as status:
        st.write(f"Saved PDF: {pdf_path}")
        try:
            process_pdf_to_rag(
                pdf_path=pdf_path,
                output_dir=doc_dir,
                storage_format="json",
                faiss_index_path=faiss_path,
                vector_mgr=current_tools["vector_mgr"],
                storage=current_tools["storage"],
                print_func=st.write,
            )
            st.session_state.active_vector_mgr = current_tools["vector_mgr"]
            st.session_state.active_summarizer = current_tools["summarizer"]
            status.update(label="Processing complete!", state="complete")
        except FileNotFoundError as e:
            status.update(label="MinerU not found", state="error")
            st.error(
                f"MinerU CLI not found: {e}\n\n"
                "Install MinerU with: `pip install 'mineru[all]'`\n"
                "Or set `MINERU_BINARY_PATH` in your `.env` file."
            )
            return None
        except RuntimeError as e:
            status.update(label="Processing failed", state="error")
            st.error(f"Pipeline error: {e}")
            return None

    return doc_name


with st.sidebar:
    if st.session_state.get("active_doc") and st.button("Re-process Current Document"):
        doc_dir = OUTPUT_BASE / st.session_state.active_doc
        if doc_dir.exists():
            # Add safety check before rmtree
            if "extracted_tables" in str(doc_dir.resolve()):
                shutil.rmtree(doc_dir)
        st.session_state.active_doc = None
        st.session_state.active_vector_mgr = None
        st.session_state.active_summarizer = None
        st.session_state.messages = []
        get_tools.clear()
        st.rerun()


if uploaded_pdf is not None:
    doc_name = Path(uploaded_pdf.name).stem
    doc_faiss = OUTPUT_BASE / doc_name / "faiss_index" / "index.faiss"
    if not doc_faiss.exists():
        if process_pdf_btn:
            result = process_uploaded_pdf(uploaded_pdf)
            if result:
                activate_doc(result)
                st.rerun()
    elif st.session_state.active_doc != doc_name:
        activate_doc(doc_name)

elif selected_doc and st.session_state.active_doc != selected_doc:
    activate_doc(selected_doc)

elif not st.session_state.active_doc and available_docs:
    activate_doc(available_docs[0])


if st.session_state.active_doc:
    st.caption(f"Active: **{st.session_state.active_doc}** | Provider: **{llm_provider}**")
    
    doc_name = st.session_state.active_doc
    base_md_dir = Path("assets/markdown") / doc_name / "auto"
    if not base_md_dir.exists():
        base_md_dir = Path("assets/markdown") / doc_name / doc_name / "auto"
        
    origin_pdf = base_md_dir / f"{doc_name}_origin.pdf"
    layout_pdf = base_md_dir / f"{doc_name}_layout.pdf"
    if not origin_pdf.exists():
        origin_pdf = Path("assets/pdfs") / f"{doc_name}.pdf"
        
    if origin_pdf.exists():
        with st.expander("View Original PDF"):
            with open(origin_pdf, "rb") as f:
                pdf_bytes = f.read()
            st.download_button("Download Original PDF", data=pdf_bytes, file_name=f"{doc_name}_origin.pdf", mime="application/pdf", key="orig_pdf")
            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            st.markdown(f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>', unsafe_allow_html=True)
            
    if layout_pdf.exists():
        with st.expander("View Annotated Layout PDF"):
            with open(layout_pdf, "rb") as f:
                pdf_bytes = f.read()
            st.download_button("Download Annotated PDF", data=pdf_bytes, file_name=f"{doc_name}_layout.pdf", mime="application/pdf", key="layout_pdf")
            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            st.markdown(f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>', unsafe_allow_html=True)

    st.divider()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "table_html" in message:
            with st.expander("View Source Tables"):
                st.markdown(message["table_html"], unsafe_allow_html=True)
        elif "table" in message:
            with st.expander("View Source Tables (Legacy)"):
                st.code(message["table"])

if st.session_state.active_doc:
    if query := st.chat_input("Ask a question about the tables..."):
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Searching and generating answer..."):
                res = query_rag(
                    query_text=query,
                    summarizer=st.session_state.active_summarizer,
                    vector_mgr=st.session_state.active_vector_mgr,
                    k_val=retrieval_k,
                    k_before_rerank=int(os.getenv("RETRIEVAL_K_BEFORE_RERANK", "15")),
                    enable_reranking=enable_reranker,
                    print_func=lambda x: None,
                )

                if res.get("results"):
                    latency = res.get('latency', 0)
                    answer_with_latency = f"{res['answer']}\n\n*Answer generated in {latency:.2f} seconds.*"
                    st.markdown(answer_with_latency)
                    
                    # Build HTML for source tables
                    html_parts = []
                    for i, result in enumerate(res["results"]):
                        table_id = result.metadata.get("table_id", f"table_{i}")
                        page_idx = result.metadata.get("page_idx")
                        title = f"Table {i+1}: {table_id}"
                        if page_idx is not None:
                            title += f" (Page {page_idx + 1})"
                        
                        content = result.page_content
                        context_part = ""
                        table_part = content
                        if "TABLE (JSON):\n" in content:
                            parts = content.split("TABLE (JSON):\n")
                            context_part = parts[0].replace("<context>\nCONTEXT:\n", "").strip()
                            table_part = parts[1].replace("</context>", "").strip()
                        
                        import html
                        html_parts.append(f"<h4>{title}</h4>")
                        if context_part:
                            safe_context = html.escape(context_part)
                            html_parts.append(f"<details><summary><b>View Surrounding Context</b></summary><pre><code>{safe_context}</code></pre></details>")
                        safe_table = html.escape(table_part)
                        html_parts.append(f"<pre><code>{safe_table}</code></pre>")
                    
                    table_html = "<hr>".join(html_parts)
                    
                    with st.expander("View Source Tables"):
                        st.markdown(table_html, unsafe_allow_html=True)
                        
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer_with_latency,
                        "table": res["table_context"],
                        "table_html": table_html
                    })
                else:
                    st.error("No relevant tables found.")
