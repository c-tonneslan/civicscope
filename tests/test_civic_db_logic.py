"""Unit tests for the civic DB layer's pure logic (NO real Postgres).

Two things are tested here without a live database:

  1. The DDL / schema constants in ``app.civic.db`` — that the vector extension,
     both tables, the generated tsvector, and both indexes are declared, that the
     embedding width matches ``EMBEDDING_DIM``, and that everything is idempotent
     (``IF NOT EXISTS``). This is a string-level contract check, not an execution.

  2. ``db.upsert_document`` control flow — driven against a MagicMock psycopg
     connection (the ``mock_conn`` fixture). We assert the ordering that makes the
     upsert idempotent AND non-orphaning: parent upsert (RETURNING id) -> DELETE
     children for that id -> INSERT each new chunk. This is the delete-then-insert
     invariant that stops a shrinking chunk set leaving stale rows.

The REAL Postgres round-trip lives in tests/test_civic_db.py behind a skipif on
DB availability; this file needs no DB at all.
"""

from __future__ import annotations

import pytest

pytest.importorskip("app.civic.db", reason="civic db deps (pgvector/psycopg) absent")

from app.civic import db  # noqa: E402
from app.civic.schemas import CivicChunk, CivicDocument  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers to read what was executed on the mock cursor
# ---------------------------------------------------------------------------


def _executed(mock_conn) -> list[str]:
    """The stripped SQL strings executed on the mock cursor, in order."""

    return [call.args[0].strip() for call in mock_conn._cur.execute.call_args_list]


def _verbs(mock_conn) -> list[str]:
    """The leading SQL verb of each executed statement, in order."""

    return [sql.split()[0].upper() for sql in _executed(mock_conn)]


def _make_doc(**over) -> CivicDocument:
    base = dict(
        source_ref="27386",
        doc_type="Ordinance",
        file_no="260633",
        title="An Ordinance",
        body_name="CITY COUNCIL",
        status="IN COMMITTEE",
        intro_date=None,
        url="https://example.test/1",
        raw={"MatterId": 27386},
    )
    base.update(over)
    return CivicDocument(**base)


def _make_chunks(n: int) -> list[CivicChunk]:
    return [
        CivicChunk(source_ref="27386", file_no="260633", chunk_index=i,
                   text=f"chunk {i}", embedding=[float(i)] * 3)
        for i in range(n)
    ]


# ===========================================================================
# Schema / DDL contract (string-level, no execution)
# ===========================================================================


def test_embedding_dim_is_384():
    # Must match the fastembed bge-small output width and the VECTOR(...) column.
    assert db.EMBEDDING_DIM == 384


def test_ddl_enables_vector_extension_first():
    # pgvector must exist before any vector(...) column is created.
    first = db._DDL_STATEMENTS[0].strip().lower()
    assert "create extension if not exists vector" in first


@pytest.mark.parametrize(
    "needle",
    [
        "create table if not exists civic_documents",
        "create table if not exists civic_chunks",
        "source_ref  text not null unique",
        "on delete cascade",
        "unique (document_id, chunk_index)",
        "tsvector generated always as",
        "create index if not exists civic_chunks_tsv_gin",
        "using gin (tsv)",
        "civic_chunks_embedding_ivfflat",
        "using ivfflat",
        "vector_cosine_ops",
    ],
)
def test_ddl_declares_expected_object(needle):
    blob = " ".join(db._DDL_STATEMENTS).lower()
    assert needle in blob


def test_vector_column_width_matches_embedding_dim():
    blob = " ".join(db._DDL_STATEMENTS).lower()
    assert f"vector({db.EMBEDDING_DIM})".lower() in blob


def test_all_ddl_statements_are_idempotent():
    # Every CREATE must be IF NOT EXISTS so init() is safe to call every startup.
    for stmt in db._DDL_STATEMENTS:
        low = stmt.strip().lower()
        assert low.startswith("create")
        assert "if not exists" in low


def test_tsv_is_generated_from_text_column():
    # The generated tsvector keeps lexical search from ever going stale.
    chunks_ddl = next(s for s in db._DDL_STATEMENTS if "civic_chunks" in s.lower()
                      and "create table" in s.lower())
    low = chunks_ddl.lower()
    assert "to_tsvector('english', coalesce(text, ''))" in low
    assert "stored" in low


# ===========================================================================
# init() drives every DDL statement then commits (mocked pool)
# ===========================================================================


def test_init_executes_all_ddl_then_commits(monkeypatch, mock_conn):
    from contextlib import contextmanager

    @contextmanager
    def fake_get_conn():
        yield mock_conn

    monkeypatch.setattr(db, "get_conn", fake_get_conn)
    db.init()

    # One execute per DDL statement, then a single commit.
    assert mock_conn._cur.execute.call_count == len(db._DDL_STATEMENTS)
    mock_conn.commit.assert_called_once()


# ===========================================================================
# upsert_document control flow (mock connection, no Postgres)
# ===========================================================================


def test_upsert_returns_document_id_from_returning_clause(mock_conn):
    mock_conn._cur.fetchone.return_value = (42,)
    doc_id = db.upsert_document(mock_conn, _make_doc(), _make_chunks(1))
    assert doc_id == 42


def test_upsert_order_is_parent_then_delete_then_inserts(mock_conn):
    db.upsert_document(mock_conn, _make_doc(), _make_chunks(2))
    verbs = _verbs(mock_conn)
    # Parent upsert, then delete stale children, then one insert per new chunk.
    assert verbs == ["INSERT", "DELETE", "INSERT", "INSERT"]


def test_upsert_deletes_children_by_returned_document_id(mock_conn):
    mock_conn._cur.fetchone.return_value = (7,)
    db.upsert_document(mock_conn, _make_doc(), _make_chunks(1))
    delete_call = next(
        c for c in mock_conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("DELETE")
    )
    # The DELETE is scoped to the surviving parent id, so a re-ingest that
    # produces FEWER chunks never orphans rows.
    assert delete_call.args[1] == (7,)


def test_upsert_with_zero_chunks_still_deletes_then_inserts_nothing(mock_conn):
    db.upsert_document(mock_conn, _make_doc(), [])
    verbs = _verbs(mock_conn)
    # Parent upsert + delete children; no chunk inserts. A document whose text
    # vanished upstream must end with zero chunks, not stale ones.
    assert verbs == ["INSERT", "DELETE"]


def test_upsert_binds_raw_via_json_adapter(mock_conn):
    # The raw dict must be bound through psycopg's Json adapter (JSONB), not
    # json.dumps — matching the ingest write path.
    from psycopg.types.json import Json

    db.upsert_document(mock_conn, _make_doc(raw={"k": "v"}), [])
    parent_call = mock_conn._cur.execute.call_args_list[0]
    bound_raw = parent_call.args[1][-1]  # raw is the last bound param
    assert isinstance(bound_raw, Json)


def test_upsert_parent_binds_all_columns_in_order(mock_conn):
    doc = _make_doc(source_ref="S", doc_type="D", file_no="F", title="T",
                    body_name="B", status="ST", intro_date=None, url="U")
    db.upsert_document(mock_conn, doc, [])
    params = mock_conn._cur.execute.call_args_list[0].args[1]
    # (source_ref, doc_type, file_no, title, body_name, status, intro_date, url, raw)
    assert params[:8] == ("S", "D", "F", "T", "B", "ST", None, "U")


def test_upsert_inserts_each_chunk_with_its_index_text_embedding(mock_conn):
    mock_conn._cur.fetchone.return_value = (5,)
    chunks = _make_chunks(3)
    db.upsert_document(mock_conn, _make_doc(), chunks)
    insert_calls = [
        c for c in mock_conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("INSERT")
        and "civic_chunks" in c.args[0].lower()
    ]
    assert len(insert_calls) == 3
    for chunk, call in zip(chunks, insert_calls):
        # (document_id, chunk_index, text, embedding)
        assert call.args[1] == (5, chunk.chunk_index, chunk.text, chunk.embedding)


@pytest.mark.parametrize("n_chunks", [0, 1, 2, 5, 25])
def test_upsert_insert_count_matches_chunk_count(mock_conn, n_chunks):
    db.upsert_document(mock_conn, _make_doc(), _make_chunks(n_chunks))
    chunk_inserts = [
        c for c in mock_conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("INSERT")
        and "civic_chunks" in c.args[0].lower()
    ]
    assert len(chunk_inserts) == n_chunks


# ===========================================================================
# Idempotent-upsert SQL contract (the ON CONFLICT clauses)
# ===========================================================================


def test_document_upsert_conflicts_on_source_ref():
    low = db._UPSERT_DOCUMENT_SQL.lower()
    assert "on conflict (source_ref) do update" in low
    assert "loaded_at  = now()" in low or "loaded_at = now()" in low


def test_chunk_insert_conflicts_on_document_id_chunk_index():
    low = db._INSERT_CHUNK_SQL.lower()
    assert "on conflict (document_id, chunk_index) do update" in low


def test_document_upsert_refreshes_every_mutable_column():
    low = db._UPSERT_DOCUMENT_SQL.lower()
    for col in ["doc_type", "file_no", "title", "body_name", "status",
                "intro_date", "url", "raw"]:
        assert f"{col}" in low and "excluded." + col in low


# ===========================================================================
# Property-based: upsert control flow holds for ANY chunk count (Hypothesis)
# ===========================================================================


from hypothesis import given, settings as hyp_settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


@hyp_settings(max_examples=40, deadline=None)
@given(n=st.integers(min_value=0, max_value=50))
def test_property_verb_sequence_is_insert_delete_then_n_inserts(n):
    from unittest.mock import MagicMock

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (1,)

    db.upsert_document(conn, _make_doc(), _make_chunks(n))

    verbs = [c.args[0].strip().split()[0].upper() for c in cur.execute.call_args_list]
    # Always: parent INSERT, then DELETE, then exactly n chunk INSERTs.
    assert verbs[0] == "INSERT"
    assert verbs[1] == "DELETE"
    assert verbs[2:] == ["INSERT"] * n
    assert len(verbs) == 2 + n
