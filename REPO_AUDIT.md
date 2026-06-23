# Repository Audit: Document Lifecycle, Risks, Cleanup, and Simplification Opportunities

This report documents the current end-to-end lifecycle of a processed document in this repository and highlights design issues, security concerns, redundant code, and areas that can be simplified.

Scope: the `backend/` Python application, including CLI (`main.py`), Streamlit UI (`app.py`), pipeline logic (`routes/rag_routes.py`), parsing/storage (`src/parsers/*`), and LLM provider plumbing (`src/llm/*`).

Note: this document is based on source inspection only. No code was executed or modified as part of the audit.

---

## 1. Executive Summary

The project follows a simple but effective RAG pipeline:

1. A PDF is converted to Markdown with MinerU, or an existing Markdown file is used directly.
2. Markdown is parsed into table bundles with surrounding context.
3. Each table bundle is serialized into a single chunk containing both context and JSON table data.
4. Those chunks are embedded and stored in a per-document FAISS index.
5. Queries load the saved FAISS index later and answer questions without reprocessing, as long as the index remains valid and the embedding provider matches.

The main strengths are:

- Per-document persistence under `extracted_tables/<document>/`.
- Reusable indexes that support later Q&A without re-running MinerU.
- Provider abstraction for Ollama and Gemini.
- A direct retrieval path that avoids re-reading stored table files at query time.

The main concerns are:

- `FAISS.load_local(..., allow_dangerous_deserialization=True)` is a real security risk if untrusted files can reach the index directory.
- The cache in `process_documents()` is incomplete and misleading: it avoids rewriting table files, but it still rebuilds embeddings and the FAISS index every time.
- The pipeline has duplicated orchestration logic in CLI and Streamlit.
- Several names are broader than the behavior they actually implement.
- Some settings are loosely pinned, which increases upgrade breakage risk.
- There is prompt-injection exposure because raw document content is passed directly into the LLM prompt.

---

## 2. Document Lifecycle, End to End

### 2.1 High-level flow

```mermaid
flowchart TD
    A[Input PDF or Markdown] --> B{Entry point}
    B -->|CLI| C[backend/main.py]
    B -->|UI| D[backend/app.py]

    C --> E[process_pdf_to_rag() or process_documents()]
    D --> E

    E --> F[MinerUConverter.convert()]
    F --> G[assets/markdown/<doc>.md]
    F --> H[assets/markdown/<doc>/<doc>/auto/...]

    E --> I[parse_bundles_from_md()]
    I --> J[context + table grid bundles]

    E --> K[storage.save(grid, output_dir/table_i.<fmt>)]
    E --> L[table_metadata.json]
    E --> M[VectorStoreManager.create_index()]
    M --> N[FAISS index]
    N --> O[extracted_tables/<doc>/faiss_index/index.faiss]
    N --> P[extracted_tables/<doc>/faiss_index/index.pkl]

    Q[Later question] --> R[load_local()]
    R --> N
    Q --> S[similarity_search()]
    S --> T[query_rag()]
    T --> U[LLM answer_query()]
```

### 2.2 CLI entry point

The CLI entry point is [`backend/main.py`](backend/main.py). It accepts:

- `--pdf`: convert a PDF through MinerU first.
- `--input`: process an existing Markdown file directly.
- `--format`: choose how extracted tables are archived on disk (`md`, `json`, `html`, `xml`).
- `--output_dir`: base directory for per-document storage.
- `--query`: ask one question immediately after indexing.
- `--provider`: select Ollama or Gemini.

If neither `--pdf` nor `--input` is provided, the code defaults to `assets/markdown/test1_2page_output.md`.

Behavior in order:

1. Derive `doc_name` from the input file stem.
2. Build `doc_dir = extracted_tables/<doc_name>`.
3. Build `faiss_index_path = extracted_tables/<doc_name>/faiss_index`.
4. Build the storage backend with `get_storage(args.format)`.
5. Build the summarizer with `get_summarizer(provider=args.provider)`.
6. Build the vector manager with `VectorStoreManager(provider=args.provider)`.
7. If a FAISS index already exists and the input is not a PDF, load it.
8. If `--pdf` is provided, run the PDF-to-Markdown-to-index pipeline.
9. Otherwise, process the Markdown input directly.
10. If `--query` is provided, answer that question.
11. If not, start an interactive question loop.

### 2.3 Streamlit entry point

The Streamlit UI lives in [`backend/app.py`](backend/app.py).

It provides:

- Provider selection.
- PDF upload.
- Markdown input path.
- Storage-format selection.
- Document selector.
- Re-process button.
- Chat-style Q&A over the active document.

The UI keeps a cached tool bundle via `@st.cache_resource`, which contains:

- `summarizer`
- `vector_mgr`
- `storage`

Document activation happens through `activate_doc(doc_name)`.

If the FAISS index exists for that document:

- The index is loaded directly.
- The active summarizer and vector manager are stored in session state.
- Chat history is reset when switching to a different document.

If the FAISS index does not exist but a matching Markdown file can be found, the app reprocesses from Markdown and then loads the new index.

### 2.4 PDF conversion stage

The PDF conversion stage is handled by [`backend/src/parsers/mineru_converter.py`](backend/src/parsers/mineru_converter.py).

Resolution order for the MinerU binary:

1. Explicit constructor argument.
2. `MINERU_BINARY_PATH`.
3. `backend/.venv` or project-root `.venv`.
4. System `PATH` via `shutil.which("mineru")`.

The `convert()` method:

1. Validates that the PDF exists.
2. Builds a per-PDF MinerU output directory under `assets/markdown/<pdf_stem>/`.
3. Deletes any existing run directory with `shutil.rmtree()`.
4. Runs the MinerU CLI with `subprocess.run()`.
5. Locates the generated Markdown file in the MinerU output tree.
6. Copies that file to a convenience path: `assets/markdown/<pdf_stem>.md`.
7. Returns the convenience Markdown path.

This means the repository keeps two relevant Markdown artifacts for PDFs:

- The convenience copy at `assets/markdown/<pdf_stem>.md`.
- The full MinerU output tree under `assets/markdown/<pdf_stem>/<pdf_stem>/...`.

### 2.5 Markdown parsing stage

Markdown parsing happens in [`backend/src/parsers/table_processor.py`](backend/src/parsers/table_processor.py).

`parse_bundles_from_md()`:

- Reads the Markdown file.
- Splits it around HTML `<table>...</table>` blocks.
- Parses each HTML table into a rectangular 2D grid.
- Tracks active Markdown headings as sticky section context.
- Carries forward the most recent body text between consecutive tables.
- Produces a bundle for each table containing:
  - `context`
  - `table`
  - `raw_html`

This parser is tightly coupled to MinerU-like Markdown that contains HTML tables. It does not handle general Markdown tables.

### 2.6 Table serialization and caching stage

This stage is implemented in [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py) via `process_documents()`.

For each parsed bundle:

1. A `table_id` such as `table_0` is assigned.
2. The table grid is converted to JSON.
3. A single chunk is created:
   - `CONTEXT:\n{context}\n\nTABLE (JSON):\n{table_json}`
4. A SHA-256 hash is computed from that chunk.
5. If the hash matches the previous run, the file write is skipped.
6. Otherwise, the table is persisted through the storage backend.
7. Metadata is stored in `table_metadata.json`.
8. The chunk and metadata are fed to FAISS.
9. The FAISS index is saved to `extracted_tables/<doc_name>/faiss_index/`.

Important detail:

- The cache only suppresses the archive-file write for unchanged tables.
- It does not skip embedding creation or FAISS rebuilding.
- So the cache is partial, not a full incremental-indexing system.

### 2.7 Retrieval and question answering stage

Queries are handled by `query_rag()` in [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py).

The flow is:

1. Read `RETRIEVAL_K` from the environment, defaulting to `1`.
2. Run `vector_mgr.search(query_text, k=k_val)`.
3. If no results are found, return a no-match response.
4. Otherwise, concatenate the retrieved chunk texts.
5. Pass the concatenated context to `summarizer.answer_query(query_text, combined_tables)`.
6. Return the answer, the raw table context, and the retrieved documents.

The LLM prompt template comes from `QA_SYSTEM_PROMPT` in the environment.

### 2.8 Can questions be asked later without reprocessing?

Yes, as long as the document’s FAISS index exists and the index is loadable with the same embedding provider configuration.

Practically:

- CLI: `main.py` loads an existing FAISS index automatically when the input is not a PDF.
- Streamlit: `activate_doc()` loads the saved index for the selected document.
- If the index is missing and a Markdown source file exists, the app can reprocess from Markdown.

Important caveat:

- The code does not automatically verify that the embedding provider/model used to load the index matches the one used to build it.
- If the provider changes, the old index may become invalid or misleading, and the app does not force a rebuild.

### 2.9 Where embeddings are stored

Embeddings are stored inside the FAISS index created by LangChain and written under:

- `extracted_tables/<doc_name>/faiss_index/index.faiss`
- `extracted_tables/<doc_name>/faiss_index/index.pkl`

Additional per-document artifacts include:

- `extracted_tables/<doc_name>/table_metadata.json`
- `extracted_tables/<doc_name>/table_0.<fmt>` and similar archived table files

The chunk texts embedded into FAISS are not raw table files. They are in-memory strings that combine context and JSON table content.

---

## 3. Data Artifacts and Storage Layout

### 3.1 Runtime directories

The current architecture stores data in two main places:

- `assets/markdown/` for MinerU output.
- `extracted_tables/` for per-document table archives and indexes.

### 3.2 Per-document structure

A processed document generally looks like this:

```text
assets/markdown/
  <doc>.md
  <doc>/
    <doc>/
      auto/
        ...

extracted_tables/
  <doc>/
    table_0.json
    table_1.json
    table_metadata.json
    faiss_index/
      index.faiss
      index.pkl
```

### 3.3 What each artifact is for

- `assets/markdown/<doc>.md`: canonical Markdown input for parsing.
- `extracted_tables/<doc>/table_*.{md,json,html,xml}`: archival copy of each extracted table.
- `table_metadata.json`: content hashes, table IDs, and snippets used for change detection.
- `faiss_index/index.faiss`: vector index data.
- `faiss_index/index.pkl`: serialized LangChain FAISS metadata store.

### 3.4 What is and is not persisted

Persisted:

- Table grids, serialized by the selected storage format.
- Table metadata and hashes.
- FAISS index and document metadata required for retrieval.
- Convenience Markdown from MinerU.

Not persisted as a separate durable layer:

- Raw embedding vectors outside FAISS.
- The parsed bundle structure itself.
- Any structured provenance map from query answer back to exact source table cell spans.

---

## 4. Risks, Vulnerabilities, and Deprecated or Fragile Patterns

### 4.1 High severity: unsafe FAISS deserialization

Location: [`backend/src/parsers/vector_store.py`](backend/src/parsers/vector_store.py)

Current code:

- `FAISS.load_local(folder_path, self.embeddings, allow_dangerous_deserialization=True)`

Why this matters:

- This flag explicitly allows deserializing a pickle-backed file.
- If an attacker can place a malicious `index.pkl` into a loaded directory, code execution is possible during load.
- The risk is bounded by local file trust, but it is still a genuine security issue.

Possible fixes:

- Avoid loading indexes from untrusted sources.
- Add a trust boundary check and only load indexes created by this application.
- Store and validate a signed manifest before loading.
- If feasible, use a safer persistence layer than pickle-backed deserialization.

### 4.2 High severity: prompt injection exposure

Location: [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py) and summarizer implementations.

Current behavior:

- Retrieved table chunks are concatenated and passed verbatim into the LLM prompt.
- The context includes content derived from the source document.

Why this matters:

- Untrusted documents can embed instructions that try to manipulate the model.
- Tables and surrounding context are not sanitized or isolated from the system prompt.

Possible fixes:

- Use strict prompt separation and stronger instruction hierarchy.
- Strip or neutralize obvious prompt-like artifacts from retrieved content.
- Put retrieved content in a structured data envelope and ask the LLM to treat it as inert evidence.
- Add prompt-injection testing if this repo will process third-party documents.

### 4.3 Medium severity: destructive directory wipes

Locations:

- [`backend/src/parsers/mineru_converter.py`](backend/src/parsers/mineru_converter.py)
- [`backend/app.py`](backend/app.py)

Current behavior:

- Existing MinerU output directories are deleted before reprocessing.
- The Streamlit reprocess button deletes the active document directory with `shutil.rmtree(doc_dir)`.

Why this matters:

- If path derivation ever goes wrong, the deletion is destructive.
- There is no explicit safety check that the target stays inside the expected root.

Possible fixes:

- Add a helper that confirms the resolved path is a child of the expected base directory before deleting.
- Refuse to delete unless the directory looks like a generated document directory.
- Keep a backup or versioned output directory when reprocessing.

### 4.4 Medium severity: partial cache that looks stronger than it is

Location: [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py)

Current behavior:

- `table_metadata.json` is used to detect whether table files changed.
- On a cache hit, table file writes are skipped.
- Embeddings and FAISS rebuilding still happen every run.

Why this matters:

- The presence of a cache file suggests incremental indexing, but the implementation does not actually avoid the expensive steps.
- This can mislead maintainers and complicate debugging.

Possible fixes:

- Remove the cache entirely if incremental indexing is not needed.
- Or implement real incremental indexing that reuses unchanged embeddings and only updates changed tables.
- If the cache is retained, rename it to reflect that it is only an artifact hash manifest.

### 4.5 Medium severity: stale or incompatible index reuse

Locations:

- [`backend/main.py`](backend/main.py)
- [`backend/app.py`](backend/app.py)
- [`backend/src/parsers/vector_store.py`](backend/src/parsers/vector_store.py)

Current behavior:

- Existing FAISS indexes are loaded whenever present.
- The code does not verify that the current embedding provider/model matches the provider used to build the index.

Why this matters:

- Switching between Ollama and Gemini can invalidate retrieval quality or break compatibility.
- The current UI lets the user switch provider, but it does not force a rebuild when provider settings change.

Possible fixes:

- Store provider and model metadata alongside the index.
- Refuse to load when the current provider/model does not match the saved metadata.
- Provide an explicit rebuild path when the provider changes.

### 4.6 Medium severity: loosely pinned dependencies

Location: [`backend/requirements.txt`](backend/requirements.txt)

Examples:

- `langchain>=0.2.0`
- `langchain-community>=0.2.0`
- `mineru[all]`
- `google-generativeai>=0.5.0`

Why this matters:

- Broad lower-bound pins are more likely to absorb breaking API changes.
- `mineru[all]` is especially broad and may pull in a moving set of transitive dependencies.

Possible fixes:

- Add a lockfile or pin to tested versions.
- Introduce upper bounds for fast-moving packages.
- Separate optional dependencies more cleanly between local and cloud-only provider modes.

### 4.7 Low-to-medium severity: silent fallback on invalid storage format

Location: [`backend/src/parsers/storage.py`](backend/src/parsers/storage.py)

Current behavior:

- `get_storage(format_type)` falls back to `MarkdownStorage()` for unknown input.

Why this matters:

- A typo in configuration silently changes behavior instead of failing fast.
- This can hide misconfiguration and make debugging harder.

Possible fixes:

- Raise `ValueError` for unsupported format types.
- Let the caller choose an explicit fallback if needed.

### 4.8 Low-to-medium severity: markdown discovery is heuristic

Location: [`backend/app.py`](backend/app.py)

Current behavior:

- If a FAISS index is missing, the app tries two Markdown paths:
  - `assets/markdown/<doc>.md`
  - `assets/markdown/<doc>/<doc>.md`

Why this matters:

- This works for the current layout, but it is a heuristic rather than an explicit manifest.
- If output conventions change, reprocessing can fail even though the underlying data exists.

Possible fixes:

- Store the source Markdown path in `table_metadata.json` or a document manifest.
- Use a single canonical location for source Markdown references.

### 4.9 Low severity: user-controlled file names are written directly

Locations:

- [`backend/app.py`](backend/app.py)
- [`backend/src/parsers/mineru_converter.py`](backend/src/parsers/mineru_converter.py)

Current behavior:

- Uploaded PDF names are used directly when writing to `assets/pdfs/`.
- PDF stems are used directly for output directory names.

Why this matters:

- It is mostly safe because paths are rooted under controlled directories.
- But it still assumes file names are well-formed and non-hostile.

Possible fixes:

- Sanitize file names to a normalized slug.
- Reject or normalize path separators and strange characters.

### 4.10 Low severity: error handling is uneven

Examples:

- `json.load()` on `table_metadata.json` is not wrapped.
- `MinerUConverter._find_markdown()` returns the first `.md` it finds.
- `process_documents()` assumes parse success and does not guard against malformed input beyond parser output.

Possible fixes:

- Add a small validation layer for metadata and generated outputs.
- Report a clear error when the cache file is malformed.
- Tighten MinerU output discovery to prefer the expected path rather than the first match.

---

## 5. Redundant Code, Repeated Logic, and Cleanup Candidates

### 5.1 Unused constant

Location: [`backend/src/parsers/table_processor.py`](backend/src/parsers/table_processor.py)

Findings:

- `TABLE_PATTERN` is defined but not used anywhere.

Why it matters:

- It is dead code.
- It adds noise and can confuse readers into thinking it is part of the parsing logic.

Suggested fix:

- Remove the constant.

### 5.2 Incomplete cache logic

Location: [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py)

Findings:

- `cached_data` is loaded.
- `new_cache` is written.
- But there is no real reuse of embeddings, index entries, or downstream artifacts.

Why it matters:

- This is more complicated than the behavior justifies.
- The code reads like a full caching system, but it only avoids rewriting unchanged table files.

Suggested fix:

- Remove the cache and simplify the code, or build a real incremental indexer.

### 5.3 Duplicate orchestration in CLI and UI

Locations:

- [`backend/main.py`](backend/main.py)
- [`backend/app.py`](backend/app.py)
- [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py)

Findings:

- Both the CLI and Streamlit layers compute the same per-document paths.
- Both instantiate provider-specific tools in similar ways.
- Both decide whether to load an existing index or build a new one.

Why it matters:

- The same flow is implemented twice.
- Any change to document resolution or provider handling must be repeated in multiple places.

Suggested fix:

- Centralize document resolution and pipeline orchestration into a small service module.
- Let CLI and UI call into the same coordinator function.

### 5.4 Storage format is now mostly archival

Location: [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py)

Findings:

- Retrieval no longer reads archived table files.
- The serialized table files are only saved for disk persistence and inspection.

Why it matters:

- The `storage_format` option sounds central, but it only affects archival output.
- That makes the public API look broader than the actual runtime dependency.

Suggested fix:

- Rename the option to something like `archive_format` if that reflects intent better.
- Or remove the format toggle if the archives are not used operationally.

### 5.5 Lots of status emojis in the UI

Location: [`backend/app.py`](backend/app.py)

Findings:

- The UI uses emoji-prefixed labels extensively, such as titles, sidebar headings, status text, and captions.

Why it matters:

- This is not a functional problem, but it adds visual noise and makes the code less consistent with the rest of the project.
- If the goal is a cleaner operational UI, these can be simplified.

Suggested fix:

- Replace the emoji-heavy labels with plain labels or restrict emojis to one or two high-value affordances.

### 5.6 Comments that restate adjacent code

Locations:

- [`backend/src/parsers/mineru_converter.py`](backend/src/parsers/mineru_converter.py)
- [`backend/src/parsers/table_processor.py`](backend/src/parsers/table_processor.py)

Findings:

- Several comments simply rephrase the surrounding line or block.
- Some are helpful, but others are only repeating the obvious.

Examples of lower-value comment patterns:

- “Split content by table tags but keep the tags.”
- “Fresh text block before this table — update state.”
- “Assemble context: headings + body text.”
- “Use the PDF stem as the subdirectory name.”

Why it matters:

- These comments age poorly because they repeat intent already visible in code.
- They create clutter without increasing comprehension much.

Suggested fix:

- Keep only comments that explain non-obvious constraints or rationale.
- Remove comments that merely narrate the code.

### 5.7 Duplicate document activation logic

Location: [`backend/app.py`](backend/app.py)

Findings:

- `activate_doc()`, `process_uploaded_pdf()`, and `process_md_file()` all repeat parts of the same setup.
- They derive the document name, build output paths, create tool objects, and set session state in similar ways.

Why it matters:

- This is more branching than necessary for a fairly small workflow.
- It makes the app harder to reason about when adding another source type.

Suggested fix:

- Factor a single helper that returns the resolved document paths and tool bundle.
- Keep the source-specific code paths thin.

### 5.8 Broad factory plus broad vector store wrapper

Locations:

- [`backend/src/llm/provider_factory.py`](backend/src/llm/provider_factory.py)
- [`backend/src/parsers/vector_store.py`](backend/src/parsers/vector_store.py)

Findings:

- The provider factory and the vector manager are both doing selection and construction work.
- `VectorStoreManager` currently behaves as a FAISS wrapper with provider switching built in.

Why it matters:

- The class name suggests a general manager, but the implementation is really a FAISS-specific wrapper.
- Provider selection and vector-store persistence are mixed together.

Suggested fix:

- Split provider selection from the index wrapper.
- Rename the class to something more explicit if FAISS is the only backend.

---

## 6. Convoluted or Overengineered Areas and Simpler Alternatives

### 6.1 Full rerun indexing when only one table changes

Current behavior:

- Even when `table_metadata.json` indicates no content change, the code still re-embeds all chunks and rewrites the FAISS index.

Why this is convoluted:

- The cache suggests incremental operation, but the implementation is effectively full rebuilds.
- This is more code than a straight rebuild, but with little practical gain.

Simpler alternative:

- Remove the cache and always rebuild.
- Or implement actual incremental document-level or table-level updates.

### 6.2 Separate archive formats for content that retrieval never reads

Current behavior:

- `storage.py` can write Markdown, JSON, HTML, or XML copies of each table.
- Retrieval uses the in-memory chunk text, not the saved files.

Why this is convoluted:

- The storage layer is not part of the RAG path anymore.
- The format switch becomes a side-effect preference rather than a pipeline requirement.

Simpler alternative:

- Keep one archival format, usually JSON, and remove the rest unless there is a concrete consumer.
- Or move archival storage behind a clearly labeled export feature.

### 6.3 Automatic “reprocess from Markdown” fallback

Current behavior:

- If an index is missing, the app hunts for a Markdown file and reprocesses it.

Why this is convoluted:

- The app silently tries to repair state at load time.
- It depends on a heuristic lookup for source Markdown.

Simpler alternative:

- Store the source path in a manifest.
- Make reprocessing an explicit user action.

### 6.4 Context-building heuristic in the table parser

Current behavior:

- The parser maintains sticky headings and carries body text forward across table boundaries.

Why this is convoluted:

- It is useful, but the logic is subtle and stateful.
- It can be hard to predict which text will end up in which bundle.

Simpler alternative:

- Emit explicit document-section objects first, then attach tables to the nearest section.
- Or store a simplified context model with one heading stack and one immediate preceding block only.

### 6.5 Provider selection duplicated across layers

Current behavior:

- CLI and UI both pick a provider and instantiate the same backend classes.

Why this is convoluted:

- The application surface is already small, so provider orchestration should live in one place.

Simpler alternative:

- Build a single `create_runtime(provider, storage_format)` helper.
- Have both entry points call it.

### 6.6 Mixed responsibilities in `process_pdf_to_rag()`

Current behavior:

- One function handles conversion, parsing, indexing, and progress logging.

Why this is convoluted:

- It is okay for a small script, but the function is already acting as a coordinator.

Simpler alternative:

- Split it into `convert_pdf_to_markdown()`, `index_markdown_document()`, and a thin orchestration wrapper.
- This would make the pipeline easier to test mentally and easier to reuse from other entry points.

---

## 7. Naming and Organization Problems

### 7.1 `process_documents()` is broader than its name suggests

Location: [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py)

It does more than process documents:

- Parses markdown.
- Serializes tables.
- Caches artifact metadata.
- Builds embeddings.
- Builds and saves FAISS.

A more descriptive name would be something like `index_markdown_document()` or `build_document_index()`.

### 7.2 `VectorStoreManager` is FAISS-specific

Location: [`backend/src/parsers/vector_store.py`](backend/src/parsers/vector_store.py)

The name suggests a general abstraction, but the implementation only manages FAISS.

A clearer name would be something like `FaissIndexManager` or `FaissVectorStoreManager`.

### 7.3 `storage.py` sounds central, but it is now an archive formatter

Location: [`backend/src/parsers/storage.py`](backend/src/parsers/storage.py)

The file name implies storage is part of the runtime pipeline. In practice, it is mostly a file-export helper.

A clearer name could be `table_exporters.py` or `table_archive.py` if that matches intended use.

### 7.4 `query_rag()` is accurate, but it hides the retrieval-then-generation split

Location: [`backend/routes/rag_routes.py`](backend/routes/rag_routes.py)

The function does two distinct things:

- Retrieval.
- Answer synthesis.

If the project grows, it may be clearer to separate those responsibilities.

---

## 8. Behavior That Is Good and Should Be Preserved

To avoid overcorrecting, a few current choices are worth keeping:

- Per-document output directories are a good improvement over a flat shared store.
- Storing the embedded chunk text inside FAISS is a practical simplification for retrieval.
- Supporting both local Ollama and cloud Gemini providers is a useful flexibility point.
- Loading an existing index later without rebuilding is exactly the right behavior for this use case.

---

## 9. Recommended Remediation Order

If this were being cleaned up incrementally, the safest order would be:

1. Remove or guard `allow_dangerous_deserialization=True`.
2. Add provider/model metadata to the saved index and refuse mismatches.
3. Delete the unused `TABLE_PATTERN` constant and other dead code.
4. Decide whether the current cache is worth keeping; remove it if not.
5. Simplify the duplicate orchestration in `main.py` and `app.py`.
6. Tighten `get_storage()` so invalid formats fail fast.
7. Pin dependencies more tightly.
8. Reduce emoji-heavy UI labels if a cleaner operational UI is desired.

---

## 10. Bottom Line

The repository’s core pipeline is coherent and usable. The biggest practical risk is unsafe FAISS deserialization, followed by stale-provider/index mismatches and a cache that looks smarter than it is. The biggest maintainability issues are duplicated orchestration, an over-broad storage abstraction, and a handful of unused or narrating comments/constants that can be removed without changing behavior.
