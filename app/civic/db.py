"""Civic Postgres + pgvector data access: pool, schema ``init()``, upserts.

This is the civic slice's OWN database layer. It is entirely separate from the
existing ``app.db`` (SQLite tasks/users) — different engine (Postgres via
psycopg 3 + a small connection pool), different tables, different connection
string (``settings.civic_database_url``). The two never share a connection.

Adapted from AwardGuard's ``backend/app/db.py``. Key adaptations:
  * connection string comes from ``settings.civic_database_url``;
  * the single ``sections`` table becomes TWO tables: ``civic_documents`` (one
    row per Legistar Matter) and ``civic_chunks`` (embeddable units, FK to a
    document), because civic text is chunked rather than stored whole.

Lazy pool: the module-level pool starts as None and is only constructed on the
first ``get_pool()`` call, so importing this module never opens a socket. That
is what lets the test suite import the app with no Postgres running.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Sequence

import psycopg
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from app.config import settings

# Embedding dimension for BAAI/bge-small-en-v1.5 (ONNX). MUST match the fastembed
# model in embeddings.py and the VECTOR(...) column width in init().
EMBEDDING_DIM = 384


# ---------------------------------------------------------------------------
# Connection pool (lazy singleton)
# ---------------------------------------------------------------------------

# Module-level pool that is NOT created at import time: the singleton starts as
# None and is only constructed on the first ``get_pool()`` call. That lazy
# construction is what lets the test suite import the app without a live civic
# database. The pool is opened eagerly on creation, so its worker threads must be
# torn down via ``close_pool()`` on shutdown.
_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Return the process-wide civic connection pool, creating it on first use."""

    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.civic_database_url,
            min_size=1,
            max_size=10,
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Close the process-wide pool and drop the singleton.

    Called from the FastAPI lifespan shutdown. The pool spawns background worker
    threads on open; without this they leak past teardown.
    """

    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Context manager yielding a pooled connection (returned to the pool on exit)."""

    pool = get_pool()
    with pool.connection() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# DDL is split into discrete statements so each runs (and is idempotent) on its
# own. Timestamps are owned by the DB layer (DEFAULT now()), matching the repo
# convention that the persistence layer stamps rows.
_DDL_STATEMENTS = [
    # 1. Enable pgvector. Must come before any vector(...) column is created.
    "CREATE EXTENSION IF NOT EXISTS vector;",
    # 2. One row per Legistar Matter. ``source_ref`` (MatterId) is UNIQUE — the
    #    idempotent upsert key. The full original record is kept in ``raw`` JSONB.
    """
    CREATE TABLE IF NOT EXISTS civic_documents (
        id          BIGSERIAL PRIMARY KEY,
        source_ref  TEXT NOT NULL UNIQUE,           -- Legistar MatterId (upsert key)
        doc_type    TEXT,
        file_no     TEXT,
        title       TEXT,
        body_name   TEXT,
        status      TEXT,
        intro_date  DATE,
        url         TEXT,
        raw         JSONB NOT NULL,
        loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    # 3. One row per embeddable unit. ``tsv`` is a GENERATED column maintained by
    #    Postgres from ``text`` so lexical search never goes stale. Chunks are
    #    ON DELETE CASCADE from their parent document.
    f"""
    CREATE TABLE IF NOT EXISTS civic_chunks (
        id          BIGSERIAL PRIMARY KEY,
        document_id BIGINT NOT NULL REFERENCES civic_documents(id) ON DELETE CASCADE,
        chunk_index INT NOT NULL,
        text        TEXT NOT NULL,
        embedding   VECTOR({EMBEDDING_DIM}),
        tsv         TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(text, ''))
                    ) STORED,
        UNIQUE (document_id, chunk_index)
    );
    """,
    # 4. GIN index for fast lexical (full-text) search over tsv.
    "CREATE INDEX IF NOT EXISTS civic_chunks_tsv_gin ON civic_chunks USING gin (tsv);",
    # 5. IVFFlat index for approximate cosine nearest-neighbour over embeddings.
    #    vector_cosine_ops => distances are cosine; lists=100 is fine at this scale.
    "CREATE INDEX IF NOT EXISTS civic_chunks_embedding_ivfflat "
    "ON civic_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);",
]


def init() -> None:
    """Create the pgvector extension, both civic tables, and their indexes.

    Idempotent (``IF NOT EXISTS`` everywhere) and safe to call on every startup.
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            for stmt in _DDL_STATEMENTS:
                cur.execute(stmt)
        conn.commit()


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------

_UPSERT_DOCUMENT_SQL = """
    INSERT INTO civic_documents
        (source_ref, doc_type, file_no, title, body_name, status, intro_date, url, raw)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (source_ref) DO UPDATE SET
        doc_type   = EXCLUDED.doc_type,
        file_no    = EXCLUDED.file_no,
        title      = EXCLUDED.title,
        body_name  = EXCLUDED.body_name,
        status     = EXCLUDED.status,
        intro_date = EXCLUDED.intro_date,
        url        = EXCLUDED.url,
        raw        = EXCLUDED.raw,
        loaded_at  = now()
    RETURNING id;
"""

_INSERT_CHUNK_SQL = """
    INSERT INTO civic_chunks (document_id, chunk_index, text, embedding)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (document_id, chunk_index) DO UPDATE SET
        text      = EXCLUDED.text,
        embedding = EXCLUDED.embedding;
"""


def upsert_document(conn, doc, chunks: Sequence) -> int:
    """Idempotently upsert one document + its chunks on ``source_ref``.

    ``doc`` is a ``CivicDocument`` and ``chunks`` a sequence of ``CivicChunk``
    with embeddings already populated. The parent is upserted first (returning
    its surviving id), then the children are refreshed: any pre-existing chunks
    for the document are deleted so a re-ingest that produces FEWER chunks does
    not leave stale rows behind, then the new chunks are inserted. Callers must
    have ``register_vector(conn)`` active so pgvector adapts the embeddings.

    Returns the document's primary key id.
    """

    with conn.cursor() as cur:
        cur.execute(
            _UPSERT_DOCUMENT_SQL,
            (
                doc.source_ref,
                doc.doc_type,
                doc.file_no,
                doc.title,
                doc.body_name,
                doc.status,
                doc.intro_date,
                doc.url,
                # Bind the dict via psycopg's Json adapter (not json.dumps) so the
                # raw record is sent as JSONB, matching the ingest write path.
                Json(doc.raw),
            ),
        )
        document_id = cur.fetchone()[0]

        # Delete-then-insert children so a shrinking chunk set never orphans rows.
        cur.execute("DELETE FROM civic_chunks WHERE document_id = %s;", (document_id,))
        for chunk in chunks:
            cur.execute(
                _INSERT_CHUNK_SQL,
                (document_id, chunk.chunk_index, chunk.text, chunk.embedding),
            )

    return document_id
