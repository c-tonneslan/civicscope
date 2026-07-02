# Civic Intelligence Slice

> Branch: `feat/civic-intel-slice`. Status: **implemented** — the `app/civic/`
> module is complete and both routers are mounted in `app/main.py` (`/civic/ingest`
> and `/civic/ask` are exposed in the OpenAPI schema). Nothing here modifies the
> existing tasks/auth/health code.

## What this slice proves

An end-to-end civic RAG spine, scoped to **Philadelphia only**:

```
Legistar (Philadelphia City Council Matters)
    -> normalize            (map the Legistar JSON to civic_documents)
    -> chunk                (split title/text into embeddable units)
    -> embed                (fastembed bge-small, 384-dim, local, $0)
    -> Postgres + pgvector  (civic_documents + civic_chunks)
    -> HYBRID retrieval     (dense pgvector + lexical tsvector, fused with RRF)
    -> CITE-OR-REFUSE answer (local Ollama; every claim cites a retrieved bill or refuses)
```

The point of the slice is to demonstrate the *spine* works, not to be complete.
It is deliberately additive: it lives alongside the existing SQLite
tasks/users/health API and shares none of its tables or connections.

## Where it sits in the repo

```
app/
  config.py            # EXTENDED: civic_database_url, ollama_*, llm_provider,
                       #           legistar_client, ingest_token (additive fields)
  main.py              # EXTENDED: includes the two civic routers + pool shutdown
  civic/
    __init__.py        # package overview / module map
    schemas.py         # CivicDocument / CivicChunk + Ask/Ingest wire models
    db.py              # Postgres + pgvector pool, schema init(), upserts
    embeddings.py      # fastembed bge-small (384-dim), lazy singleton
    ingest.py          # Legistar fetch -> normalize -> chunk -> embed -> upsert
    retrieval.py       # dense + lexical + RRF hybrid retrieval
    answer.py          # cite-or-refuse synthesis + citation verification
    routers/
      ingest.py        # POST /civic/ingest (token-gated, 503 if no token)
      ask.py           # POST /civic/ask
docs/
  CIVIC_SLICE.md       # this file
docker-compose.yml     # pgvector/pgvector:pg16 service (civicscope DB)
tests/
  test_civic_rrf.py         # pure RRF fusion unit test (no DB/LLM)
  test_civic_citations.py   # citation-verifier unit test (no DB/LLM)
  test_civic_db.py          # Postgres smoke test that SKIPS cleanly if no DB
```

## Data model (Postgres + pgvector)

Two tables, defined as idempotent SQL in `app/civic/db.py`:

**`civic_documents`** — one row per Legistar Matter.

| column      | notes                                                        |
|-------------|--------------------------------------------------------------|
| id          | BIGSERIAL PK                                                 |
| source_ref  | Legistar `MatterId`, **UNIQUE** — the idempotent upsert key  |
| doc_type    | `MatterTypeName` (e.g. "Resolution", "COMMUNICATION")        |
| file_no     | `MatterFile` (e.g. "260633") — used as the citation key      |
| title       | `MatterTitle` (falls back to `MatterName`)                   |
| body_name   | `MatterBodyName` (e.g. "CITY COUNCIL")                       |
| status      | `MatterStatusName`                                           |
| intro_date  | `MatterIntroDate` (DATE)                                     |
| url         | canonical Legistar URL for the matter                        |
| raw         | JSONB — the full original Legistar record                   |
| loaded_at   | TIMESTAMPTZ DEFAULT now() — timestamps owned by the db layer |

**`civic_chunks`** — one row per embeddable unit.

| column      | notes                                                        |
|-------------|--------------------------------------------------------------|
| id          | BIGSERIAL PK                                                 |
| document_id | FK -> civic_documents(id) ON DELETE CASCADE                  |
| chunk_index | INT, ordinal within the document                            |
| text        | the chunk text                                              |
| embedding   | VECTOR(384) — bge-small dense embedding                     |
| tsv         | TSVECTOR GENERATED from text — never goes stale             |
| —           | UNIQUE (document_id, chunk_index)                           |

Indexes: a **GIN** index on `civic_chunks.tsv` (lexical search) and an
**ivfflat**/hnsw cosine index on `civic_chunks.embedding` (dense search). The
`vector` extension is enabled in `init()` before any `vector(...)` column.

## The flow, end to end

1. **Ingest** (`ingest.py`, `POST /civic/ingest`). Paginate Philadelphia
   `Matters` from the Legistar Web API (`https://webapi.legistar.com/v1/phila/`)
   with a descriptive User-Agent and polite rate limiting. Normalize each Matter
   into a `civic_documents` row (keeping the full `raw` JSON), chunk its
   title/text into `civic_chunks`, embed the chunks with fastembed, and upsert
   idempotently on `source_ref` (re-running refreshes in place).

2. **Retrieve** (`retrieval.py`). Embed the question once. Run two retrievers
   over `civic_chunks`: **dense** (pgvector cosine, `embedding <=> %s::vector`)
   and **lexical** (`ts_rank` over `tsv` filtered by `plainto_tsquery`). Fuse
   the two ranked lists with **Reciprocal Rank Fusion** (`k=60`), then hydrate
   the top-k fused chunk ids back to their parent documents (file_no + title).

3. **Answer** (`answer.py`, `POST /civic/ask`). The LLM (local Ollama,
   `llama3.1:8b`) sees ONLY the retrieved chunks and must cite each claim to a
   retrieved bill (e.g. `[Bill 260633]`) or emit the fixed refusal phrase. We
   then **independently verify** every citation against the retrieved file_nos —
   invented citations are dropped, and an answer with no surviving citations is
   returned as a refusal. Graceful when Ollama is unreachable (refuse with a
   hint, never crash).

## Why hybrid + RRF (the defensible bit)

Dense embedding search understands paraphrase but can miss an exact token like a
bill number or a committee name. Lexical full-text search nails exact tokens but
is blind to paraphrase. RRF fuses the two rankings without needing their scores
to be on the same scale: each document scores `Σ 1/(k + rank)` across the lists
it appears in, `k=60` damping top-rank dominance. It is simple, robust, and easy
to defend in review. The fusion function is pure and unit-tested with no I/O.

## Cite-or-refuse (the trust bit)

Grounding is enforced twice: once by prompt (the model is told to cite every
claim by bill number or refuse) and once by us (we re-scan the answer and drop
any citation whose file_no was not in the retrieved set). The second check is
what makes the guarantee hold even when the model misbehaves — a hallucinated
bill number cannot survive into the response.

## How to run

```bash
# 1. Start Postgres + pgvector.
docker compose up -d db

# 2. Install deps (adds psycopg[binary], pgvector, fastembed to the base set).
pip install -r requirements.txt

# 3. (Optional) start the local LLM for cited answers.
ollama serve
ollama pull llama3.1:8b

# 4. Run the API (existing app; civic routers are additive).
uvicorn app.main:app --reload

# 5. Ingest Philadelphia legislation (requires INGEST_TOKEN to be set).
export INGEST_TOKEN=dev-secret
curl -X POST localhost:8000/civic/ingest -H "X-Ingest-Token: dev-secret"

# 6. Ask a grounded question.
curl -X POST localhost:8000/civic/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What recent communications went to City Council?"}'
```

Configuration (all have safe local defaults; see `app/config.py`):
`civic_database_url`, `ollama_host`, `ollama_model`, `llm_provider`,
`legistar_client`, `ingest_token`.

## Non-goals (explicitly deferred to later slices)

- **No auth / no multi-tenancy** on the civic routes this slice.
- **No background jobs / schedulers** — ingest is a manual, gated HTTP call.
- **No insights / analytics / summarization** beyond the cited Q&A.
- **No web UI.**
- **No jurisdictions beyond Philadelphia** — the scope is hardcoded to `phila`.
- **No document text beyond the Matter title/metadata** — attachment/full-text
  ingestion is left as a stable extension point in the chunking layer.

The existing tasks/users/health API and its 23 tests are untouched by this slice.
