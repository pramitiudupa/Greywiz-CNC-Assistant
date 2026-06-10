import streamlit as st
import os
from pathlib import Path
from src.parsers.storage import get_storage
from src.llm.providers.gemini.summarizer import TableSummarizer
from src.parsers.vector_store import VectorStoreManager
from routes.rag_routes import process_documents, query_rag
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="TableRAG Chat", layout="wide")

st.title("📊 TableRAG: Extract, Summarize & Chat")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("Settings")
    input_file = st.text_input("Input MD File", value="assets/markdown/test1_2page_output.md")
    storage_format = st.selectbox("Storage Format", options=["md", "json", "html", "xml"], index=1)
    output_dir = st.text_input("Output Directory", value="extracted_tables")
    faiss_index_path = st.text_input("FAISS Index Path", value="faiss_index")
    
    if st.button("Re-process Tables"):
        st.session_state.processed = False
        if os.path.exists(faiss_index_path):
            import shutil
            shutil.rmtree(faiss_index_path)
        st.rerun()

# --- Initialize State ---
if 'processed' not in st.session_state:
    st.session_state.processed = False
if 'messages' not in st.session_state:
    st.session_state.messages = []

# --- Processing Logic ---
@st.cache_resource
def get_tools():
    return {
        "summarizer": TableSummarizer(),
        "vector_mgr": VectorStoreManager(),
        "storage": get_storage(storage_format)
    }

tools = get_tools()

def process_data():
    input_path = Path(input_file)
    out_dir = Path(output_dir)
    index_path = Path(faiss_index_path)
    
    with st.status("Processing tables...", expanded=True) as status:
        process_documents(
            input_path=input_path,
            output_dir=out_dir,
            storage_format=storage_format,
            faiss_index_path=index_path,
            summarizer=tools["summarizer"],
            vector_mgr=tools["vector_mgr"],
            storage=tools["storage"],
            print_func=st.write
        )
        status.update(label="Processing complete!", state="complete")
    
    st.session_state.processed = True

if not st.session_state.processed:
    if os.path.exists(faiss_index_path):
        tools["vector_mgr"].load_local(faiss_index_path)
        st.session_state.processed = True
    else:
        process_data()

# --- Chat Interface ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "table" in message:
            with st.expander("View Source Table"):
                st.code(message["table"])

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
                storage=tools["storage"],
                print_func=lambda x: None  # Mute print logs in UI chat
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
