"""Password hashing and signed session tokens for civic user accounts.

Passwords are hashed with argon2 (argon2-cffi). Session tokens are a compact
``body.signature`` pair: a base64url JSON payload (``sub`` = user id, ``exp`` =
unix expiry) signed with HMAC-SHA256 over the payload using ``settings.auth_secret``.
No third-party JWT dependency — the scheme is small enough to keep in stdlib and
verify by constant-time comparison.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from argon2 import PasswordHasher

from app.config import settings

_hasher = PasswordHasher()

# How long a session token stays valid.
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def hash_password(password: str) -> str:
    """Return an argon2 hash of ``password``."""

    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """True iff ``password`` matches ``hashed``; False on mismatch or a bad hash."""

    try:
        return _hasher.verify(hashed, password)
    except Exception:  # noqa: BLE001 - a mismatch or a malformed hash is just False
        return False


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    mac = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256)
    return _b64encode(mac.digest())


def create_token(user_id: int, now: float | None = None) -> str:
    """Issue a signed session token for ``user_id``."""

    now = time.time() if now is None else now
    payload = {"sub": user_id, "exp": int(now + TOKEN_TTL_SECONDS)}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def decode_token(token: str, now: float | None = None) -> int | None:
    """Return the user id if ``token`` is well-formed, correctly signed, and
    unexpired; otherwise None. Never raises."""

    now = time.time() if now is None else now
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_b64decode(body))
        if not isinstance(payload, dict) or payload.get("exp", 0) < now:
            return None
        sub = payload.get("sub")
        return sub if isinstance(sub, int) else None
    except Exception:  # noqa: BLE001 - any malformed token is simply invalid
        return None
