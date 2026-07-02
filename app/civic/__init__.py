"""Civic-intelligence slice for task-forge.

A thin, additive RAG spine over Philadelphia City Council legislation:

    Legistar (Matters) -> normalize -> chunk -> embed into Postgres + pgvector
    -> HYBRID retrieval (dense pgvector + lexical tsvector, fused with RRF)
    -> CITE-OR-REFUSE grounded answer via a local LLM (Ollama).

This package is deliberately isolated from the existing SQLite tasks/auth code:
it has its own Postgres db layer (``app.civic.db``), its own config fields
(prefixed on the shared ``app.config.Settings``), and its own routers. Nothing
here modifies or depends on the tasks/users tables.

Module map (see docs/CIVIC_SLICE.md for the full walkthrough):
  * ``schemas``      — dataclasses + Pydantic request/response wire contract.
  * ``db``           — Postgres + pgvector connection, schema, upsert helpers.
  * ``embeddings``   — local fastembed (bge-small, 384-dim) embedding.
  * ``ingest``       — fetch Legistar Matters -> normalize -> chunk -> embed -> upsert.
  * ``retrieval``    — hybrid dense+lexical retrieval fused with RRF.
  * ``answer``       — cite-or-refuse synthesis + independent citation verification.
  * ``routers.*``    — POST /civic/ingest and POST /civic/ask.
"""
