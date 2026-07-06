"""Tests for civic user accounts: password hashing, session tokens, and routes.

No Postgres: the DB layer is mocked. argon2 hashing + HMAC token signing run for
real so the security-critical paths are actually exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

auth = pytest.importorskip("app.civic.auth")


# ---------------------------------------------------------------------------
# password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_verify_round_trip(self):
        h = auth.hash_password("correct horse battery")
        assert h != "correct horse battery"  # actually hashed
        assert auth.verify_password("correct horse battery", h) is True

    def test_wrong_password_rejected(self):
        h = auth.hash_password("secret-one")
        assert auth.verify_password("secret-two", h) is False

    def test_bad_hash_rejected_not_raised(self):
        assert auth.verify_password("whatever", "not-a-valid-argon2-hash") is False


# ---------------------------------------------------------------------------
# session tokens
# ---------------------------------------------------------------------------


class TestTokens:
    def test_round_trip(self):
        token = auth.create_token(42)
        assert auth.decode_token(token) == 42

    def test_tampered_signature_rejected(self):
        token = auth.create_token(42)
        body, _sig = token.split(".", 1)
        assert auth.decode_token(f"{body}.deadbeef") is None

    def test_tampered_body_rejected(self):
        # Re-sign nothing: flip the body but keep the old signature.
        token = auth.create_token(42)
        _body, sig = token.split(".", 1)
        assert auth.decode_token(f"AAAA.{sig}") is None

    def test_expired_token_rejected(self):
        past = 1_000_000.0
        token = auth.create_token(42, now=past)
        # a year later the token has long expired
        assert auth.decode_token(token, now=past + 400 * 24 * 3600) is None

    def test_unexpired_token_accepted(self):
        past = 1_000_000.0
        token = auth.create_token(42, now=past)
        assert auth.decode_token(token, now=past + 60) == 42

    @pytest.mark.parametrize("bad", ["", "nodot", "a.b.c", "...", "x."])
    def test_malformed_tokens_return_none(self, bad):
        assert auth.decode_token(bad) is None


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _patch_conn(monkeypatch):
    conn = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    monkeypatch.setattr("app.civic.db.get_conn", lambda: cm)
    return conn


class TestSignup:
    def test_signup_returns_valid_token(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.create_user", lambda conn, email, ph: 7)
        resp = civic_client.post("/civic/auth/signup",
                                 json={"email": "A@Example.com", "password": "password123"})
        assert resp.status_code == 200
        assert auth.decode_token(resp.json()["token"]) == 7

    def test_duplicate_email_409(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.create_user", lambda conn, email, ph: None)
        resp = civic_client.post("/civic/auth/signup",
                                 json={"email": "a@b.com", "password": "password123"})
        assert resp.status_code == 409

    @pytest.mark.parametrize("body", [
        {"email": "a@b.com", "password": "short"},     # < 8 chars
        {"email": "not-an-email", "password": "password123"},
        {"email": "a@b.com"},                          # missing password
        {"password": "password123"},                   # missing email
    ])
    def test_validation_422(self, civic_client, body):
        assert civic_client.post("/civic/auth/signup", json=body).status_code == 422


class TestLogin:
    def test_login_ok_returns_token(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        h = auth.hash_password("password123")
        monkeypatch.setattr("app.civic.db.get_user_by_email",
                            lambda conn, email: (7, "a@b.com", h))
        resp = civic_client.post("/civic/auth/login",
                                 json={"email": "a@b.com", "password": "password123"})
        assert resp.status_code == 200
        assert auth.decode_token(resp.json()["token"]) == 7

    def test_unknown_email_401(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.get_user_by_email", lambda conn, email: None)
        resp = civic_client.post("/civic/auth/login",
                                 json={"email": "a@b.com", "password": "password123"})
        assert resp.status_code == 401

    def test_wrong_password_401(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        h = auth.hash_password("the-right-one")
        monkeypatch.setattr("app.civic.db.get_user_by_email",
                            lambda conn, email: (7, "a@b.com", h))
        resp = civic_client.post("/civic/auth/login",
                                 json={"email": "a@b.com", "password": "the-wrong-one"})
        assert resp.status_code == 401


class TestMe:
    def test_me_with_valid_token(self, civic_client, monkeypatch):
        _patch_conn(monkeypatch)
        monkeypatch.setattr("app.civic.db.get_user_by_id",
                            lambda conn, uid: (7, "a@b.com"))
        token = auth.create_token(7)
        resp = civic_client.get("/civic/auth/me",
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == {"id": 7, "email": "a@b.com"}

    def test_me_missing_header_401(self, civic_client):
        assert civic_client.get("/civic/auth/me").status_code == 401

    def test_me_bad_token_401(self, civic_client):
        resp = civic_client.get("/civic/auth/me",
                                headers={"Authorization": "Bearer nonsense"})
        assert resp.status_code == 401
