# TableRAG — Developer Handoff Document

**Project:** engg_docs_processor_agents (TableRAG)
**Date:** 2026-06-17
**Purpose:** Extract tables from Markdown files (produced by MinerU/PDF-to-MD tools), vectorize them directly as JSON chunks, and provide a RAG chat interface via Streamlit.

> **Runtime:** Supports two providers — **Ollama** (fully local, no API keys) and **Gemini** (cloud, requires `GOOGLE_API_KEY`). Provider is selectable at startup in both the CLI and the Streamlit UI.

---

## 1. Repository Structure

```
backend/
├── .env                        # Provider config, prompts, and settings
├── .env.example                # Documented template for .env
├── requirements.txt            # Python dependencies
├── main.py                     # CLI entry point
├── app.py                      # Streamlit web UI entry point
├── assets/
│   ├── markdown/               # MinerU output (.md files + per-PDF subdirectories)
│   ├── pdfs/                   # Uploaded PDF files (created at runtime)
│   ├── json/                   # Static JSON assets
│   └── html/                   # Static HTML assets
├── routes/
│   └── rag_routes.py           # Core pipeline logic (process + query)
├── src/
│   ├── parsers/
│   │   ├── table_processor.py  # Markdown/HTML table parsing (section-aware context)
│   │   ├── vector_store.py     # FAISS vector store (multi-provider embeddings)
│   │   ├── storage.py          # Save extracted tables in various formats
│   │   └── mineru_converter.py # PDF -> Markdown via MinerU CLI
│   └── llm/
│       ├── provider_factory.py # Factory: returns the correct TableSummarizer
│       └── providers/
│           ├── gemini/
│           │   └── summarizer.py # Gemini-based QA (cloud)
│           └── ollama/
│               └── summarizer.py # Ollama-based QA (local)
└── extracted_tables/           # Per-document storage (runtime)
    ├── <document_A>/
    │   ├── table_0.json ... table_N.json
    │   ├── table_metadata.json
    │   └── faiss_index/
    │       ├── index.faiss
    │       └── index.pkl
    └── <document_B>/
        ├── ...
```

---

## 2. Per-Document Storage

Each processed document gets its own isolated directory under `extracted_tables/<doc_stem>/`. This means:

- Uploading a new PDF does **not** overwrite data from a previously uploaded PDF.
- The user can switch between documents via the sidebar dropdown in Streamlit.
- Each document has its own FAISS index, table files, and metadata cache.
- The document name is derived from the input file stem (e.g., `Airbus 3 Pages.pdf` → `extracted_tables/Airbus 3 Pages/`).
- Reprocessing the same document (via the "Re-process" button or re-upload) deletes and rebuilds only that document's directory.

---

## 3. Complete Workflow

### Stage 1: Parse tables from Markdown

- **Module:** `src.parsers.table_processor`
- **Function:** `parse_bundles_from_md(md_path)`
- Reads `.md`, splits by `<table>` tags, tracks sticky headings for section-aware context propagation.
- Parses each HTML table into a rectangular 2D grid (handles rowspan/colspan).
- **Output:** `[{"context": str, "table": list[list[str]], "raw_html": str}, ...]`

### Stage 2: Vectorize tables as JSON chunks

- **Module:** `routes.rag_routes` → `process_documents()`
- Builds a self-contained chunk per table: `CONTEXT:\n{context}\n\nTABLE (JSON):\n{table_json}`.
- The chunk is both the embedding text and the retrieval payload.
- Tables are also saved to disk via `storage.py` for archival.
- Creates a FAISS index from the chunks.
- **Caching:** `table_metadata.json` stores SHA-256 content hashes for change detection.

### Stage 3: RAG query

- **Module:** `routes.rag_routes` → `query_rag()`
- FAISS similarity search retrieves top-k chunks.
- Chunk content is read directly from `Document.page_content`.
- All retrieved chunks are passed to the LLM via `answer_query()`.
- **Output:** `{"answer": str, "table_context": str, "results": list}`

### Stage 4: UI (Streamlit)

- **Module:** `app.py`
- Sidebar: LLM provider selector, PDF upload, Markdown processing, storage format, document selector, re-process button.
- Chat: question input, LLM answer, source table expander.
- Switching documents clears chat history and loads the selected document's FAISS index.

---

## 4. Module Reference

### routes/rag_routes.py

| Function | Purpose |
|---|---|
| `process_documents(...)` | Extract bundles, vectorize table JSON, build FAISS index. |
| `query_rag(...)` | Retrieve top-k chunks, query LLM for answer. |
| `process_pdf_to_rag(...)` | Full pipeline: PDF → MinerU → MD → `process_documents()`. |

### src/parsers/table_processor.py

| Function | Purpose |
|---|---|
| `clean_cell_text(value)` | Normalize whitespace in a cell string. |
| `rectangularize(grid)` | Pad all rows to the same width. |
| `parse_html_table(html_str)` | Parse one `<table>` into a 2D grid (handles rowspan/colspan). |
| `parse_bundles_from_md(md_path)` | **Primary function.** Returns `[{context, table, raw_html}, ...]`. |

### src/parsers/vector_store.py

| Method | Purpose |
|---|---|
| `VectorStoreManager(provider, model_name)` | Configure embeddings — Ollama or Gemini. |
| `create_index(chunks, metadatas)` | Build FAISS index from chunk texts + metadata. |
| `search(query, k)` | Similarity search, returns top-k Documents. |
| `save_local(folder_path)` | Persist FAISS index to disk. |
| `load_local(folder_path)` | Load FAISS index from disk. |

### src/parsers/storage.py

| Class | Format |
|---|---|
| `MarkdownStorage` | `.md` |
| `JSONStorage` | `.json` |
| `HTMLStorage` | `.html` |
| `XMLStorage` | `.xml` |
| `get_storage(format_type)` | Factory returning the appropriate storage class. |

### src/parsers/mineru_converter.py

| Method | Purpose |
|---|---|
| `MinerUConverter(mineru_path)` | Auto-detect MinerU binary (env var → .venv → PATH). |
| `convert(pdf_path, output_dir)` | Convert PDF to Markdown. Overwrites previous output for same PDF. |

### src/llm/provider_factory.py

| Function | Purpose |
|---|---|
| `get_summarizer(provider, **kwargs)` | Factory: returns the correct `TableSummarizer`. |

### src/llm/providers/ollama/summarizer.py & gemini/summarizer.py

| Method | Purpose |
|---|---|
| `TableSummarizer(model_name)` | Configure the LLM. |
| `answer_query(query, context_table)` | Answer a question using table chunks as context. |

---

## 5. Provider System

| | Ollama (local) | Gemini (cloud) |
|---|---|---|
| **LLM** | `gemma4:26b-a4b-it-qat` via ChatOllama | `gemini-2.5-flash` via google-generativeai |
| **Embeddings** | `qwen3-embedding` via OllamaEmbeddings | `gemini-embedding-001` via GoogleGenerativeAIEmbeddings |
| **Auth** | None | `GOOGLE_API_KEY` required |

> Switching providers requires re-indexing — FAISS indexes are incompatible between providers.

---

## 6. How to Run

### Prerequisites

- Python 3.10+
- Ollama running (`ollama serve`) — if using the Ollama provider
- `GOOGLE_API_KEY` in `.env` — if using the Gemini provider

### Setup

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# If using Ollama:
ollama pull gemma4:26b-a4b-it-qat    # LLM
ollama pull qwen3-embedding           # Embeddings
```

### CLI

```bash
python main.py --input assets/markdown/test1_2page_output.md --format json
python main.py --input assets/markdown/test1_2page_output.md --query "What twist value for D=91?"
python main.py --pdf assets/pdfs/document.pdf --provider gemini
```

### Streamlit

```bash
streamlit run app.py
```

### Force re-indexing

```bash
rm -rf extracted_tables/<doc_name>/faiss_index
```

---

## 7. Known Caveats

1. **Provider switching requires re-indexing:** Delete the document's `faiss_index/` directory when switching providers.
2. **Single-file input:** The pipeline processes one `.md` file at a time.
3. **Ollama must be running:** `ollama serve` must be active when using the Ollama provider.
4. **Model cold-start:** First query after inactivity may be slow as Ollama loads the model.
