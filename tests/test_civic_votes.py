"""Tests for roll-call vote ingestion + the rollcall/member insights.

No network/Postgres: httpx via MockTransport, DB via a mock cursor.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

ingest = pytest.importorskip("app.civic.ingest")
insights = pytest.importorskip("app.civic.insights")
db = pytest.importorskip("app.civic.db")


def _route_client(routes):
    """MockTransport dispatching by URL-path suffix -> JSON payload."""
    import json as _json

    import httpx

    def handler(request):
        for suffix, payload in routes.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, content=_json.dumps(payload),
                                      headers={"content-type": "application/json"})
        return httpx.Response(404, content="[]")

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


class TestFetchVotes:
    def test_parses_person_and_value(self):
        http = _route_client({"/Votes": [
            {"VotePersonName": "Councilmember Bass", "VoteValueName": "Ayes"},
            {"VotePersonName": "Councilmember Jones", "VoteValueName": "Nays"},
        ]})
        out = ingest.fetch_votes(863905, client="phila", http=http)
        assert out == [("Councilmember Bass", "Ayes"), ("Councilmember Jones", "Nays")]

    def test_error_yields_empty(self):
        http = _route_client({})  # everything 404s
        assert ingest.fetch_votes(1, client="phila", http=http) == []


class TestFetchBillVotes:
    def test_only_voted_actions_pull_rollcall(self):
        http = _route_client({
            "/Histories": [
                {"MatterHistoryId": 111, "MatterHistoryPassedFlagName": None,
                 "MatterHistoryActionName": "Introduced",
                 "MatterHistoryActionDate": "2026-05-01T00:00:00"},
                {"MatterHistoryId": 222, "MatterHistoryPassedFlagName": "Pass",
                 "MatterHistoryActionName": "READ AND PASSED",
                 "MatterHistoryActionDate": "2026-06-04T00:00:00"},
            ],
            "/Votes": [{"VotePersonName": "CM Bass", "VoteValueName": "Ayes"}],
        })
        out = ingest.fetch_bill_votes("27316", client="phila", http=http)
        # Only the passed action (222) contributes a vote row.
        assert out == [(222, date(2026, 6, 4), "READ AND PASSED", "CM Bass", "Ayes")]


class TestUpsertVotes:
    def test_deletes_then_inserts(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        n = db.upsert_votes(conn, 7, [
            (222, date(2026, 6, 4), "READ AND PASSED", "CM Bass", "Ayes"),
            (222, date(2026, 6, 4), "READ AND PASSED", "CM Jones", "Nays"),
        ])
        assert n == 2
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert sqls[0].strip().upper().startswith("DELETE")
        assert sum("INSERT INTO civic_votes" in s for s in sqls) == 2


class TestBillRollcall:
    def test_returns_votes_and_tally(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (5, "An Ordinance"),                       # document lookup
            (222, "READ AND PASSED", date(2026, 6, 4)),  # latest vote action
        ]
        cur.fetchall.return_value = [("CM Bass", "Ayes"), ("CM Jones", "Nays"),
                                     ("CM Ahmad", "Ayes")]
        _patch_conn(monkeypatch, insights, cur)
        out = insights.bill_rollcall("260564", "phila")
        assert out["found"] is True
        assert out["tally"] == {"Ayes": 2, "Nays": 1}
        assert len(out["votes"]) == 3

    def test_no_votes_recorded(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.side_effect = [(5, "An Ordinance"), None]  # bill found, no votes
        _patch_conn(monkeypatch, insights, cur)
        out = insights.bill_rollcall("260564")
        assert out["found"] is True and out["votes"] == [] and out["tally"] == {}

    def test_missing_bill(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.side_effect = [None]
        _patch_conn(monkeypatch, insights, cur)
        assert insights.bill_rollcall("999999")["found"] is False


class TestMemberRecord:
    def test_counts_by_vote_value(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = [("Ayes", 240), ("Nays", 3)]
        _patch_conn(monkeypatch, insights, cur)
        out = insights.member_record("Councilmember Gauthier", jurisdiction="phila")
        assert out["record"] == [{"vote": "Ayes", "bills": 240},
                                 {"vote": "Nays", "bills": 3}]
        # no topic -> no chunk join, person is the first bound param
        sql, params = cur.execute.call_args.args
        assert "civic_chunks" not in sql
        assert params[0] == "Councilmember Gauthier"

    def test_topic_scoped_binds_content_first(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = []
        _patch_conn(monkeypatch, insights, cur)
        insights.member_record("CM Gauthier", topic="housing", jurisdiction="phila")
        sql, params = cur.execute.call_args.args
        assert "JOIN civic_chunks c" in sql
        # (content, person, jurisdiction)
        assert params[0] == "housing" and params[1] == "CM Gauthier"


class TestVoteRoutes:
    def test_rollcall_route(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.bill_rollcall",
                            lambda file_no, jurisdiction=None: {
                                "file_no": file_no, "found": True, "title": "t",
                                "action": "READ AND PASSED", "action_date": None,
                                "tally": {"Ayes": 17}, "votes": [
                                    {"person": "CM Bass", "vote": "Ayes"}]})
        resp = civic_client.get("/civic/insights/rollcall?file_no=260564")
        assert resp.status_code == 200
        assert resp.json()["tally"] == {"Ayes": 17}

    def test_member_route(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.member_record",
                            lambda person, topic=None, jurisdiction=None: {
                                "person": person, "topic": topic,
                                "jurisdiction": jurisdiction,
                                "record": [{"vote": "Ayes", "bills": 240}]})
        resp = civic_client.get("/civic/insights/member?person=CM%20Gauthier&topic=housing")
        assert resp.status_code == 200
        assert resp.json()["record"][0]["bills"] == 240

    def test_rollcall_requires_file_no(self, civic_client):
        assert civic_client.get("/civic/insights/rollcall").status_code == 422

    def test_member_requires_person(self, civic_client):
        assert civic_client.get("/civic/insights/member").status_code == 422
