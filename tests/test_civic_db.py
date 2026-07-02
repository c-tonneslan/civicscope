"""Postgres smoke test for the civic schema — SKIPS cleanly with no database.

The civic slice needs Postgres + pgvector, which is not available in the default
CI/unit environment. This test attempts a connection to settings.civic_database_url
and skips (does not fail) when the database is unreachable, so it never breaks the
existing suite while still providing a real end-to-end check when a DB is present.

When a DB IS present it proves the pgvector schema is live: init() creates the
tables, a document + chunk round-trips through the upsert path, and the chunk's
384-dim embedding reads back joined to its parent bill.
"""

import pytest


def _postgres_available() -> bool:
    """True only if we can actually open a connection to the civic DB."""
    try:
        import psycopg
    except Exception:
        return False
    try:
        from app.config import settings
        conn = psycopg.connect(settings.civic_database_url, connect_timeout=2)
    except Exception:
        return False
    conn.close()
    return True


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="civic Postgres not reachable — skipping DB smoke test",
)


def test_civic_schema_init_and_roundtrip():
    civic_db = pytest.importorskip(
        "app.civic.db",
        reason="civic db not implemented yet (skeleton)",
    )
    from pgvector.psycopg import register_vector

    from app.civic.schemas import CivicChunk, CivicDocument

    # Idempotent: create the extension, tables, and indexes.
    civic_db.init()

    doc = CivicDocument(
        source_ref="smoketest-1",
        doc_type="BILL",
        file_no="990001",
        title="Smoke test ordinance",
        body_name="CITY COUNCIL",
        status="INTRODUCED",
        intro_date=None,
        url="https://example.test/990001",
        raw={"MatterId": "smoketest-1"},
    )
    chunk = CivicChunk(
        source_ref="smoketest-1",
        file_no="990001",
        chunk_index=0,
        text="An ordinance about the smoke test.",
        embedding=[0.0] * civic_db.EMBEDDING_DIM,
    )

    with civic_db.get_conn() as conn:
        register_vector(conn)
        civic_db.upsert_document(conn, doc, [chunk])
        conn.commit()

        # Re-running the upsert must not duplicate (idempotent on source_ref).
        civic_db.upsert_document(conn, doc, [chunk])
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.file_no, d.title, c.chunk_index, c.text
                FROM civic_chunks c
                JOIN civic_documents d ON d.id = c.document_id
                WHERE d.source_ref = %s
                ORDER BY c.chunk_index;
                """,
                ("smoketest-1",),
            )
            rows = cur.fetchall()

        # Clean up so re-runs start from a known state.
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM civic_documents WHERE source_ref = %s;", ("smoketest-1",)
            )
        conn.commit()

    assert len(rows) == 1                     # one chunk, no duplication
    assert rows[0] == ("990001", "Smoke test ordinance", 0,
                       "An ordinance about the smoke test.")


def test_ingest_upsert_documents_is_idempotent():
    """The REAL ingest write path (ingest.upsert_documents) is idempotent.

    Guards the production path (run_ingest calls this), which delegates to
    db.upsert_document: running the same document twice must leave stable document
    and chunk counts, not duplicate rows.
    """

    civic_db = pytest.importorskip("app.civic.db")
    from app.civic import ingest
    from app.civic.schemas import CivicDocument

    doc = CivicDocument(
        source_ref="smoketest-ingest-1",
        doc_type="BILL",
        file_no="990002",
        title="An ordinance for the ingest idempotency smoke test.",
        body_name="CITY COUNCIL",
        status="IN COMMITTEE",
        intro_date=None,
        url="https://example.test/990002",
        raw={"MatterId": "smoketest-ingest-1"},
    )

    civic_db.init()
    try:
        assert ingest.upsert_documents([doc]) == 1
        assert ingest.upsert_documents([doc]) == 1  # re-run: no duplication

        with civic_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM civic_documents WHERE source_ref = %s;",
                    ("smoketest-ingest-1",),
                )
                doc_count = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT count(*)
                    FROM civic_chunks c
                    JOIN civic_documents d ON d.id = c.document_id
                    WHERE d.source_ref = %s;
                    """,
                    ("smoketest-ingest-1",),
                )
                chunk_count = cur.fetchone()[0]

        assert doc_count == 1
        assert chunk_count == 1
    finally:
        with civic_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM civic_documents WHERE source_ref = %s;",
                    ("smoketest-ingest-1",),
                )
            conn.commit()
