"""Tests for sponsor ingestion (fetch/upsert/backfill) + the sponsors insight.

No network/Postgres: httpx via MockTransport, the DB via a mock cursor.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

ingest = pytest.importorskip("app.civic.ingest")
insights = pytest.importorskip("app.civic.insights")
db = pytest.importorskip("app.civic.db")


def _sponsor_client(payload, status=200):
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


# --- fetch_sponsors ---------------------------------------------------------


class TestFetchSponsors:
    def test_parses_name_and_sequence(self):
        http = _sponsor_client([
            {"MatterSponsorName": "Councilmember Squilla", "MatterSponsorSequence": 0},
            {"MatterSponsorName": "Councilmember Gauthier", "MatterSponsorSequence": 1},
        ])
        out = ingest.fetch_sponsors("42", client="phila", http=http)
        assert out == [("Councilmember Squilla", 0), ("Councilmember Gauthier", 1)]

    def test_skips_blank_names(self):
        http = _sponsor_client([{"MatterSponsorName": "  ", "MatterSponsorSequence": 0}])
        assert ingest.fetch_sponsors("42", client="phila", http=http) == []

    def test_non_list_payload_yields_empty(self):
        http = _sponsor_client({"error": "nope"})
        assert ingest.fetch_sponsors("42", client="phila", http=http) == []

    def test_http_error_yields_empty(self):
        http = _sponsor_client([], status=500)
        assert ingest.fetch_sponsors("42", client="phila", http=http) == []


# --- upsert_sponsors --------------------------------------------------------


class TestUpsertSponsors:
    def _conn(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        conn._cur = cur
        return conn

    def test_deletes_then_inserts_each(self):
        conn = self._conn()
        n = db.upsert_sponsors(conn, 7, [("A", 0), ("B", 1)])
        assert n == 2
        sqls = [c.args[0] for c in conn._cur.execute.call_args_list]
        assert sqls[0].strip().upper().startswith("DELETE")
        assert sum("INSERT INTO civic_sponsors" in s for s in sqls) == 2

    def test_empty_still_deletes(self):
        conn = self._conn()
        assert db.upsert_sponsors(conn, 7, []) == 0
        assert conn._cur.execute.call_count == 1  # just the DELETE


# --- top_sponsors -----------------------------------------------------------


class TestTopSponsors:
    def test_unscoped_shape_and_no_topic_join(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = [("Council President Johnson", 46), ("Squilla", 25)]
        _patch_conn(monkeypatch, insights, cur)
        out = insights.top_sponsors(limit=6)
        assert out["sponsors"][0] == {"name": "Council President Johnson", "bills": 46}
        sql = cur.execute.call_args.args[0]
        assert "civic_chunks" not in sql  # no topic -> no chunk join
        assert cur.execute.call_args.args[1] == (6,)  # only the limit is bound

    def test_topic_scoped_joins_chunks_and_binds_content(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = []
        _patch_conn(monkeypatch, insights, cur)
        insights.top_sponsors(topic="affordable housing", jurisdiction="phila", limit=5)
        sql, params = cur.execute.call_args.args
        assert "JOIN civic_chunks c" in sql and "to_tsquery" in sql
        assert "d.jurisdiction = %s" in sql
        # (content, jurisdiction, limit) — content first (FROM), then filters, then limit
        assert params[0] == "affordable housing" and params[-1] == 5
        assert "phila" in params


# --- backfill_sponsors ------------------------------------------------------


class TestBackfillSponsors:
    def test_iterates_docs_and_upserts(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = [(1, "100"), (2, "200")]
        # backfill_sponsors imports get_conn/upsert_sponsors from db lazily, so patch
        # them on db; fetch_sponsors is a module-level call, so patch it on ingest.
        conn = _patch_conn(monkeypatch, db, cur)
        monkeypatch.setattr(db, "upsert_sponsors", lambda c, doc_id, sp: len(sp))
        monkeypatch.setattr(ingest, "fetch_sponsors",
                            lambda sref, **k: [("Sponsor " + sref, 0)])
        monkeypatch.setattr(ingest.time, "sleep", lambda s: None)
        n = ingest.backfill_sponsors(client="phila", jurisdiction="phila",
                                     http=MagicMock())
        assert n == 2
        assert conn.commit.called


# --- route ------------------------------------------------------------------


class TestSponsorsRoute:
    def test_sponsors_route_shape(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.top_sponsors",
                            lambda topic=None, jurisdiction=None, since=None, limit=10: {
                                "topic": topic, "jurisdiction": jurisdiction,
                                "sponsors": [{"name": "Johnson", "bills": 46}]})
        resp = civic_client.get("/civic/insights/sponsors?topic=housing")
        assert resp.status_code == 200
        assert resp.json()["sponsors"][0] == {"name": "Johnson", "bills": 46}

    def test_sponsors_route_limit_bounds(self, civic_client):
        assert civic_client.get("/civic/insights/sponsors?limit=0").status_code == 422
        assert civic_client.get("/civic/insights/sponsors?limit=999").status_code == 422
