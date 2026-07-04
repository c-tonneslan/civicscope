"""GET /civic/bills — a paginated, filterable listing of Matters.

The browse surface for a kiosk: raw legislative metadata (no LLM), separate from
the grounded ``/civic/ask`` path. Thin: delegates to ``app.civic.bills``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.civic.schemas import BillListResponse

router = APIRouter(prefix="/civic")


@router.get("/bills", response_model=BillListResponse)
def bills(
    q: str | None = None,
    status: str | None = None,
    jurisdiction: str | None = None,
    since: date | None = None,
    sponsor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> BillListResponse:
    """List Matters newest-first, optionally filtered by ``?q=`` / ``?status=`` /
    ``?jurisdiction=`` / ``?since=`` / ``?sponsor=``, with ``?limit=`` / ``?offset=``
    paging. ``?sponsor=`` keeps only Matters that person sponsored."""

    from app.civic.bills import list_bills

    return BillListResponse(
        **list_bills(q, status, jurisdiction, since, limit, offset, sponsor)
    )
