# TableRAG - Developer Handoff Document

**Project:** engg_docs_processor_agents (TableRAG)
**Date:** 2026-06-10
**Purpose:** Extract tables from Markdown files (produced by MinerU/PDF-to-MD tools), generate LLM-powered descriptions, vectorize them, and provide a RAG chat interface via Streamlit.

---

## 1. Repository Structure

The repository follows a modular, package-based Python structure. Python 3.3+ implicit namespace packages are utilized, so no `__init__.py` files are present.

```
backend/
├── .env                        # Google API key (GOOGLE_API_KEY), Prompts, and Configs
├── requirements.txt            # Python dependencies
├── main.py                     # CLI entry point (parses args -> calls routes)
├── app.py                      # Streamlit web UI entry point (parses UI -> calls routes)
├── restructure_justification.md# Documentation of repository reorganization
├── assets/
│   ├── markdown/
│   │   ├── test1_2page_output.md # Sample MD file (MinerU output)
│   ├── pdfs/
│   │   └── test1_2page.pdf       # Sample source PDF
│   ├── json/                   # For static JSON assets
│   └── html/                   # For static HTML assets
├── routes/
│   └── rag_routes.py           # Core abstracted logic for processing and RAG querying
├── src/
│   ├── parsers/
│   │   ├── table_processor.py  # Markdown/HTML table parsing logic
│   │   ├── vector_store.py     # FAISS vector store (embed + search)
│   │   └── storage.py          # Save/load extracted tables in various formats
│   └── llm/
│       └── providers/
│           ├── gemini/
│           │   └── summarizer.py # Gemini-based table summarization & QA
│           └── qwen/           # Placeholder for future Qwen integration
├── extracted_tables/           # Output: saved table files + metadata cache (Generated at runtime)
│   ├── table_0.json ... table_3.json
│   └── table_metadata.json     # Cached summaries & content hashes
└── faiss_index/                # Output: persisted FAISS index (Generated at runtime)
    ├── index.faiss
    └── index.pkl
```

---

## 2. Complete Workflow

The pipeline has 5 stages. Both `main.py` (CLI) and `app.py` (Streamlit) act solely as entry points that parse inputs and pipe them to the `backend/routes/rag_routes.py` logic. Note that all scripts should be executed from the `backend/` directory so that `src.*` modules resolve correctly.

### Stage 1: Read .md file, extract tables (with section-aware context)

- **Module:** `src.parsers.table_processor` (called via `rag_routes.py`)
- **Function:** `parse_bundles_from_md(md_path)`
- **What it does:**
  1. Reads the entire `.md` file content.
  2. Splits it by `<table>...</table>` HTML tags using regex.
  3. **Section-aware context propagation:** For each table, assembles context from:
     - **Sticky headings:** Markdown headings (`##`, `###`, etc.) persist across tables until replaced by a heading at the same or higher level.
     - **Carry-forward for consecutive tables:** If two tables appear back-to-back with no text between them, the second table inherits the context (machine specs, etc.) from the preceding text block.
     - Body text is deduplicated against headings to avoid repetition.
  4. Parses each HTML table into a rectangular 2D grid (`list[list[str]]`), correctly handling `rowspan` and `colspan` attributes via BeautifulSoup.
- **Output:** A list of "bundles", each being `{"context": str, "table": list[list[str]], "raw_html": str}`.

### Stage 2: Generate descriptions for each table (LLM summarization)

- **Module:** `src.llm.providers.gemini.summarizer` (called via `rag_routes.py`)
- **Class:** `TableSummarizer` (uses `gemini-2.5-flash` via `google-generativeai`)
- **Function:** `summarize_bundle(context, grid)`
- **What it does:**
  1. Converts the 2D grid to a text representation.
  2. Fetches the system prompt from `.env` (`SUMMARIZER_SYSTEM_PROMPT`).
  3. Sends the prompt to Gemini that includes BOTH the surrounding document context AND the table data.
- **Output:** A text summary string per table.

### Stage 3: Vectorization and persistent storage

- **Module:** `src.parsers.vector_store` (called via `rag_routes.py`)
- **Class:** `VectorStoreManager` (uses `gemini-embedding-2` via `langchain-google-genai`)
- **What it does:**
  1. Wraps each summary + its metadata into a LangChain `Document`.
  2. Creates a FAISS index from these documents using Google's embedding model.
  3. Saves the FAISS index to disk (`faiss_index/`) for persistence.
- **Caching:** A JSON metadata cache (`extracted_tables/table_metadata.json`) stores content hashes. 

### Stage 4: RAG query (retrieve + answer)

- **Module:** `routes.rag_routes`
- **Function:** `query_rag()`
- **What it does:**
  1. User provides a natural language question.
  2. `rag_routes` retrieves `RETRIEVAL_K` from `.env` (default 1) and queries the vector store.
  3. FAISS similarity search retrieves the top-k most relevant table.
  4. Both the **raw table data** AND the **stored summary** are passed to Gemini (`answer_query()` using `.env` `QA_SYSTEM_PROMPT`) for grounded answer generation.
- **Output:** A dictionary containing the answer text and source tables.

### Stage 5: UI (Streamlit)

- **Module:** `app.py`
- **What it does:**
  1. Sidebar with settings (input file, storage format, output dir, index path, re-process button).
  2. On first load: processes tables if no existing FAISS index is found, otherwise loads the index.
  3. Chat interface: user types a question, the app retrieves the relevant table via `rag_routes.py`, generates an answer, and displays both the answer and the source table in an expander.

---

## 3. Module-by-Module Reference

### routes/rag_routes.py (Core Abstraction Layer)

| Function | Purpose |
|---|---|
| `process_documents(...)` | Complete pipeline for extracting, caching, summarizing, and vector indexing documents. |
| `query_rag(...)` | Retrieves top-k matching tables and queries the LLM for the final answer. |

### src/parsers/table_processor.py

| Function | Purpose |
|---|---|
| `clean_cell_text(value)` | Normalize whitespace in a cell string |
| `rectangularize(grid)` | Pad all rows to the same width |
| `parse_html_table(html_str)` | Parse one `<table>` HTML string into a 2D grid, handling rowspan/colspan |
| `extract_tables_from_md(md_path)` | Return raw HTML strings of all `<table>` elements (not used by main pipeline) |
| `parse_bundles_from_md(md_path)` | **Primary function.** Returns list of `{context, table, raw_html}` bundles |

### src/llm/providers/gemini/summarizer.py

| Function | Purpose |
|---|---|
| `TableSummarizer.__init__(model_name)` | Configure Gemini API. Default model: `gemini-2.5-flash` |
| `summarize_bundle(context, grid)` | Generate an enriched, search-optimized summary of a table + its surrounding context |
| `answer_query(query, context_table)` | Answer a user question using a table as context |

### src/parsers/vector_store.py

| Function | Purpose |
|---|---|
| `VectorStoreManager.__init__(model_name)` | Configure embeddings. Default model: `gemini-embedding-2` |
| `create_index(summaries, metadatas)` | Build FAISS index from summary texts + metadata dicts |
| `search(query, k)` | Similarity search, returns top-k LangChain Documents |
| `save_local(folder_path)` | Persist FAISS index to disk |
| `load_local(folder_path)` | Load FAISS index from disk |

### src/parsers/storage.py

| Class | Format | Purpose |
|---|---|---|
| `MarkdownStorage` | `.md` | Save/load tables as Markdown pipe-tables |
| `JSONStorage` | `.json` | Save/load tables as JSON arrays |
| `HTMLStorage` | `.html` | Save/load tables as HTML |
| `XMLStorage` | `.xml` | Save/load tables as XML |
| `get_storage(format_type)` | -- | Factory function returning the appropriate storage class |

---

## 4. How to Run

### Prerequisites

- Python 3.10+ (tested with 3.12)
- A valid Google AI API key (Gemini access)

### Setup

```bash
# 1. Clone / copy the repo and navigate to backend
cd backend

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your API key in .env
# Edit .env and set:  GOOGLE_API_KEY=your_actual_key_here
```

### Run via CLI

**IMPORTANT:** Always run the commands from the `backend/` directory to ensure package imports (`from src.parsers...`) resolve correctly.

```bash
# Process the sample file and enter interactive Q&A mode
python main.py --input assets/markdown/test1_2page_output.md --format json

# Or run a single query
python main.py --input assets/markdown/test1_2page_output.md --query "What is the twist value for gear B=80 and D=91?"

# Options:
#   --input    Path to the .md file (default: assets/markdown/test1_2page_output.md)
#   --format   Storage format: md, json, html, xml (default: md)
#   --output_dir  Where to save extracted tables (default: extracted_tables)
#   --query    Single query to run (if omitted, enters interactive loop)
```

### Run via Streamlit (Web UI)

```bash
streamlit run app.py
```

This opens a browser at `http://localhost:8501` with:
- Sidebar: configure input file, format, paths
- Chat interface: ask questions about the tables
- "Re-process Tables" button: clears cached index and re-processes from scratch

### Forcing re-processing

If you change the input `.md` file, delete these to force a full re-run:
```bash
rmdir /s /q faiss_index
del extracted_tables\table_metadata.json
```

---

## 5. Dependencies (requirements.txt)

| Package | Used For |
|---|---|
| `google-generativeai` | Gemini LLM calls (summarizer) |
| `langchain` / `langchain-core` | Document abstraction |
| `langchain-google-genai` | Gemini embeddings integration |
| `langchain-community` | FAISS vector store wrapper |
| `faiss-cpu` | Vector similarity search |
| `beautifulsoup4` | HTML table parsing |
| `python-dotenv` | Load `.env` file |
| `pandas` | DataFrame operations for table formatting |
| `numpy` | Required by FAISS/pandas |
| `lxml` | XML parser backend for pandas |
| `tabulate` | Markdown table rendering (`df.to_markdown()`) |
| `streamlit` | Web UI |

*(Note: `psycopg` may be present in `requirements.txt` from a legacy unused file. It can be safely removed or ignored.)*

---

## 6. Known Issues & Caveats

1. **Hash instability:** The caching mechanism in `rag_routes.py` uses Python's built-in `hash()`, which is randomized per process (PYTHONHASHSEED). The cache will almost never hit on a fresh run. Replace with `hashlib.sha256(content_to_hash.encode()).hexdigest()` for stable caching.

2. **FAISS index staleness:** If the index already exists on disk, the system loads it and skips re-processing even if the source `.md` file changed. The user must manually delete the `faiss_index/` directory to force a rebuild.

3. **Single-file input:** The pipeline processes one `.md` file at a time. There is no batch/directory processing.

4. **`storage_format` bug in `app.py`:** The `get_tools()` function is decorated with `@st.cache_resource`, but it captures `storage_format` from the outer scope at the time of first call. Changing the format in the sidebar won't update the cached `storage` object unless the cache is manually invalidated.

---

## 7. Architecture Diagram

```
                        +-----------------+
                        | .md file (input)|
                        | (HTML tables    |
                        |  inside MD)     |
                        +--------+--------+
                                 |
                    [1] parse_bundles_from_md()
                                 |
                    +------------v-----------+
                    | List of Bundles:       |
                    |  - context (text)      |
                    |  - table (2D grid)     |
                    +------------+-----------+
                                 |
               [2] summarize_bundle(context, grid)
                 (Uses SUMMARIZER_SYSTEM_PROMPT from .env)
                                 |
                    +------------v-----------+
                    | List of Summaries      |
                    | (search-optimized text)|
                    +------------+-----------+
                                 |
           [3] create_index(summaries, metadatas)
                 (gemini-embedding-2 + FAISS)
                                 |
                    +------------v-----------+
                    | FAISS Index on disk    |
                    | + table_metadata.json  |
                    +------------------------+
                                 |
                                 |  User asks a question
                                 |  (via CLI or Streamlit)
                                 |
           [4] search(query, k=RETRIEVAL_K) --> top matching Document
                                 |
                    +------------v-----------+
                    | Load matched table     |
                    | from disk (storage.py) |
                    +------------+-----------+
                                 |
           [5] answer_query(question, table_content)
                  (Uses QA_SYSTEM_PROMPT from .env)
                                 |
                    +------------v-----------+
                    | Final answer to user   |
                    +------------------------+
```

---

## 8. Quick Smoke Test

After setup, run this to verify the full pipeline works:

```bash
# This should: extract 4 tables, summarize each via Gemini, build FAISS index, then answer the query.
python main.py --input assets/markdown/test1_2page_output.md --format json --query "What twist per meter do I get with gear D=91 and B=80?"
```

**Expected behavior:**
1. Console prints: extracting bundles, found 4 bundles, summarizing each.
2. Creates `extracted_tables/` with `table_0.json` through `table_3.json` + `table_metadata.json`.
3. Creates `faiss_index/` with `index.faiss` + `index.pkl`.
4. Prints a relevant answer citing a specific Twists T/m value from the table data.

If the API key is invalid, it will fail at step 2 with an authentication error from Google.
