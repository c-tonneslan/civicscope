"""GET /civic/insights/* — read-only aggregate views over the civic corpus.

Thin routers: they delegate to ``app.civic.insights`` (pure SQL aggregation, no
LLM). Kept separate from the ask/ingest routers so the insight surface can grow
without touching the grounded-answer path.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.civic.schemas import OverviewResponse, TopicActivityResponse

router = APIRouter(prefix="/civic/insights")


@router.get("/overview", response_model=OverviewResponse)
def overview(jurisdiction: str | None = None) -> OverviewResponse:
    """Quantitative snapshot: totals, type/status/month breakdowns, date span.

    ``?jurisdiction=<slug>`` scopes the snapshot to one city; omit it for all.
    """

    # Lazy import keeps mounting this router free of the DB stack at import time.
    from app.civic.insights import corpus_overview

    return OverviewResponse(**corpus_overview(jurisdiction))


@router.get("/topics", response_model=TopicActivityResponse)
def topics(
    since: date | None = None, jurisdiction: str | None = None
) -> TopicActivityResponse:
    """Bill counts for curated policy topics, optionally by ``?since=`` / ``?jurisdiction=``."""

    from app.civic.insights import topic_activity

    return TopicActivityResponse(**topic_activity(since, jurisdiction))
