"""Server-side watchlist: GET/POST/DELETE /civic/watchlist.

Every operation is scoped to the bearer-token user resolved by
``current_user_id`` — there is no client-supplied user id anywhere, so a caller
can only ever read or mutate their own topics.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Query

from app.civic.routers.auth import current_user_id
from app.civic.schemas import WatchlistAddRequest, WatchlistResponse

router = APIRouter(prefix="/civic/watchlist")


@router.get("/", response_model=WatchlistResponse)
def get_watchlist(authorization: str | None = Header(default=None)) -> WatchlistResponse:
    """Return the caller's tracked topics."""

    from app.civic.db import get_conn, list_watchlist

    user_id = current_user_id(authorization)
    with get_conn() as conn:
        return WatchlistResponse(topics=list_watchlist(conn, user_id))


@router.post("/", response_model=WatchlistResponse)
def add_topic(
    req: WatchlistAddRequest, authorization: str | None = Header(default=None)
) -> WatchlistResponse:
    """Add a topic and return the refreshed list."""

    from app.civic.db import add_watchlist, get_conn, list_watchlist

    user_id = current_user_id(authorization)
    with get_conn() as conn:
        add_watchlist(conn, user_id, req.topic)
        conn.commit()
        return WatchlistResponse(topics=list_watchlist(conn, user_id))


@router.delete("/", response_model=WatchlistResponse)
def remove_topic(
    topic: str = Query(..., min_length=1, max_length=120),
    authorization: str | None = Header(default=None),
) -> WatchlistResponse:
    """Remove a topic and return the refreshed list.

    The topic comes in as a query param (not a path segment) because curated
    topics contain spaces and '&' (e.g. 'Zoning & Land Use').
    """

    from app.civic.db import get_conn, list_watchlist, remove_watchlist

    user_id = current_user_id(authorization)
    with get_conn() as conn:
        remove_watchlist(conn, user_id, topic.strip())
        conn.commit()
        return WatchlistResponse(topics=list_watchlist(conn, user_id))
