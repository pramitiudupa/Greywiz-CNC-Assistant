# Changes Summary

All changes made during this conversation, in chronological order.

---

## Round 1 — Direct JSON Vectorization

**Goal:** Replace LLM-based table summarization with direct JSON vectorization.

### rag_routes.py
- `process_documents()`: Removed the LLM summarization step. Tables are now vectorized as raw JSON chunks (`CONTEXT:\n{context}\n\nTABLE (JSON):\n{table_json}`). The chunk text serves as both the embedding input and the retrieval payload.
- `query_rag()`: Removed file I/O during retrieval. Table content is now read directly from `Document.page_content` instead of loading from disk via `storage.load()`. Removed the `storage` parameter entirely.

### ollama/summarizer.py
- `answer_query()`: Removed the `summary` parameter. The function now takes only `query` and `context_table`.

### gemini/summarizer.py
- `answer_query()`: Same interface change — removed `summary` parameter.

### app.py & main.py
- Updated all call sites to remove the `summarizer` and `storage` parameters from `process_documents()` and `query_rag()`.

### .env
- Updated `QA_SYSTEM_PROMPT` to remove the `{summary_section}` placeholder.

---

## Round 2 — Overwrite Directories + Gemini Provider

**Goal:** (a) Prevent duplicate output directories on reprocess. (b) Restore Gemini as a selectable LLM provider.

### (a) mineru_converter.py
- Output directories now use just the PDF stem (e.g., `Airbus 3 Pages/`) instead of `Airbus 3 Pages_20260610_150102/`.
- If the directory already exists, it's deleted and recreated via `shutil.rmtree()`.
- Removed the unused `datetime` import.

### (b) Multi-Provider Support

#### vector_store.py
- `VectorStoreManager` now accepts a `provider` parameter (`"ollama"` or `"gemini"`).
- Gemini path uses `GoogleGenerativeAIEmbeddings` from `langchain-google-genai`.
- Falls back to `LLM_PROVIDER` env var → `"ollama"`.

#### provider_factory.py
- `get_summarizer()` now accepts an explicit `provider` argument instead of only reading from env.

#### app.py
- Added a "🤖 LLM Provider" selectbox at the top of the sidebar.
- Provider choice flows to both `get_summarizer()` and `VectorStoreManager`.

#### main.py
- Added `--provider ollama/gemini` CLI flag.

#### .env.example
- Added `GEMINI_EMBEDDING_MODEL` config option.

---

## Round 3 — Codebase Review & Cleanup

**Goal:** Fix bugs, remove unnecessary comments, flag structural issues, update HANDOFF.md.

### Bugs Fixed
- `main.py`: `provider_label` fallback hardcoded `"ollama"` instead of reading `os.getenv("LLM_PROVIDER", "ollama")`. Fixed + added missing `import os`.
- `app.py`: Removed unused `tempfile` import. Fixed stale title "Extract, Summarize & Chat" → "Extract & Chat".
- `rag_routes.py`: Removed unused imports `get_storage` and `get_summarizer`.
- `mineru_converter.py`: Removed unused `sys` import.
- `vector_store.py`: Renamed stale `summaries` parameter to `chunks` in `create_index()`.

### Comments Removed
- Removed ~30 unnecessary comments across all files: numbered steps, section dividers, and comments restating the next line of code.

### HANDOFF.md
- Complete rewrite reflecting the current architecture.

---

## Round 4 — Dead Code Removal + Per-Document Storage

**Goal:** (a) Remove all dead code. (b) Per-document storage so uploading new documents doesn't overwrite old ones. (c) This summary.

### (a) Dead Code Removed

| What | Where |
|---|---|
| `summarize_bundle()` method | Both `ollama/summarizer.py` and `gemini/summarizer.py` |
| `pandas` and `List` imports | Both summarizer files (only used by `summarize_bundle`) |
| `load()` method | `storage.py` ABC + all 4 subclasses |
| `extract_tables_from_md()` function | `table_processor.py` |
| `SUMMARIZER_SYSTEM_PROMPT` | `.env` and `.env.example` |

### (b) Per-Document Storage

**Before:** All documents shared a flat `extracted_tables/` and `faiss_index/` directory. Uploading a new document overwrote the previous one's data.

**After:** Each document gets its own isolated directory:
```
extracted_tables/
├── Airbus_3_Pages/
│   ├── table_0.json ... table_N.json
│   ├── table_metadata.json
│   └── faiss_index/
├── another_document/
│   ├── ...
```

#### Files Changed

**app.py** (full rewrite):
- Removed `output_dir` and `faiss_index_path` text inputs from sidebar (now derived per-document).
- Added a "📂 Documents" section in the sidebar with a dropdown listing all previously processed documents.
- Added a "Process Markdown" button (previously auto-processed on load).
- Each document's FAISS index is stored inside its own directory.
- Switching documents clears chat history and loads the new index.
- Uploading a PDF that's already been processed skips re-processing and loads the existing index.

**main.py** (rewrite):
- Per-document paths derived from input file stem: `extracted_tables/<doc_stem>/faiss_index/`.
- Prints the active document name and path at startup.

**HANDOFF.md** (rewrite):
- Updated directory structure diagram.
- Added per-document storage documentation.
- Simplified module reference tables (removed dead functions).

---

## Files Modified (Complete List)

| File | Rounds Modified |
|---|---|
| `routes/rag_routes.py` | 1, 3 |
| `src/llm/providers/ollama/summarizer.py` | 1, 3, 4 |
| `src/llm/providers/gemini/summarizer.py` | 1, 4 |
| `src/parsers/vector_store.py` | 2, 3 |
| `src/parsers/mineru_converter.py` | 2, 3 |
| `src/parsers/storage.py` | 3, 4 |
| `src/parsers/table_processor.py` | 4 |
| `src/llm/provider_factory.py` | 2 |
| `app.py` | 1, 2, 3, 4 |
| `main.py` | 1, 2, 3, 4 |
| `.env` | 1, 3, 4 |
| `.env.example` | 2, 3, 4 |
| `HANDOFF.md` | 3, 4 |
