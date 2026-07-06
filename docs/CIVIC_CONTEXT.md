# Civic Slice — Test Context (living document)

> Branch: `feat/civic-intel-slice`. This file tracks the **true current state of
> the civic test suite** as of the exhaustive-testing pass. It is the companion to
> `docs/CIVIC_SLICE.md` (which describes the feature); this one describes how the
> feature is *tested*, the full test inventory, how to run it, and what is
> deliberately left to integration / future slices.

## Current status

- **Full suite: 579 passed, 4 skipped, 1 warning** (verified 2026-07-02).
- The 4 skips are the **real-Postgres integration tests** (2 in
  `test_civic_db.py`, 2 in `test_civic_dbconfig.py`) which `skipif` cleanly when
  no civic Postgres is reachable, so CI stays green with no DB.
- The 1 warning is a Starlette `TestClient`/httpx deprecation notice from
  FastAPI — not ours, not actionable here.
- **560 of the 579 tests are civic**; the original **23 tasks/auth/health tests
  are untouched and still pass**. No production code in the tasks/auth/health
  slice was modified.
- Everything in the default suite runs with **NO network, NO real LLM, NO real
  Postgres**. Legistar is served by `httpx.MockTransport`, the LLM is stubbed at
  `_synthesize`/`_call_ollama`/`_call_anthropic`, fastembed is replaced by a fake
  module, and DB logic runs against a mock psycopg connection / patched pool.

### Coverage summary (`--cov=app/civic --cov-branch`)

**99% total** — 377 statements, 0 missed; 80 branches, 1 partial.

| Module                         | Cover | Note                                                         |
|--------------------------------|-------|--------------------------------------------------------------|
| `app/civic/__init__.py`        | 100%  | package map, no statements                                   |
| `app/civic/answer.py`          | 100%  | cite-or-refuse, provider dispatch, injection fence, parsers  |
| `app/civic/db.py`              | 100%  | pool lifecycle + DDL + upsert (pool patched, no socket)      |
| `app/civic/embeddings.py`      | 100%  | fastembed load + `.tolist()` + unwrap (fake module injected) |
| `app/civic/ingest.py`          | 99%   | 1 partial branch `320->328` — provably unreachable (below)   |
| `app/civic/retrieval.py`       | 100%  | dense/lexical/fetch SQL + RRF, mocked psycopg                |
| `app/civic/routers/ask.py`     | 100%  |                                                              |
| `app/civic/routers/ingest.py`  | 100%  |                                                              |
| `app/civic/schemas.py`         | 100%  |                                                              |

The single uncovered branch is `ingest.py` `320->328`: the `for`-loop's natural
exhaustion exit in `_split_text`. It is **provably unreachable** — `step =
max(1, size - overlap) <= size`, so the final window always satisfies
`start + size >= len(text)` and hits the `break` on line 326-327 first. It is
intentional defensive code, kept (not deleted) and documented rather than gamed.

## How to run the suite

**Offline default (what CI runs — no infra):**

```bash
# From the repo root. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 keeps third-party plugins
# out; we re-enable the two we actually need by hand.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  -p pytest_cov -p hypothesis \
  --cov=app/civic --cov-branch --cov-report=term-missing -q
```

Note: with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` you MUST pass `-p pytest_cov -p
hypothesis` explicitly, or `--cov` and `@given` silently disappear. Plain
`.venv/bin/python -m pytest -q` also works if plugin autoload is left on.

**Full e2e (with live infra — runs the 4 skipped tests too):**

```bash
# 1. bring up pgvector (see docker-compose.yml -> pgvector/pgvector:pg16)
docker compose up -d db
export CIVIC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/civicscope

# 2. (optional, exercises real embedding/LLM paths in a manual smoke) local LLM
ollama serve && ollama pull llama3.1:8b

# 3. run everything; the skipif gates now see a reachable DB and execute
.venv/bin/python -m pytest -q
```

The real fastembed model download and the live Anthropic/Ollama calls are NOT
wired into an automated test; they are exercised via the manual `docs/CIVIC_SLICE.md`
run recipe.

## Civic-slice architecture + file map

```
app/
  config.py            # EXTENDED (additive civic fields): civic_database_url,
                       #   ollama_host, ollama_model, llm_provider, legistar_client,
                       #   ingest_token, anthropic_api_key, anthropic_model
  main.py              # EXTENDED: mounts the two civic routers + pool shutdown hook
  civic/
    __init__.py        # package overview / module map
    schemas.py         # CivicDocument / CivicChunk + Ask/Ingest wire models
    db.py              # Postgres + pgvector pool, schema init(), upserts
    embeddings.py      # fastembed bge-small (384-dim), lazy lru_cache singleton
    ingest.py          # Legistar fetch -> normalize -> chunk -> embed -> upsert
    retrieval.py       # dense + lexical + RRF hybrid retrieval
    answer.py          # cite-or-refuse synthesis + citation verification
    routers/
      ingest.py        # POST /civic/ingest (token-gated, 503 if no token, single-flight lock)
      ask.py           # POST /civic/ask
docs/
  CIVIC_SLICE.md       # the feature description (data model, flow, run recipe)
  CIVIC_CONTEXT.md     # this file — test context + status
docker-compose.yml     # pgvector/pgvector:pg16 service (civicscope DB)
```

Flow: Legistar Matters (Philadelphia) -> normalize -> chunk -> embed (fastembed
bge-small 384-dim) -> Postgres+pgvector -> hybrid retrieve (dense pgvector cosine
+ lexical tsvector, fused with RRF k=60) -> cite-or-refuse answer (Ollama or
Anthropic) with independent citation verification. See `docs/CIVIC_SLICE.md` for
the full data model and end-to-end walkthrough.

## Test infrastructure (decided + enforced)

| Concern             | Approach                                                                  |
|---------------------|---------------------------------------------------------------------------|
| Legistar HTTP       | `httpx.MockTransport` via the `legistar_client_factory` conftest fixture  |
| LLM synthesis       | patch `app.civic.answer._synthesize` / `_call_ollama` / `_call_anthropic` |
| Retrieval (for /ask)| patch `app.civic.answer.retrieve` (returns in-process `RetrievedChunk`s)  |
| Embeddings          | inject a fake `fastembed` module (no ONNX / no model download)            |
| DB (unit logic)     | `mock_conn` fixture (MagicMock psycopg conn/cursor); assert executed SQL  |
| DB pool lifecycle   | patched `ConnectionPool` / `get_conn`; no socket ever opened              |
| DB (integration)    | real Postgres, **gated behind `skipif` on DB availability**               |
| Config              | fresh `Settings()` + `monkeypatch.setenv`; singleton patched per-test     |
| Combinatorial       | `pytest.mark.parametrize` (enumerated) + Hypothesis (property-based)      |

Pinned in `requirements.txt`: `hypothesis==6.122.3`, `pytest-cov==6.0.0`.

Shared fixtures in `tests/conftest.py` (civic section): `make_chunk`,
`sample_chunks`, `null_file_no_chunk`, `civic_settings` (per-attr setter),
`make_matter`, `sample_matters` (6-item batch spanning every normalize/skip
branch), `legistar_client_factory`, `odata_error_body`, `civic_client` (bare
TestClient), `mock_conn`.

## Full test inventory (per file)

Totals below are **collected** counts; every one passes in isolation and in the
full run. 560 civic tests across 14 files.

| File                            | Count | What it covers                                                                                       | Gate / technique                                     |
|---------------------------------|-------|------------------------------------------------------------------------------------------------------|------------------------------------------------------|
| `test_civic_answer.py`          | 111   | cite-or-refuse, verify, provider dispatch (ollama/anthropic), grounding, injection fence, `_call_ollama`/`_call_anthropic` parsing incl. null/whitespace content -> `""`, empty/whitespace-synthesis refusal, provider-casing robustness, duplicate + null-file_no cite-key determinism, citation-regex boundaries | pure; stubbed `_synthesize`/`retrieve`, patched `httpx` + fake `anthropic`. Hypothesis |
| `test_civic_dbconfig.py`        | 132   | **Exhaustive consolidated db.py + config.py.** Pool lifecycle (`get_pool` lazy-singleton / `close_pool` idempotent-noop / recreate-after-close / `get_conn` borrow-return, reads live `settings`), full DDL contract (vector-width-drift guard, statement count, extension-before-tables), upsert column-binding surface (nullable pass-through, chunk order, None-embedding, `Json` adapter exact `.obj`, no-commit-txn-is-caller's), every config field default/env-override/type + empty-string-honored + free-text `llm_provider` + config→db conninfo tie-in, real-Postgres round-trip incl. shrinking-chunk no-orphan | `mock_conn` + patched `ConnectionPool`/`get_conn` + fresh `Settings()`; Hypothesis. **2 skipif Postgres** |
| `test_civic_retrieval.py`       | 65    | RRF fusion (enumerated + Hypothesis) + `retrieve` orchestration + the SQL retrievers `_dense`/`_lexical`/`_fetch_chunks` mock-psycopg: asserts `%s::vector` cast, `embedding IS NOT NULL`, cosine `<=>` ASC, `plainto_tsquery`/`tsv @@ q`/`ts_rank DESC`, `ANY(%s)` array bind, row→record mapping (all-null doc fields) | pure + patched retrievers + `MagicMock` cursor; Hypothesis |
| `test_civic_api.py`             | 61    | Both endpoints: 422/503/401/409/500 + success/refusal/degradation, plus Hypothesis property sweeps (never-5xx, citations ⊆ retrieved, length boundary 0..2600, empty-retrieval refuses, exception never leaks, token gate holds, lock frees) | TestClient + stubbed boundaries; Hypothesis          |
| `test_civic_ingest.py`          | 59    | fetch pagination/error-envelope/every-status/inter-page-sleep/settings-slug, normalize (all malformed cases), chunk boundaries (parametrized + Hypothesis invariants: total/non-empty/≤size/deterministic/no-Cf), upsert batching + no-chunk-skip-embed path, overlap>size correctness, orchestration skip/drop | `MockTransport` + patched embed/db; Hypothesis        |
| `test_civic_db_logic.py`        | 33    | DDL/schema string contract, `init()`, `upsert_document` control flow                                 | `mock_conn`; Hypothesis                               |
| `test_civic_config.py`          | 33    | Settings defaults, env overrides, case-insensitivity, no-fail-loud                                   | fresh `Settings()` + `setenv`; parametrize            |
| `test_civic_legistar_errors.py` | 27    | the REAL Legistar error surface: every HTTP status, non-array 200 bodies, `Retry-After`, `$orderby`/`$skip` stability, 1000-row cap | `MockTransport`                                       |
| `test_civic_endpoints.py`       | 17    | HTTP contract for both routers (parallel-window sibling of `test_civic_api.py`)                      | TestClient + stubbed boundaries                       |
| `test_civic_sql.py`             | 8     | pure-SQL retriever helpers `_dense_candidates`/`_lexical_candidates`/`_fetch_chunks` (ids, row-mapping, asserted binds) | `MagicMock` cursor, no Postgres                       |
| `test_civic_embeddings.py`      | 6     | fastembed contract without ONNX: `embed_texts` returns plain `list`s (`vec.tolist()`), `embed_query` unwraps `[0]` flat, empty-batch, `_get_model` singleton constructed once, `EMBEDDING_DIM == 384` pins `vector(384)` | fake `fastembed` module injected                     |
| `test_civic_citations.py`       | 3     | `extract_citations` / `verify_citations` pure helpers                                                | pure, `importorskip`                                  |
| `test_civic_rrf.py`             | 3     | `reciprocal_rank_fusion` pure fusion                                                                 | pure, `importorskip`                                  |
| `test_civic_db.py`              | 2     | Real pgvector schema init + upsert round-trip                                                        | **skipif** real Postgres                              |

Gated summary: **4 tests are Postgres-gated** (2 in `test_civic_db.py`, 2 in
`test_civic_dbconfig.py`); everything else is pure/offline. **No test needs a
real LLM or a network call** — the LLM and fastembed paths are always stubbed or
faked. Hypothesis property sweeps live in `answer`, `api`, `dbconfig`,
`db_logic`, `ingest`, `retrieval`, and `config`.

## Bugs fixed this pass

Across all phases, **every fix was a wrong TEST or fixture, not a source bug** —
the civic slice was already correct against every intended-behavior test. Total
production source bugs found: **0**. The load-bearing test/fixture fixes:

1. `test_civic_ingest.py::test_embeds_once_and_delegates_per_doc` — fake
   `get_conn` yielded a bare `object()` lacking `.commit()`; fixed the stub to a
   `MagicMock`. (The one-transaction-commit-once guarantee is correct source.)
2. `test_civic_endpoints.py::test_passes_question_through` — a
   `seen.setdefault(...) or AskResponse(...)` returned the truthy question string
   instead of the response, tripping `ResponseValidationError`. Rewritten as an
   explicit `fake_answer`.
3. `test_civic_retrieval.py` RRF assertions encoded a mathematically false
   premise ("matched middle wins"). For `[[1,2,3],[3,2,1]]`, k=60: id 2 scores
   `2/(k+2)=0.032258`; ids 1 and 3 each `1/(k+1)+1/(k+3)=0.032266`. Convexity of
   `1/(k+rank)` means a strong #1 outweighs a matched middle, so 1 and 3 beat 2
   (tie → id-ascending puts 1 first). Fixed the expectations; source correct.
4. `conftest.py` Legistar transport used httpx's `json=` shortcut, and
   `json=None` sends an EMPTY body (decode error) not literal JSON `null`, masking
   the source's real `isinstance(list)` guard. Fixed the transport to serialize
   with `json.dumps` (None → `"null"`) so a true null payload reaches — and is
   correctly rejected by — `fetch_matters`.
5. `test_civic_retrieval.py` SQL-retriever coverage gap: added a mocked-psycopg
   section asserting the load-bearing SQL and row-mapping; all green first run
   (regression-locking, not red→green source).
6. `test_civic_api.py` Hypothesis sweeps went red first on TEST bugs: (a) leak
   assertions used tiny random messages (`")"`,`"'"`,`":"`) that appear naturally
   in the JSON body — fixed with sentinel-prefixed secrets; (b) header strategies
   drew non-ASCII/control chars httpx rejects pre-app — restricted to
   printable-ASCII header-safe tokens. Source (`routers/*`, `main.py`) correct.
7. `test_civic_dbconfig.py` consolidated db.py+config.py: all green first run.
   Verified the red→green linkage is real by a mutation check — reordering the
   upsert DELETE after the chunk INSERTs (an orphan-leaving bug) turned the order
   and Hypothesis verb-sequence tests red; restoring the source returned them
   green. `app/civic/db.py` left byte-for-byte unmodified.

## Legistar Web API — the real error + edge surface we test against

Researched against the live Granicus/Legistar Web API (`webapi.legistar.com`,
client `phila`) and reproduced offline with `httpx.MockTransport` in
`test_civic_legistar_errors.py` (and, for normalize/field cases, in
`test_civic_ingest.py`). The happy path returns a **bare JSON array** of Matter
objects; the tables below enumerate how the real service deviates.

### HTTP status codes

| Code | Real cause                                          | Pipeline behavior (tested)                          |
|------|-----------------------------------------------------|-----------------------------------------------------|
| 400  | Malformed OData query (bad `$filter`/`$orderby`)    | `raise_for_status()` → `HTTPStatusError`, code kept |
| 401  | Client token policy rejects an unauthenticated read | `HTTPStatusError` (body is the OData error envelope) |
| 403  | Forbidden                                           | `HTTPStatusError`                                   |
| 404  | Unknown client slug (`/v1/<bad>/Matters`)           | `HTTPStatusError`                                   |
| 429  | Rate limited — may carry `Retry-After`              | `HTTPStatusError`; `Retry-After` preserved on resp  |
| 500  | Server error                                        | `HTTPStatusError`; a later-page 500 fails the whole run (no partial ingest) |
| 502/503/504 | Bad gateway / unavailable / gateway timeout | `HTTPStatusError`                                   |

### Non-array 200 bodies (the silent-corruption trap)

On trouble the service (IIS + OData v3) can answer **200** with a JSON *object*
instead of the promised array. A dict is truthy, so blindly `extend()`-ing it
would splice its string KEYS into the results and crash `normalize` later with an
opaque 500. `fetch_matters` rejects any non-array body with a typed
`ValueError("...non-list payload (<type>)...")`. Covers OData v3 verbose error,
ASP.NET/IIS `{"Message": ...}`, OData v2 `{"d":{"results":[...]}}`, OData v4
`{"value":[...]}`, bare `{}`/string/number/bool/literal `null`, and empty body
(surfaced as a JSON-decode `ValueError`).

### Pagination stability + the 1000-row cap

Query replies are capped at 1000 rows; a `page_size` above the cap comes back
short and the short-page rule stops the walk. `$skip` paging needs a total-order
`$orderby` (`MatterIntroDate desc,MatterId desc` — the `MatterId` tiebreak forces
determinism). Tested: `$orderby` value, `$skip` advancing by one page, slug in
the path, and inter-page sleep firing only after full pages (never the terminal
short page).

### Null / missing / malformed fields on real Matters (normalize)

| Field             | Real-world deviation                                    | Normalize behavior                                    |
|-------------------|---------------------------------------------------------|-------------------------------------------------------|
| `MatterName`      | routinely `null` on recent records                      | fall back to it only if `MatterTitle` empty           |
| `MatterTitle`     | `null` / `""` / non-string / HTML+entities / zero-width | coerce to str, unescape, strip tags, drop Cf chars    |
| `MatterFile`      | legitimately `null`                                     | kept `None`; citable by `source_ref`                  |
| `MatterIntroDate` | missing / `""` / `"not-a-date"` / impossible            | parse to `date` or `None`, never raise                |
| `MatterGuid`      | missing                                                 | URL falls back to the API resource URL                |
| `MatterId`        | absent on a malformed record                            | record dropped by `run_ingest` (collapses upsert key) |
| whole record      | one record raises during normalize                      | logged + skipped; rest of the page still ingests      |

## Deferred / next items

Ordered roughly by expected value. Each is a stable extension point, not a
rewrite.

1. **Auth + multi-tenancy on civic routes.** Today `/civic/ingest` is
   token-gated (503 without a token) and `/civic/ask` is fully open; there is no
   per-user or per-tenant scoping. Next slice: reuse the existing tasks/auth
   layer so civic data can be partitioned per tenant.
2. **Body-text ingest.** Only the Matter title/metadata is chunked today.
   Attachment / full-text ingestion is left as a stable extension point in the
   chunking layer (`chunk_document`) — pull the Matter's attachments/full text,
   chunk and embed them, keep `source_ref` idempotency.
3. **Jurisdiction data model for multi-city.** Scope is hardcoded to `phila`
   (`legistar_client`). Generalize to multiple Legistar clients: add a
   `jurisdiction` column/dimension to `civic_documents`, key retrieval and
   citations by it, and make `run_ingest` iterate configured clients.
4. **Background jobs / scheduler.** Ingest is a manual, gated HTTP call. Move it
   to a scheduled/queued background job so the corpus refreshes without an
   operator curl.

### Still-manual / not automated (by design)

- Real pgvector `init()` + schema round-trip and idempotent upsert
  (`test_civic_db.py`, 2 tests + 2 in `test_civic_dbconfig.py`) — need a live
  `pgvector/pgvector:pg16` (see `docker-compose.yml`) and skip cleanly otherwise.
  Their SQL text + binds are already unit-tested with a mocked cursor; only the
  behavior against a *real* pgvector index (actual `<=>`/`ts_rank` ordering over
  live data) is deferred to these gated tests.
- The real fastembed model download + a live Anthropic/Ollama call are exercised
  only via the manual `docs/CIVIC_SLICE.md` run recipe, not an automated test.
  The vector-conversion/unwrap contract itself IS covered offline via a fake
  `fastembed` module in `test_civic_embeddings.py`.

## Note: parallel-window overlap

`test_civic_api.py` and `test_civic_endpoints.py` were authored in separate
parallel windows and cover the same two endpoints with overlapping scenarios.
Both pass and neither is wrong; a future consolidation could merge them, but the
redundancy is harmless (belt-and-suspenders on the error-code contract).
Likewise `test_civic_dbconfig.py` supersedes and expands `test_civic_db_logic.py`
+ `test_civic_config.py`; the smaller files are kept as they still pass and
document the same contracts at lower resolution.
