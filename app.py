import streamlit as st
import os
import sys

# --- PyTorch Error Mitigation ---
# This must happen before other imports that might trigger torch initialization
try:
    import torch
    # Ensure torch.classes is initialized properly to avoid '__path__._path' error
    if hasattr(torch, 'classes'):
        try:
            _ = torch.classes.__path__
        except Exception:
            pass
except ImportError:
    pass

from pathlib import Path
from table_processor import parse_bundles_from_md
from storage import get_storage
from summarizer import TableSummarizer
from vector_store import VectorStoreManager
import json
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="TableRAG Chat", layout="wide")

st.title("📊 TableRAG: Extract, Summarize & Chat")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("Settings")
    input_file = st.text_input("Input MD File", placeholder="e.g., data.md")
    storage_format = st.selectbox("Storage Format", options=["md", "json", "html", "xml"], index=1)
    output_dir = st.text_input("Output Directory", value="extracted_tables")
    faiss_index_path = st.text_input("FAISS Index Path", value="faiss_index")
    
    if st.button("Re-process Tables"):
        if not input_file:
            st.error("Please provide an input file path.")
        elif not os.path.exists(input_file):
            st.error(f"File not found: {input_file}")
        else:
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
    if not input_file:
        st.warning("Please enter an input Markdown file path in the sidebar.")
        return

    input_path = Path(input_file)
    if not input_path.exists():
        st.error(f"Input file not found at: {input_path}")
        return

    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True)
    
    cache_file = out_dir / "table_metadata.json"
    cached_data = {}
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_data = json.load(f)

    with st.status("Processing tables...", expanded=True) as status:
        st.write("Extracting bundles from Markdown...")
        bundles = parse_bundles_from_md(input_path)
        
        summaries = []
        metadatas = []
        new_cache = {}
        
        st.write(f"Found {len(bundles)} bundles. Generating intelligent summaries...")
        for i, bundle in enumerate(bundles):
            table_id = f"table_{i}"
            grid = bundle["table"]
            context = bundle["context"]
            
            content_to_hash = json.dumps(grid) + context
            content_hash = hash(content_to_hash)
            
            if table_id in cached_data and cached_data[table_id].get("content_hash") == content_hash:
                st.write(f"Using cache for Bundle {i}")
                summary = cached_data[table_id]["summary"]
                file_path = Path(cached_data[table_id]["file_path"])
            else:
                st.write(f"Summarizing Bundle {i} (with context)...")
                file_name = f"{table_id}"
                file_path = out_dir / file_name
                tools["storage"].save(grid, file_path)
                summary = tools["summarizer"].summarize_bundle(context, grid)
            
            summaries.append(summary)
            metadata = {
                "table_id": table_id,
                "file_path": str(file_path.with_suffix(f'.{storage_format}')),
                "original_index": i,
                "summary": summary,
                "content_hash": content_hash
            }
            metadatas.append(metadata)
            new_cache[table_id] = metadata

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(new_cache, f, indent=4)

        st.write("Building vector index...")
        tools["vector_mgr"].create_index(summaries, metadatas)
        tools["vector_mgr"].save_local(faiss_index_path)
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
        elif "tables" in message:
            with st.expander("View Source Tables"):
                for ctx in message["tables"]:
                    st.markdown(f"**{ctx['name']}**")
                    st.code(ctx['table_data'])

if query := st.chat_input("Ask a question about the tables..."):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        with status_placeholder.status("Searching and generating answer...", expanded=True) as status:
            st.write("🔍 Searching vector index for relevant tables...")
            results = tools["vector_mgr"].search(query, k=1)
            
            if results:
                top_result = results[0]
                table_path = Path(top_result.metadata["file_path"])
                summary = top_result.metadata.get("summary", "")
                
                st.write(f"📖 Loading table data from `{table_path.name}`...")
                table_context = tools["storage"].load(table_path)
                
                st.write("🤖 Generating answer using Gemini...")
                answer = tools["summarizer"].answer_query(query, table_context, summary=summary)
                
                status.update(label="Answer generated!", state="complete", expanded=False)
                st.markdown(answer)
                
                with st.expander("View Source Table"):
                    st.code(table_context)
                
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": answer,
                    "table": table_context
                })
            else:
                status.update(label="No results found.", state="error")
                st.error("No relevant tables found.")
