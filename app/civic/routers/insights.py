"""GET /civic/insights/* — read-only aggregate views over the civic corpus.

Thin routers: they delegate to ``app.civic.insights`` (pure SQL aggregation, no
LLM). Kept separate from the ask/ingest routers so the insight surface can grow
without touching the grounded-answer path.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.civic.schemas import (
    BillTimelineResponse,
    BriefResponse,
    OverviewResponse,
    SponsorsResponse,
    TopicActivityResponse,
    VelocityResponse,
)
from fastapi import Query

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


@router.get("/brief", response_model=BriefResponse)
def brief(
    topic: str = Query(..., min_length=1, max_length=200),
    jurisdiction: str | None = None,
    since: date | None = None,
) -> BriefResponse:
    """A grounded, consulting-style briefing on a policy ``topic``.

    Retrieves the relevant bills and synthesises an advisory summary (overview,
    notable measures, status, guidance) with the same cite-or-refuse discipline as
    ``/civic/ask``. Never 500s for the normal failure modes — returns
    ``refused: true`` with an explanatory ``briefing`` instead.
    """

    from app.civic.brief import generate_brief

    return generate_brief(topic, jurisdiction=jurisdiction, since=since)


@router.get("/sponsors", response_model=SponsorsResponse)
def sponsors(
    topic: str | None = None,
    jurisdiction: str | None = None,
    since: date | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> SponsorsResponse:
    """Most active sponsors, optionally scoped by ``?topic=`` / ``?jurisdiction=``.

    With a topic this answers "who leads on <topic>?" — ranked by distinct bills
    sponsored under the scope.
    """

    from app.civic.insights import top_sponsors

    return SponsorsResponse(**top_sponsors(topic, jurisdiction, since, limit))


@router.get("/timeline", response_model=BillTimelineResponse)
def timeline(
    file_no: str = Query(..., min_length=1, max_length=64),
    jurisdiction: str | None = None,
) -> BillTimelineResponse:
    """The legislative action history (timeline) for one bill by ``?file_no=``."""

    from app.civic.insights import bill_timeline

    return BillTimelineResponse(**bill_timeline(file_no, jurisdiction))


@router.get("/velocity", response_model=VelocityResponse)
def velocity(
    jurisdiction: str | None = None, since: date | None = None
) -> VelocityResponse:
    """How fast enacted legislation moves: count + avg days from intro to final action."""

    from app.civic.insights import legislative_velocity

    return VelocityResponse(**legislative_velocity(jurisdiction, since))
