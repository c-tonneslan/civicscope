"""Tests for the server-side watchlist router and its DB helpers.

No Postgres: the DB layer is mocked. Real HMAC tokens (via app.civic.auth) are
used so the bearer-token scoping is actually exercised. Every op must be scoped
to the token's user id — there is no client-supplied id anywhere to spoof.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

auth = pytest.importorskip("app.civic.auth")
db = pytest.importorskip("app.civic.db")


def _patch_conn(monkeypatch):
    conn = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    monkeypatch.setattr("app.civic.db.get_conn", lambda: cm)
    return conn


def _bearer(uid: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_token(uid)}"}


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_with_valid_token_returns_topics(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.list_watchlist",
                            lambda conn, uid: ["Transit", "Zoning & Land Use"])
        resp = civic_client.get("/civic/watchlist/", headers=_bearer(7))
        assert resp.status_code == 200
        assert resp.json() == {"topics": ["Transit", "Zoning & Land Use"]}

    def test_get_missing_header_401(self, civic_client):
        assert civic_client.get("/civic/watchlist/").status_code == 401

    def test_get_bad_token_401(self, civic_client):
        resp = civic_client.get("/civic/watchlist/",
                                headers={"Authorization": "Bearer nonsense"})
        assert resp.status_code == 401


class TestPost:
    def test_post_adds_then_returns_refreshed_list(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.add_watchlist", lambda conn, uid, topic: None)
        monkeypatch.setattr("app.civic.db.list_watchlist",
                            lambda conn, uid: ["Transit", "Housing"])
        resp = civic_client.post("/civic/watchlist/", headers=_bearer(7),
                                 json={"topic": "Housing"})
        assert resp.status_code == 200
        assert resp.json() == {"topics": ["Transit", "Housing"]}

    def test_post_missing_header_401(self, civic_client):
        resp = civic_client.post("/civic/watchlist/", json={"topic": "Housing"})
        assert resp.status_code == 401

    def test_post_bad_token_401(self, civic_client):
        resp = civic_client.post("/civic/watchlist/",
                                 headers={"Authorization": "Bearer nope"},
                                 json={"topic": "Housing"})
        assert resp.status_code == 401

    @pytest.mark.parametrize("topic", ["", "   ", "\t\n"])
    def test_post_blank_topic_422(self, civic_client, monkeypatch, topic):
        _patch_conn(monkeypatch)
        resp = civic_client.post("/civic/watchlist/", headers=_bearer(7),
                                 json={"topic": topic})
        assert resp.status_code == 422


class TestDelete:
    def test_delete_returns_refreshed_list(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.remove_watchlist", lambda conn, uid, topic: None)
        monkeypatch.setattr("app.civic.db.list_watchlist", lambda conn, uid: ["Transit"])
        resp = civic_client.delete("/civic/watchlist/?topic=Housing", headers=_bearer(7))
        assert resp.status_code == 200
        assert resp.json() == {"topics": ["Transit"]}

    def test_delete_missing_header_401(self, civic_client):
        assert civic_client.delete("/civic/watchlist/?topic=Housing").status_code == 401

    def test_delete_bad_token_401(self, civic_client):
        resp = civic_client.delete("/civic/watchlist/?topic=Housing",
                                   headers={"Authorization": "Bearer bad"})
        assert resp.status_code == 401


class TestScopedToBearerUser:
    """The user id passed to every helper must be the token's id, never a client
    value — there is deliberately no client id field to supply."""

    def test_get_scopes_to_token_user(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        seen: list[int] = []
        monkeypatch.setattr("app.civic.db.list_watchlist",
                            lambda conn, uid: seen.append(uid) or [])
        civic_client.get("/civic/watchlist/", headers=_bearer(31))
        assert seen == [31]

    def test_post_scopes_to_token_user(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        seen: list[int] = []
        monkeypatch.setattr("app.civic.db.add_watchlist",
                            lambda conn, uid, topic: seen.append(uid))
        monkeypatch.setattr("app.civic.db.list_watchlist", lambda conn, uid: [])
        civic_client.post("/civic/watchlist/", headers=_bearer(99),
                          json={"topic": "Housing"})
        assert seen == [99]

    def test_delete_scopes_to_token_user(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        seen: list[int] = []
        monkeypatch.setattr("app.civic.db.remove_watchlist",
                            lambda conn, uid, topic: seen.append(uid))
        monkeypatch.setattr("app.civic.db.list_watchlist", lambda conn, uid: [])
        civic_client.delete("/civic/watchlist/?topic=Housing", headers=_bearer(42))
        assert seen == [42]


# ---------------------------------------------------------------------------
# DB-layer SQL contract (mock conn, no Postgres)
# ---------------------------------------------------------------------------


def _fresh_mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [("Transit",), ("Housing",)]
    conn._cur = cur
    return conn


class TestDbHelpers:
    def test_list_selects_by_user_ordered(self):
        conn = _fresh_mock_conn()
        assert db.list_watchlist(conn, 7) == ["Transit", "Housing"]
        sql, params = conn._cur.execute.call_args.args
        low = sql.lower()
        assert "select topic from civic_watchlist where user_id = %s" in low
        assert "order by created_at, id" in low
        assert params == (7,)

    def test_add_inserts_on_conflict_do_nothing(self):
        conn = _fresh_mock_conn()
        db.add_watchlist(conn, 7, "Housing")
        sql, params = conn._cur.execute.call_args.args
        low = sql.lower()
        assert "insert into civic_watchlist (user_id, topic) values (%s, %s)" in low
        assert "on conflict (user_id, topic) do nothing" in low
        assert params == (7, "Housing")

    def test_remove_deletes_by_user_and_topic(self):
        conn = _fresh_mock_conn()
        db.remove_watchlist(conn, 7, "Housing")
        sql, params = conn._cur.execute.call_args.args
        low = sql.lower()
        assert "delete from civic_watchlist where user_id = %s and topic = %s" in low
        assert params == (7, "Housing")

    def test_helpers_do_not_commit(self):
        # The router owns the transaction; helpers must not commit.
        conn = _fresh_mock_conn()
        db.add_watchlist(conn, 7, "Housing")
        db.remove_watchlist(conn, 7, "Housing")
        db.list_watchlist(conn, 7)
        conn.commit.assert_not_called()
