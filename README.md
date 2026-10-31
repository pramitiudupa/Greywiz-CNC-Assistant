# Greywiz — CNC Fault Assistant

FastAPI + Vite app for one CNC machine. The owner uploads the machine's documents
(manual, alarm list, service notes). Later, any worker can report a problem with a
**photo**, a **description**, or both, and Greywiz answers with the most likely cause
and simple steps — each step linked to the page of the machine's own manual it
came from.

## Report a problem (photo diagnosis)

1. **Read the photo** — Gemini vision names the part (e.g. the Emergency Stop button),
   copies any alarm text on the screen, and suggests what to search for.
2. **Search the documents** — hybrid search (FAISS + BM25) over every processed
   document of the machine, plus past problems at this shop that were marked fixed.
3. **Explain** — Gemini writes the likely cause, other possible causes and steps in
   plain language, citing the numbered excerpts it used.
4. **Check the sources** — code (not the model) removes citations that do not exist
   and moves any uncited step into a separate "General advice (not found in your
   documents)" box. Safety warnings are always shown first.

Each report is saved under `backend/data/cases/`. When a worker writes what actually
fixed it and clicks **Mark as fixed**, that note is used for similar problems later.

Endpoints: `GET/PUT /api/machine`, `POST /api/diagnose` (form fields `description`,
`photo`), `GET /api/cases`, `GET /api/cases/{id}`, `GET /api/cases/{id}/photo`,
`PATCH /api/cases/{id}`.

## Run on Windows

Requires Python 3.12 (`py -3.12`) and Node.js. From this folder:

```powershell
npm run setup:win   # one time: creates backend\.venv, installs everything
npm run dev:win     # starts backend (8000) and frontend (5173)
```

Then open http://127.0.0.1:5173. Put your `GOOGLE_API_KEY` in `backend/.env`
(photo diagnosis needs Gemini). MinerU runs on the CPU, so a 50-page manual takes
several minutes to process the first time.

---

The original TableRAG document processor notes follow.

The original Python processing pipeline is still used:

- `backend/routes/rag_routes.py`
- `backend/src/parsers/*`
- `backend/src/llm/*`

The FastAPI app wraps that logic with REST endpoints, and the completed dashboard UI calls those endpoints through a centralized Axios client.

## Project Layout

```text
backend/
  api.py                 FastAPI REST app
  app.py                 Original Streamlit UI, kept for reference
  main.py                Original CLI entry point
  routes/rag_routes.py   Existing processing and RAG pipeline
  src/                   Existing parser, vector store, and LLM code
frontend/
  index.html             Completed dashboard UI
  src/api.ts             Centralized Axios client
  src/main.ts            UI wiring, upload, processing, chat, loading/error states
scripts/
  dev.sh                 Starts backend and frontend together
```

## Run In Antigravity

Open this folder:

```bash
/Users/abhaykulkarni/23junlatest/Greywiz-Project-1
```

Install dependencies:

```bash
npm run setup
```

Start the whole app:

```bash
npm run dev
```

If your IDE uses pnpm instead of npm, the same commands work as:

```bash
pnpm setup
pnpm dev
```

Then open:

```text
http://127.0.0.1:5173
```

FastAPI runs at:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Environment

Backend config lives in:

```text
backend/.env
```

Use `backend/.env.example` as the safe template.

Frontend config lives in:

```text
frontend/.env
```

Use `frontend/.env.example` as the template. The default backend URL is:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Useful Commands

Run backend only:

```bash
npm run backend
```

Run frontend only:

```bash
npm run frontend
```

Build frontend:

```bash
npm run build
```

Type-check frontend:

```bash
npm run typecheck
```

## Main API Endpoints

- `GET /api/health`
- `GET /api/documents`
- `POST /api/documents/upload`
- `POST /api/documents/{document_id}/process`
- `GET /api/documents/{document_id}/tables`
- `GET /api/documents/{document_id}/pdf`
- `DELETE /api/documents/{document_id}`
- `POST /api/chat`
