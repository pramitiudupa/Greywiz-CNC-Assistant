# TableRAG - Developer Handoff Document

**Project:** Greywiz Code (TableRAG)
**Date:** 2026-06-08
**Purpose:** Extract tables from Markdown files (produced by MinerU/PDF-to-MD tools), generate LLM-powered descriptions, vectorize them, and provide a RAG chat interface via Streamlit.

---

## 1. Repository Structure

```
Greywiz Code/
├── .env                        # Google API key (GOOGLE_API_KEY)
├── requirements.txt            # Python dependencies
├── main.py                     # CLI entry point (extraction + RAG query loop)
├── app.py                      # Streamlit web UI entry point
├── table_processor.py          # Markdown/HTML table parsing logic
├── summarizer.py               # Gemini-based table summarization & QA
├── vector_store.py             # FAISS vector store (embed + search)
├── storage.py                  # Save/load extracted tables in various formats
├── Test1_2Page.pdf             # Sample source PDF
├── Test1_2Page_Output.md       # Sample MD file (MinerU output from the PDF above)
├── extracted_tables/           # Output: saved table files + metadata cache
│   ├── table_0.json ... table_3.json
│   └── table_metadata.json     # Cached summaries & content hashes
├── faiss_index/                # Output: persisted FAISS index
│   ├── index.faiss
│   └── index.pkl
├── __pycache__/                # Python bytecode cache (ignorable)
└── .vscode/                    # VS Code settings (ignorable)
```

---

## 2. Complete Workflow

The pipeline has 5 stages. Both `main.py` (CLI) and `app.py` (Streamlit) execute the same logic.

### Stage 1: Read .md file, extract tables (with section-aware context)

- **Module:** `table_processor.py`
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
- **Note:** The input `.md` file is expected to contain HTML `<table>` tags (this is the format produced by MinerU when converting PDFs to Markdown). It does NOT parse native Markdown pipe-tables.

### Stage 2: Generate descriptions for each table (LLM summarization)

- **Module:** `summarizer.py`
- **Class:** `TableSummarizer` (uses `gemini-2.5-flash` via `google-generativeai`)
- **Function:** `summarize_bundle(context, grid)`
- **What it does:**
  1. Converts the 2D grid to a text representation using pandas `DataFrame.to_string()`.
  2. Sends a prompt to Gemini that includes BOTH the surrounding document context AND the table data.
  3. The prompt **mandates** that the LLM:
     - State all machine specs (wharve diameter, roller diameter, retrofit kit) in the **first sentence** of the summary.
     - Perform unit expansion (e.g., "T/m" = Twists per meter, "T/"" = Twists per inch).
     - List independent/dependent variables with ranges.
     - Write in a search-optimized style matching technician queries.
- **Output:** A text summary string per table.
- **This is the "agent" step** -- the LLM reads the surrounding context and the table together to produce an enriched, search-friendly description. No separate agent call is needed; context selection is handled deterministically by the parser, and relevance filtering is handled by this summarization step.

### Stage 3: Vectorization and persistent storage

- **Module:** `vector_store.py`
- **Class:** `VectorStoreManager` (uses `gemini-embedding-2` via `langchain-google-genai`)
- **What it does:**
  1. Wraps each summary + its metadata into a LangChain `Document`.
  2. Creates a FAISS index from these documents using Google's embedding model.
  3. Saves the FAISS index to disk (`faiss_index/`) for persistence.
  4. On subsequent runs, loads the existing index instead of re-creating it.
- **Caching:** A JSON metadata cache (`extracted_tables/table_metadata.json`) stores content hashes. If a table hasn't changed between runs, the cached summary is reused instead of calling the LLM again. Note: `hash()` is used which is NOT stable across Python sessions (Python randomizes hash seeds). This means the cache will miss on every new process. A production fix would use `hashlib.sha256`.

### Stage 4: RAG query (retrieve + answer)

- **Module:** `vector_store.py` (search) + `summarizer.py` (answer generation)
- **What it does:**
  1. User provides a natural language question.
  2. The question is embedded using the same embedding model (`gemini-embedding-2`).
  3. FAISS similarity search retrieves the top-k most relevant table (default k=1).
  4. The matched table file is loaded from disk (via `storage.py`).
  5. Both the **raw table data** AND the **stored summary** (which contains machine specs, unit info, and context) are passed to Gemini (`answer_query()`) for grounded answer generation.
- **Output:** A text answer based on both the table data and its contextual description.

### Stage 5: UI (Streamlit)

- **Module:** `app.py`
- **What it does:**
  1. Sidebar with settings (input file, storage format, output dir, index path, re-process button).
  2. On first load: processes tables if no existing FAISS index is found, otherwise loads the index.
  3. Chat interface: user types a question, the app retrieves the relevant table, generates an answer, and displays both the answer and the source table in an expander.
  4. Chat history is maintained in `st.session_state`.

---

## 3. Module-by-Module Reference

### table_processor.py

| Function | Purpose |
|---|---|
| `clean_cell_text(value)` | Normalize whitespace in a cell string |
| `rectangularize(grid)` | Pad all rows to the same width |
| `parse_html_table(html_str)` | Parse one `<table>` HTML string into a 2D grid, handling rowspan/colspan |
| `extract_tables_from_md(md_path)` | Return raw HTML strings of all `<table>` elements (not used by main pipeline) |
| `parse_bundles_from_md(md_path)` | **Primary function.** Returns list of `{context, table, raw_html}` bundles |

### summarizer.py

| Function | Purpose |
|---|---|
| `TableSummarizer.__init__(model_name)` | Configure Gemini API. Default model: `gemini-2.5-flash` |
| `summarize_bundle(context, grid)` | Generate an enriched, search-optimized summary of a table + its surrounding context |
| `answer_query(query, context_table)` | Answer a user question using a table as context |

### vector_store.py

| Function | Purpose |
|---|---|
| `VectorStoreManager.__init__(model_name)` | Configure embeddings. Default model: `gemini-embedding-2` |
| `create_index(summaries, metadatas)` | Build FAISS index from summary texts + metadata dicts |
| `search(query, k)` | Similarity search, returns top-k LangChain Documents |
| `save_local(folder_path)` | Persist FAISS index to disk |
| `load_local(folder_path)` | Load FAISS index from disk |

### storage.py

| Class | Format | Purpose |
|---|---|---|
| `MarkdownStorage` | `.md` | Save/load tables as Markdown pipe-tables |
| `JSONStorage` | `.json` | Save/load tables as JSON arrays |
| `HTMLStorage` | `.html` | Save/load tables as HTML |
| `XMLStorage` | `.xml` | Save/load tables as XML |
| `get_storage(format_type)` | -- | Factory function returning the appropriate storage class |

### postgres_builder.py (UNUSED)

A standalone module for ingesting parsed tables into PostgreSQL with auto-inferred schemas. It imports `parse_tables_from_md` which **does not exist** in `table_processor.py` (the actual function is `extract_tables_from_md`), so this module would crash on import. It is not imported by `main.py` or `app.py`.

---

## 4. Unnecessary / Dead Files

| File/Directory | Verdict | Reason |
|---|---|---|
| `postgres_builder.py` | **REMOVE** | Not used by the pipeline. Has a broken import (`parse_tables_from_md` doesn't exist). 706 lines of dead code. Would need a PostgreSQL server anyway. |
| `Test1_2Page.pdf` | **Optional** | The original source PDF. Not read by any code -- only the `.md` output matters. Keep for reference if desired. |
| `__pycache__/` | **REMOVE** | Auto-generated bytecode. Add to `.gitignore`. |
| `.vscode/` | **Optional** | Editor config. Not project-critical. |
| `extracted_tables/` | **Generated output** | Recreated on each run. Can be gitignored. |
| `faiss_index/` | **Generated output** | Recreated on each run. Can be gitignored. |

**Core files to keep:** `main.py`, `app.py`, `table_processor.py`, `summarizer.py`, `vector_store.py`, `storage.py`, `.env`, `requirements.txt`, `Test1_2Page_Output.md` (sample data).

---

## 5. How to Run

### Prerequisites

- Python 3.10+ (tested with 3.12 based on pycache files)
- A valid Google AI API key (Gemini access)

### Setup

```bash
# 1. Clone / copy the repo
cd "Greywiz Code"

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

```bash
# Process the sample file and enter interactive Q&A mode
python main.py --input Test1_2Page_Output.md --format json

# Or run a single query
python main.py --input Test1_2Page_Output.md --query "What is the twist value for gear B=80 and D=91?"

# Options:
#   --input    Path to the .md file (default: Test1_2Page_Output.md)
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

## 6. Dependencies (requirements.txt)

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
| `psycopg` | **UNUSED** -- only needed by `postgres_builder.py`. Remove if that file is removed. |

---

## 7. Known Issues & Caveats

1. **Hash instability:** The caching mechanism in `main.py` and `app.py` uses Python's built-in `hash()`, which is randomized per process (PYTHONHASHSEED). The cache will almost never hit on a fresh run. Replace with `hashlib.sha256(content_to_hash.encode()).hexdigest()` for stable caching.

2. **FAISS index staleness:** If the index already exists on disk, the system loads it and skips re-processing even if the source `.md` file changed. The user must manually delete the `faiss_index/` directory to force a rebuild.

3. **Single-file input:** The pipeline processes one `.md` file at a time. There is no batch/directory processing.

4. **Top-1 retrieval only:** Both CLI and Streamlit retrieve only the single best-matching table (`k=1`). For multi-table queries, this would need to be increased.

5. **`storage_format` bug in `app.py`:** The `get_tools()` function is decorated with `@st.cache_resource`, but it captures `storage_format` from the outer scope at the time of first call. Changing the format in the sidebar won't update the cached `storage` object unless the cache is manually invalidated.

6. **No error handling for API failures:** Neither `summarizer.py` nor `vector_store.py` has try/except around API calls. A network failure or quota exhaustion will crash the app.

7. **Broken import in postgres_builder.py:** Line 13 imports `parse_tables_from_md` which does not exist in `table_processor.py` (the actual function name is `extract_tables_from_md`).

---

## 8. Mapping to Ideal Workflow

Below is how the current codebase maps to each stage of the intended workflow:

| Ideal Workflow Step | Status | Implementation |
|---|---|---|
| Read .md file, extract tables | **Done** | `table_processor.py :: parse_bundles_from_md()` -- parses HTML tables from MD, handles rowspan/colspan |
| Agent identifies relevant context + generates descriptions | **Done** | `summarizer.py :: summarize_bundle()` -- sends table + surrounding text context to Gemini, generates search-optimized summary with unit expansion |
| Vectorization, persistent storage + cache | **Done** | `vector_store.py` -- uses `gemini-embedding-2` embeddings + FAISS, saves to disk. Cache via JSON metadata file (but hash is unstable, see Known Issues #1) |
| Streamlit UI for user prompt input | **Done** | `app.py` -- full chat interface with sidebar config, source table display |
| Prompt vectorized, compared with embeddings, retrieve relevant table | **Done** | `vector_store.py :: search()` -- embeds the query and runs FAISS similarity search |
| Pass retrieved table to LLM as context for answer | **Done** | `summarizer.py :: answer_query()` -- retrieved table content is sent to Gemini with the user's question |

**All core functionalities are addressed.** The pipeline is end-to-end functional for the described use case.

---

## 9. Architecture Diagram

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
                     (Gemini 2.5 Flash LLM)
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
           [4] search(query, k=1) --> top matching Document
                                 |
                    +------------v-----------+
                    | Load matched table     |
                    | from disk (storage.py) |
                    +------------+-----------+
                                 |
           [5] answer_query(question, table_content)
                     (Gemini 2.5 Flash LLM)
                                 |
                    +------------v-----------+
                    | Final answer to user   |
                    +------------------------+
```

---

## 10. Recommended Cleanup (for the testing dev)

Before starting testing, run these cleanup steps:

```bash
# 1. Delete dead module
del postgres_builder.py

# 2. Remove psycopg from requirements.txt (only needed by postgres_builder.py)
# Edit requirements.txt and remove the line: psycopg>=3.1.0

# 3. Clean generated artifacts
rmdir /s /q __pycache__
rmdir /s /q faiss_index
rmdir /s /q extracted_tables

# 4. Add a .gitignore
echo __pycache__/ > .gitignore
echo faiss_index/ >> .gitignore
echo extracted_tables/ >> .gitignore
echo .env >> .gitignore
echo *.pyc >> .gitignore
```

---

## 11. Quick Smoke Test

After setup, run this to verify the full pipeline works:

```bash
# This should: extract 4 tables, summarize each via Gemini, build FAISS index, then answer the query.
python main.py --input Test1_2Page_Output.md --format json --query "What twist per meter do I get with gear D=91 and B=80?"
```

**Expected behavior:**
1. Console prints: extracting bundles, found 4 bundles, summarizing each.
2. Creates `extracted_tables/` with `table_0.json` through `table_3.json` + `table_metadata.json`.
3. Creates `faiss_index/` with `index.faiss` + `index.pkl`.
4. Prints a relevant answer citing a specific Twists T/m value from the table data.

If the API key is invalid, it will fail at step 2 with an authentication error from Google.
