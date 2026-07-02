"""Mock-psycopg tests for the pure-SQL retriever helpers + owned-client close.

These exercise the SQL-building/param-passing/row-mapping of the DB retrievers
WITHOUT a real Postgres: the psycopg cursor is a MagicMock whose ``fetchall``
returns canned rows. We assert (a) the returned ids/records are mapped correctly
and (b) the query is parameterised with the expected binds. pgvector's
``register_vector`` is patched to a no-op so no adapter registration touches a
real connection.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

retrieval = pytest.importorskip(
    "app.civic.retrieval",
    reason="civic retrieval deps (pgvector/psycopg) not installed",
)


def _conn_with_rows(rows):
    """A MagicMock connection whose cursor.fetchall() returns ``rows``."""

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = rows
    conn._cur = cur
    return conn


class TestDenseCandidates:
    def test_returns_ids_in_row_order(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _conn_with_rows([(3,), (1,), (2,)])
        ids = retrieval._dense_candidates(conn, [0.0] * 384, 20)
        assert ids == [3, 1, 2]

    def test_binds_vector_and_limit(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        vec = [0.1] * 384
        conn = _conn_with_rows([(1,)])
        retrieval._dense_candidates(conn, vec, 7)
        sql, params = conn._cur.execute.call_args[0]
        assert "<=>" in sql and "%s::vector" in sql
        assert params == (vec, 7)

    def test_empty_result_empty_list(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _conn_with_rows([])
        assert retrieval._dense_candidates(conn, [0.0] * 384, 20) == []


class TestLexicalCandidates:
    def test_returns_ids_in_row_order(self):
        conn = _conn_with_rows([(9,), (8,)])
        assert retrieval._lexical_candidates(conn, "trash pickup", 20) == [9, 8]

    def test_binds_query_and_limit(self):
        conn = _conn_with_rows([(1,)])
        retrieval._lexical_candidates(conn, "trash pickup", 5)
        sql, params = conn._cur.execute.call_args[0]
        assert "plainto_tsquery" in sql and "ts_rank" in sql
        assert params == ("trash pickup", 5)


class TestFetchChunks:
    def test_empty_ids_short_circuits_without_query(self):
        conn = MagicMock()
        assert retrieval._fetch_chunks(conn, []) == {}
        conn.cursor.assert_not_called()

    def test_maps_rows_to_records(self):
        rows = [
            (1, "27386", "260633", "Ord X", 0, "body one",
             "Ordinance", "IN COMMITTEE", date(2026, 6, 11)),
            (2, "27400", None, "Comm Y", 0, "body two",
             "Communication", "PLACED ON FILE", None),
        ]
        conn = _conn_with_rows(rows)
        by_id = retrieval._fetch_chunks(conn, [1, 2])
        assert set(by_id) == {1, 2}
        assert by_id[1].file_no == "260633"
        assert by_id[1].status == "IN COMMITTEE"
        assert by_id[1].intro_date == date(2026, 6, 11)
        assert by_id[2].file_no is None
        assert by_id[2].source_ref == "27400"

    def test_binds_id_array(self):
        conn = _conn_with_rows([])
        retrieval._fetch_chunks(conn, [5, 6, 7])
        sql, params = conn._cur.execute.call_args[0]
        assert "ANY(%s)" in sql
        assert params == ([5, 6, 7],)
