"""Civic user accounts: POST /civic/auth/signup, /login, and GET /me.

Signup/login return a signed session token (see app.civic.auth); /me resolves the
``Authorization: Bearer <token>`` header back to the user. Thin — hashing/token
logic lives in app.civic.auth, storage in app.civic.db.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.civic.schemas import LoginRequest, SignupRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/civic/auth")


def current_user_id(authorization: str | None) -> int:
    """Resolve a ``Bearer`` token to a user id, or raise 401."""

    from app.civic.auth import decode_token

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    user_id = decode_token(token.strip())
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user_id


@router.post("/signup", response_model=TokenResponse)
def signup(req: SignupRequest) -> TokenResponse:
    """Register a new account and return a session token; 409 if email is taken."""

    from app.civic.auth import create_token, hash_password
    from app.civic.db import create_user, get_conn

    with get_conn() as conn:
        user_id = create_user(conn, req.email, hash_password(req.password))
        conn.commit()
    if user_id is None:
        raise HTTPException(status_code=409, detail="email already registered")
    return TokenResponse(token=create_token(user_id))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    """Return a session token for valid credentials, else 401.

    The same 401 is returned whether the email is unknown or the password is
    wrong, so the endpoint doesn't reveal which emails are registered.
    """

    from app.civic.auth import create_token, verify_password
    from app.civic.db import get_conn, get_user_by_email

    with get_conn() as conn:
        row = get_user_by_email(conn, req.email)
    if row is None or not verify_password(req.password, row[2]):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return TokenResponse(token=create_token(row[0]))


@router.get("/me", response_model=UserResponse)
def me(authorization: str | None = Header(default=None)) -> UserResponse:
    """Return the account for the bearer token."""

    from app.civic.db import get_conn, get_user_by_id

    user_id = current_user_id(authorization)
    with get_conn() as conn:
        row = get_user_by_id(conn, user_id)
    if row is None:
        raise HTTPException(status_code=401, detail="user not found")
    return UserResponse(id=row[0], email=row[1])
