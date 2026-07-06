"""GET /civic/insights/recent — the what's-new digest over the civic corpus.

Thin router: it delegates to ``app.civic.digest`` (pure SQL, no LLM). Mounted
under the same ``/civic/insights`` prefix as the other aggregate views so the
opening-value digest lives alongside them without touching the ask path.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.civic.schemas import RecentActivityResponse

router = APIRouter(prefix="/civic/insights")


@router.get("/recent", response_model=RecentActivityResponse)
def recent(
    jurisdiction: str | None = None,
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),
) -> RecentActivityResponse:
    """Recently introduced + enacted bills, optionally by ``?jurisdiction=`` / ``?days=``."""

    from app.civic.digest import recent_activity

    return RecentActivityResponse(**recent_activity(jurisdiction, days, limit))
