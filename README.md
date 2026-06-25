# Greywiz Document Processor

FastAPI + Vite version of the existing TableRAG document processor.

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
