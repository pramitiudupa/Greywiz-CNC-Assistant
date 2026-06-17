import streamlit as st
import os
import shutil
from pathlib import Path
from src.parsers.storage import get_storage
from src.llm.provider_factory import get_summarizer
from src.parsers.vector_store import VectorStoreManager
from routes.rag_routes import process_documents, process_pdf_to_rag, query_rag
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="TableRAG Chat", layout="wide")
st.title("📊 TableRAG: Extract & Chat")

OUTPUT_BASE = Path("extracted_tables")


def get_processed_docs():
    """Return names of documents that have a completed FAISS index."""
    if not OUTPUT_BASE.exists():
        return []
    return sorted([
        d.name for d in OUTPUT_BASE.iterdir()
        if d.is_dir() and (d / "faiss_index" / "index.faiss").exists()
    ])


with st.sidebar:
    st.header("Settings")

    st.subheader("🤖 LLM Provider")
    llm_provider = st.selectbox(
        "Choose provider",
        options=["ollama", "gemini"],
        index=0,
        help="Ollama runs locally (no API key). Gemini requires a GOOGLE_API_KEY in .env."
    )

    st.divider()

    st.subheader("📄 Upload PDF")
    uploaded_pdf = st.file_uploader(
        "Upload a PDF to process",
        type=["pdf"],
        help="The PDF will be converted to Markdown via MinerU, then tables are extracted and indexed."
    )

    st.divider()

    st.subheader("📝 Or use existing Markdown")
    input_file = st.text_input("Input MD File", value="assets/markdown/test1_2page_output.md")
    process_md_btn = st.button("Process Markdown")

    st.divider()

    st.subheader("⚙️ Processing")
    storage_format = st.selectbox("Storage Format", options=["md", "json", "html", "xml"], index=1)

    st.divider()

    st.subheader("📂 Documents")
    available_docs = get_processed_docs()
    if available_docs:
        default_idx = 0
        if st.session_state.get("active_doc") in available_docs:
            default_idx = available_docs.index(st.session_state["active_doc"])
        selected_doc = st.selectbox("Select document", available_docs, index=default_idx)
    else:
        selected_doc = None
        st.caption("No processed documents yet.")


@st.cache_resource
def get_tools(storage_format: str, llm_provider: str):
    return {
        "summarizer": get_summarizer(provider=llm_provider),
        "vector_mgr": VectorStoreManager(provider=llm_provider),
        "storage": get_storage(storage_format)
    }


tools = get_tools(storage_format, llm_provider)

with st.sidebar:
    if st.session_state.get("active_doc") and st.button("🔄 Re-process Current Document"):
        doc_dir = OUTPUT_BASE / st.session_state.active_doc
        if doc_dir.exists():
            shutil.rmtree(doc_dir)
        st.session_state.active_doc = None
        st.session_state.messages = []
        get_tools.clear()
        st.rerun()

if "active_doc" not in st.session_state:
    st.session_state.active_doc = None
if "messages" not in st.session_state:
    st.session_state.messages = []


def activate_doc(doc_name: str):
    """Load a document's FAISS index and set it as active."""
    faiss_path = OUTPUT_BASE / doc_name / "faiss_index"
    tools["vector_mgr"].load_local(str(faiss_path))
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

    with st.status("🔄 Processing PDF...", expanded=True) as status:
        st.write(f"📄 Saved PDF: {pdf_path}")
        try:
            process_pdf_to_rag(
                pdf_path=pdf_path,
                output_dir=doc_dir,
                storage_format=storage_format,
                faiss_index_path=faiss_path,
                vector_mgr=tools["vector_mgr"],
                storage=tools["storage"],
                print_func=st.write,
            )
            status.update(label="✅ Processing complete!", state="complete")
        except FileNotFoundError as e:
            status.update(label="❌ MinerU not found", state="error")
            st.error(
                f"MinerU CLI not found: {e}\n\n"
                "Install MinerU with: `pip install 'mineru[all]'`\n"
                "Or set `MINERU_BINARY_PATH` in your `.env` file."
            )
            return None
        except RuntimeError as e:
            status.update(label="❌ Processing failed", state="error")
            st.error(f"Pipeline error: {e}")
            return None

    return doc_name


def process_md_file(md_file_path: str):
    """Process a Markdown file through the table extraction pipeline."""
    md_path = Path(md_file_path)
    doc_name = md_path.stem
    doc_dir = OUTPUT_BASE / doc_name
    faiss_path = doc_dir / "faiss_index"

    with st.status("Processing Markdown...", expanded=True) as status:
        process_documents(
            input_path=md_path,
            output_dir=doc_dir,
            storage_format=storage_format,
            faiss_index_path=faiss_path,
            vector_mgr=tools["vector_mgr"],
            storage=tools["storage"],
            print_func=st.write
        )
        status.update(label="✅ Processing complete!", state="complete")

    return doc_name


if uploaded_pdf is not None:
    doc_name = Path(uploaded_pdf.name).stem
    doc_faiss = OUTPUT_BASE / doc_name / "faiss_index" / "index.faiss"
    if not doc_faiss.exists():
        result = process_uploaded_pdf(uploaded_pdf)
        if result:
            activate_doc(result)
    elif st.session_state.active_doc != doc_name:
        activate_doc(doc_name)

elif process_md_btn:
    doc_name = Path(input_file).stem
    doc_faiss = OUTPUT_BASE / doc_name / "faiss_index" / "index.faiss"
    if not doc_faiss.exists():
        result = process_md_file(input_file)
        activate_doc(result)
    else:
        activate_doc(doc_name)

elif selected_doc and st.session_state.active_doc != selected_doc:
    activate_doc(selected_doc)

elif not st.session_state.active_doc and available_docs:
    activate_doc(available_docs[0])


if st.session_state.active_doc:
    st.caption(f"📂 Active: **{st.session_state.active_doc}** &nbsp;|&nbsp; 🤖 Provider: **{llm_provider}**")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "table" in message:
            with st.expander("View Source Table"):
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
                    summarizer=tools["summarizer"],
                    vector_mgr=tools["vector_mgr"],
                    print_func=lambda x: None,
                )

                if res.get("results"):
                    st.markdown(res["answer"])
                    with st.expander("View Source Table"):
                        st.code(res["table_context"])
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": res["answer"],
                        "table": res["table_context"]
                    })
                else:
                    st.error("No relevant tables found.")
