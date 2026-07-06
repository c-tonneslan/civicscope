"""Tests for the what's-new digest + its HTTP route.

No Postgres: ``get_conn`` is replaced with a mock cursor returning canned rows,
so the SQL wiring, bound params, and row shaping are exercised without a
database. The route test stubs ``recent_activity`` at its module boundary and
drives the real FastAPI app via the ``civic_client`` fixture.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

digest = pytest.importorskip(
    "app.civic.digest",
    reason="civic deps (pgvector/psycopg) not installed",
)


def _patch_conn(monkeypatch, cur):
    """Point ``digest.get_conn`` at a context-manager conn whose cursor is ``cur``."""

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    monkeypatch.setattr(digest, "get_conn", lambda: cm)


INTRODUCED = [
    ("260633", "An ordinance", "INTRODUCED", date(2026, 6, 20)),
    ("260640", "A resolution", "INTRODUCED", date(2026, 6, 18)),
]
ENACTED = [
    ("260500", "Enacted ordinance", "ENACTED", date(2026, 5, 1), date(2026, 6, 25)),
]


# ===========================================================================
# recent_activity — shaping
# ===========================================================================


class TestRecentActivityShaping:
    def test_shapes_introduced_and_enacted(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.side_effect = [INTRODUCED, ENACTED]
        _patch_conn(monkeypatch, cur)
        out = digest.recent_activity()

        assert out["days"] == 14
        assert out["jurisdiction"] is None
        # Introduced items carry no last-action date.
        assert out["introduced"][0] == {
            "file_no": "260633",
            "title": "An ordinance",
            "status": "INTRODUCED",
            "intro_date": date(2026, 6, 20),
            "last_action_date": None,
        }
        # Enacted items carry the max action date from civic_history.
        assert out["enacted"][0]["last_action_date"] == date(2026, 6, 25)
        assert out["enacted"][0]["status"] == "ENACTED"
        assert out["enacted"][0]["file_no"] == "260500"
        assert out["enacted"][0]["intro_date"] == date(2026, 5, 1)


# ===========================================================================
# recent_activity — SQL wiring + bound params
# ===========================================================================


class TestRecentActivitySql:
    def _run(self, monkeypatch, **kwargs):
        cur = MagicMock()
        cur.fetchall.side_effect = [[], []]
        _patch_conn(monkeypatch, cur)
        digest.recent_activity(**kwargs)
        return cur

    def test_query_text(self, monkeypatch):
        cur = self._run(monkeypatch)
        intro_sql = cur.execute.call_args_list[0].args[0]
        enacted_sql = cur.execute.call_args_list[1].args[0]
        assert "intro_date >= %s" in intro_sql
        assert "ORDER BY d.intro_date DESC" in intro_sql
        assert "d.status = 'ENACTED'" in enacted_sql
        assert "max(action_date)" in enacted_sql

    def test_since_window(self, monkeypatch):
        cur = self._run(monkeypatch, days=30)
        expected = date.today() - timedelta(days=30)
        assert cur.execute.call_args_list[0].args[1][0] == expected
        assert cur.execute.call_args_list[1].args[1][0] == expected

    def test_unscoped_binds_no_slug(self, monkeypatch):
        cur = self._run(monkeypatch, limit=7)
        intro_params = cur.execute.call_args_list[0].args[1]
        # Only (since, limit) with no jurisdiction predicate.
        assert intro_params == (date.today() - timedelta(days=14), 7)
        assert "AND d.jurisdiction = %s" not in cur.execute.call_args_list[0].args[0]

    def test_jurisdiction_scoping(self, monkeypatch):
        cur = self._run(monkeypatch, jurisdiction="chicago", limit=5)
        intro_sql = cur.execute.call_args_list[0].args[0]
        intro_params = cur.execute.call_args_list[0].args[1]
        assert "AND d.jurisdiction = %s" in intro_sql
        assert intro_params == (date.today() - timedelta(days=14), "chicago", 5)

    def test_limit_is_last_param(self, monkeypatch):
        cur = self._run(monkeypatch, jurisdiction="chicago", limit=3)
        assert cur.execute.call_args_list[0].args[1][-1] == 3
        assert cur.execute.call_args_list[1].args[1][-1] == 3


# ===========================================================================
# HTTP route
# ===========================================================================


class TestRecentRoute:
    def test_recent_route_shape(self, civic_client, monkeypatch):
        monkeypatch.setattr(
            "app.civic.digest.recent_activity",
            lambda jurisdiction=None, days=14, limit=10: {
                "jurisdiction": jurisdiction,
                "days": days,
                "introduced": [{
                    "file_no": "260633",
                    "title": "An ordinance",
                    "status": "INTRODUCED",
                    "intro_date": date(2026, 6, 20),
                    "last_action_date": None,
                }],
                "enacted": [],
            },
        )
        resp = civic_client.get("/civic/insights/recent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 14
        assert body["introduced"][0]["file_no"] == "260633"
        assert body["introduced"][0]["last_action_date"] is None
        assert body["enacted"] == []

    def test_recent_route_rejects_zero_days(self, civic_client):
        resp = civic_client.get("/civic/insights/recent?days=0")
        assert resp.status_code == 422
