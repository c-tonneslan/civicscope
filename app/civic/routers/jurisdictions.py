"""GET /civic/jurisdictions — the cities currently ingested.

Lets a client discover which Legistar jurisdictions are available (to populate a
selector, or to scope /civic/ask and /civic/insights via their ``jurisdiction``
parameter). Thin: delegates to ``app.civic.insights.list_jurisdictions``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.civic.schemas import JurisdictionsResponse

router = APIRouter(prefix="/civic")


@router.get("/jurisdictions", response_model=JurisdictionsResponse)
def jurisdictions() -> JurisdictionsResponse:
    """List every ingested jurisdiction (Legistar client slug) with its bill count."""

    from app.civic.insights import list_jurisdictions

    return JurisdictionsResponse(**list_jurisdictions())
