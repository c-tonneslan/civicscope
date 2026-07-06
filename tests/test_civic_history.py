"""Tests for action-history ingestion + the timeline/velocity insights.

No network/Postgres: httpx via MockTransport, DB via a mock cursor.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

ingest = pytest.importorskip("app.civic.ingest")
insights = pytest.importorskip("app.civic.insights")
db = pytest.importorskip("app.civic.db")


def _history_client(payload, status=200):
    import json as _json

    import httpx

    def handler(request):
        return httpx.Response(status, content=_json.dumps(payload),
                              headers={"content-type": "application/json"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _patch_conn(monkeypatch, module, cur):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    monkeypatch.setattr(module, "get_conn", lambda: cm)
    return conn


class TestFetchHistory:
    def test_parses_entries_with_seq(self):
        http = _history_client([
            {"MatterHistoryActionName": "Introduced and Referred",
             "MatterHistoryActionDate": "2026-05-28T00:00:00",
             "MatterHistoryPassedFlagName": None},
            {"MatterHistoryActionName": "HEARING HELD",
             "MatterHistoryActionDate": "2026-06-03T00:00:00",
             "MatterHistoryPassedFlagName": "Pass"},
        ])
        out = ingest.fetch_history("42", client="phila", http=http)
        assert out[0] == (0, date(2026, 5, 28), "Introduced and Referred", None)
        assert out[1] == (1, date(2026, 6, 3), "HEARING HELD", "Pass")

    def test_blank_action_and_bad_date_tolerated(self):
        http = _history_client([
            {"MatterHistoryActionName": "  ", "MatterHistoryActionDate": "not-a-date"},
        ])
        out = ingest.fetch_history("42", client="phila", http=http)
        assert out == [(0, None, None, None)]

    def test_non_list_and_http_error_yield_empty(self):
        assert ingest.fetch_history("42", client="phila",
                                    http=_history_client({"e": 1})) == []
        assert ingest.fetch_history("42", client="phila",
                                    http=_history_client([], status=500)) == []


class TestUpsertHistory:
    def _conn(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        conn._cur = conn.cursor.return_value.__enter__.return_value
        return conn

    def test_deletes_then_inserts(self):
        conn = self._conn()
        n = db.upsert_history(conn, 7, [(0, date(2026, 1, 1), "Introduced", None),
                                        (1, date(2026, 2, 1), "Enacted", "Pass")])
        assert n == 2
        sqls = [c.args[0] for c in conn._cur.execute.call_args_list]
        assert sqls[0].strip().upper().startswith("DELETE")
        assert sum("INSERT INTO civic_history" in s for s in sqls) == 2


class TestBillTimeline:
    def test_found_bill_returns_sorted_timeline(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.return_value = (5, "phila", "An Ordinance", "ENACTED", "http://x")
        cur.fetchall.return_value = [
            (date(2026, 5, 28), "Introduced", None),
            (date(2026, 6, 4), "Enacted", "Pass"),
        ]
        _patch_conn(monkeypatch, insights, cur)
        out = insights.bill_timeline("260564", "phila")
        assert out["found"] is True and out["status"] == "ENACTED"
        assert out["timeline"][0]["action"] == "Introduced"

    def test_missing_bill_returns_not_found(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.return_value = None
        _patch_conn(monkeypatch, insights, cur)
        out = insights.bill_timeline("999999")
        assert out["found"] is False and out["timeline"] == []


class TestVelocity:
    def test_shapes_metrics(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.return_value = (60, 44)
        _patch_conn(monkeypatch, insights, cur)
        out = insights.legislative_velocity("phila")
        assert out == {"jurisdiction": "phila", "enacted": 60, "avg_days_to_enact": 44}

    def test_none_avg_when_empty(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.return_value = (0, None)
        _patch_conn(monkeypatch, insights, cur)
        out = insights.legislative_velocity()
        assert out["enacted"] == 0 and out["avg_days_to_enact"] is None


class TestHistoryRoutes:
    def test_timeline_route(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.bill_timeline",
                            lambda file_no, jurisdiction=None: {
                                "file_no": file_no, "found": True,
                                "jurisdiction": jurisdiction, "title": "t",
                                "status": "ENACTED", "url": "u",
                                "timeline": [{"action_date": None, "action": "X",
                                              "passed": None}]})
        resp = civic_client.get("/civic/insights/timeline?file_no=260564")
        assert resp.status_code == 200
        assert resp.json()["found"] is True

    def test_timeline_requires_file_no(self, civic_client):
        assert civic_client.get("/civic/insights/timeline").status_code == 422

    def test_velocity_route(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.legislative_velocity",
                            lambda jurisdiction=None, since=None: {
                                "jurisdiction": jurisdiction, "enacted": 60,
                                "avg_days_to_enact": 44})
        resp = civic_client.get("/civic/insights/velocity?jurisdiction=phila")
        assert resp.status_code == 200
        assert resp.json()["avg_days_to_enact"] == 44
