# Docket

Civic-intelligence platform. Ask plain-English questions about real local legislation and get answers that are **grounded in the source records** — with citations — or an honest "I can't ground that" when the data doesn't support an answer.

Currently covers **Philadelphia City Council** legislation (via the Legistar public API), with a roadmap toward additional jurisdictions and, eventually, national coverage.

## What it does

1. **Ingest** — pulls Philadelphia City Council matters from Legistar, extracts the full bill text from each Matter's PDF attachment (falling back to the title when a PDF is missing or unreadable), normalizes the messy real-world data (null fields, HTML in titles, transmittal boilerplate, duplicate/amended records), chunks it, and stores it in Postgres with vector embeddings.
2. **Hybrid retrieval** — combines dense (pgvector) and keyword (Postgres full-text) search, fused with Reciprocal Rank Fusion, to find the most relevant records.
3. **Cite-or-refuse answers** — a local LLM (via Ollama, $0) answers *only* from the retrieved records and must cite each claim to a real bill, or explicitly refuse. Every citation is independently verified against what was actually retrieved, so the model can't invent a source — and it reports a bill's status only from the record, so it never presents a pending bill as enacted law.

## Status

Working Philadelphia slice: full-text ingestion → hybrid retrieval → cited answers → web UI, on a $0 local stack (Postgres + pgvector + Ollama). **617 tests** on the civic modules. See [`docs/CIVIC_CONTEXT.md`](docs/CIVIC_CONTEXT.md) for the full architecture, test inventory, and roadmap.

## Quickstart (local)

Requires Docker and [Ollama](https://ollama.com) with `llama3.1:8b` pulled.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker compose up -d
ollama pull llama3.1:8b
.venv/bin/python -c "from app.civic import db, ingest; db.init(); print(ingest.run_ingest()); db.close_pool()"
.venv/bin/uvicorn app.main:app
```

Then ask a question:

```bash
curl -s -X POST localhost:8000/civic/ask -H 'content-type: application/json' \
  -d '{"question":"What recent legislation concerns zoning?"}'
```

### Web UI

With the API running on `:8000`, start the Next.js frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) and ask a question from the
browser. The UI (in [`frontend/`](frontend/)) is a single clean page that POSTs
to `/civic/ask` and renders the grounded answer with its bill citations, or the
refusal when the records don't support one. It reads the API base URL from
`NEXT_PUBLIC_API_URL` (see `frontend/.env.local.example`, default
`http://localhost:8000`); the backend allows the `:3000` dev origin via CORS.

`POST /civic/ask` never crashes for the normal failure modes: an unreachable
civic database, an unreachable Ollama, a missing Anthropic key, or an
ungroundable question all return `refused: true` with a clear message rather than
an HTTP 500. Whitespace-only questions are rejected at validation.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Roadmap

- Multi-jurisdiction data model (path to other cities → national)
- Per-tenant auth and data isolation
- Insight digests and alerts (trends, new legislation on tracked topics)
- Background-job ingestion (scheduled refresh)

Built as a full-stack learning and portfolio project.
