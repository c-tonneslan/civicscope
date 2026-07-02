# civicscope

Civic-intelligence platform. Ask plain-English questions about real local legislation and get answers that are **grounded in the source records** — with citations — or an honest "I can't ground that" when the data doesn't support an answer.

Currently covers **Philadelphia City Council** legislation (via the Legistar public API), with a roadmap toward additional jurisdictions and, eventually, national coverage.

## What it does

1. **Ingest** — pulls Philadelphia City Council matters from Legistar, normalizes the messy real-world data (null fields, HTML in titles, duplicate/amended records), chunks it, and stores it in Postgres with vector embeddings.
2. **Hybrid retrieval** — combines dense (pgvector) and keyword (Postgres full-text) search, fused with Reciprocal Rank Fusion, to find the most relevant records.
3. **Cite-or-refuse answers** — a local LLM (via Ollama, $0) answers *only* from the retrieved records and must cite each claim to a real bill, or explicitly refuse. Every citation is independently verified against what was actually retrieved, so the model can't invent a source — and it reports a bill's status only from the record, so it never presents a pending bill as enacted law.

## Status

Working Philadelphia thin slice: ingestion → hybrid retrieval → cited answers, on a $0 local stack (Postgres + pgvector + Ollama). **579 tests, 99% branch coverage** on the civic modules. See [`docs/CIVIC_CONTEXT.md`](docs/CIVIC_CONTEXT.md) for the full architecture, test inventory, and roadmap.

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

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Roadmap

- Full bill / attachment text ingestion (currently titles + metadata)
- Multi-jurisdiction data model (path to other cities → national)
- Per-tenant auth and data isolation
- Insight digests and alerts (trends, new legislation on tracked topics)
- Web UI

Built as a full-stack learning and portfolio project.
