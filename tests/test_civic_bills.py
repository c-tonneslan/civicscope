"""Tests for the browse listing + its HTTP route.

No Postgres: ``get_conn`` is replaced with a mock cursor returning canned rows,
so the dynamic WHERE, param binding, and pagination are exercised without a
database. Route tests stub ``list_bills`` at its module boundary.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

bills = pytest.importorskip(
    "app.civic.bills",
    reason="civic deps (pgvector/psycopg) not installed",
)


def _patch_conn(monkeypatch, cur):
    """Point ``bills.get_conn`` at a context-manager conn whose cursor is ``cur``."""

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    monkeypatch.setattr(bills, "get_conn", lambda: cm)


def _cursor(rows, total=0):
    cur = MagicMock()
    cur.fetchone.return_value = (total,)   # the COUNT(*)
    cur.fetchall.return_value = rows       # the SELECT page
    return cur


# ===========================================================================
# list_bills
# ===========================================================================


class TestListBills:
    def test_no_filters_shape(self, monkeypatch):
        rows = [("260001", "A bill", "ADOPTED", "Bill", date(2026, 6, 1))]
        _patch_conn(monkeypatch, _cursor(rows, total=1))
        out = bills.list_bills(limit=25, offset=10)
        assert out["bills"] == [{
            "file_no": "260001", "title": "A bill", "status": "ADOPTED",
            "doc_type": "Bill", "intro_date": date(2026, 6, 1),
        }]
        assert out["total"] == 1
        assert out["limit"] == 25 and out["offset"] == 10

    def test_no_filters_has_no_where(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills()
        count_sql = cur.execute.call_args_list[0].args[0]
        assert "WHERE" not in count_sql
        assert cur.execute.call_args_list[0].args[1] == ()

    def test_q_builds_ilike_with_wildcard_param(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills(q="zoning")
        sql, params = cur.execute.call_args_list[0].args
        assert "title ILIKE %s" in sql
        assert params[0] == "%zoning%"

    def test_status_predicate(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills(status="ENACTED")
        sql, params = cur.execute.call_args_list[0].args
        assert "status = %s" in sql
        assert params == ("ENACTED",)

    def test_jurisdiction_predicate(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills(jurisdiction="chicago")
        sql, params = cur.execute.call_args_list[0].args
        assert "jurisdiction = %s" in sql
        assert params == ("chicago",)

    def test_since_predicate(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills(since=date(2026, 1, 1))
        sql, params = cur.execute.call_args_list[0].args
        assert "intro_date >= %s" in sql
        assert params == (date(2026, 1, 1),)

    def test_ordering_newest_first(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills()
        select_sql = cur.execute.call_args_list[1].args[0]
        assert "ORDER BY intro_date DESC" in select_sql

    def test_limit_offset_are_last_params(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        bills.list_bills(status="ADOPTED", limit=5, offset=15)
        select_params = cur.execute.call_args_list[1].args[1]
        assert select_params == ("ADOPTED", 5, 15)

    def test_limit_clamped(self, monkeypatch):
        cur = _cursor([], total=0)
        _patch_conn(monkeypatch, cur)
        out = bills.list_bills(limit=999, offset=-4)
        assert out["limit"] == 100 and out["offset"] == 0


# ===========================================================================
# HTTP route
# ===========================================================================


class TestBillsRoute:
    def test_route_shape(self, civic_client, monkeypatch):
        monkeypatch.setattr(
            "app.civic.bills.list_bills",
            lambda *a, **k: {
                "bills": [{
                    "file_no": "260001", "title": "A bill", "status": "ADOPTED",
                    "doc_type": "Bill", "intro_date": date(2026, 6, 1),
                }],
                "total": 1, "limit": 50, "offset": 0,
            },
        )
        resp = civic_client.get("/civic/bills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["bills"][0]["file_no"] == "260001"

    def test_route_passes_filters(self, civic_client, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            "app.civic.bills.list_bills",
            lambda q, status, jurisdiction, since, limit, offset: (
                seen.update(q=q, status=status, since=since) or
                {"bills": [], "total": 0, "limit": limit, "offset": offset}
            ),
        )
        resp = civic_client.get("/civic/bills?q=zoning&status=ADOPTED&since=2026-06-01")
        assert resp.status_code == 200
        assert seen["q"] == "zoning" and seen["status"] == "ADOPTED"
        assert seen["since"] == date(2026, 6, 1)

    def test_route_rejects_bad_date(self, civic_client):
        assert civic_client.get("/civic/bills?since=not-a-date").status_code == 422

    def test_route_rejects_out_of_range_limit(self, civic_client):
        assert civic_client.get("/civic/bills?limit=0").status_code == 422
        assert civic_client.get("/civic/bills?limit=101").status_code == 422
