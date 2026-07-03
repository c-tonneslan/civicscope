"""Civic domain records + HTTP request/response contract.

Two layers live here, mirroring AwardGuard's ``models.py`` convention:

  * plain in-process records (``CivicDocument``, ``CivicChunk``) that flow
    between ingest / retrieval / answer;
  * Pydantic models that define the wire contract for the civic routers.

The Postgres *tables* themselves are defined as SQL in ``app.civic.db`` — this
module holds only the Python-side shapes. Kept separate from the existing
``app.schemas`` (tasks/users) so the two slices never collide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# In-process records (flow through ingest / retrieval / answer)
# ---------------------------------------------------------------------------


@dataclass
class CivicDocument:
    """One normalized Legistar Matter.

    ``source_ref`` (the Legistar MatterId) is the idempotent upsert key.
    ``raw`` keeps the full original Legistar JSON so re-normalizing never has to
    re-fetch. ``intro_date`` is parsed to a ``date`` (None when Legistar omits it).
    """

    source_ref: str            # MatterId (upsert key within a jurisdiction)
    doc_type: str | None       # MatterTypeName, e.g. "COMMUNICATION"
    file_no: str | None        # MatterFile, e.g. "260633" — the citation key
    title: str | None          # MatterTitle (falls back to MatterName)
    body_name: str | None      # MatterBodyName, e.g. "CITY COUNCIL"
    status: str | None         # MatterStatusName, e.g. "PLACED ON FILE"
    intro_date: date | None    # MatterIntroDate parsed to a date
    url: str | None            # canonical Legistar URL for the matter
    raw: dict                  # the full original Legistar record
    # Full bill text extracted from the Matter's PDF attachment, when available.
    # TRANSIENT: it is chunked/embedded for retrieval but NOT persisted to
    # civic_documents (which stores only the short title for citation display), so
    # adding it needs no DB migration. None -> ingest falls back to chunking the
    # title, so a Matter is always ingestable even with no/what unreadable PDF.
    body: str | None = None
    # Legistar client slug the Matter came from (its city). Part of the composite
    # upsert key with source_ref, since MatterIds only disambiguate within a city.
    jurisdiction: str = "phila"


@dataclass
class CivicChunk:
    """One embeddable unit derived from a document.

    Carries a back-reference to its parent document's ``source_ref``/``file_no``
    so the answer layer can cite bills after retrieval. ``embedding`` is only
    populated during ingest; retrieval/answer don't need it on the way out.
    """

    source_ref: str                     # parent document upsert key
    file_no: str | None                 # parent bill number (for citation)
    chunk_index: int                    # deterministic ordinal within the document
    text: str                           # the chunk text
    embedding: list[float] | None = field(default=None)


# ---------------------------------------------------------------------------
# API request/response models (the wire contract the civic routers expose)
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """Body of ``POST /civic/ask``."""

    # max_length caps the body before it reaches the model: an unbounded question
    # is forwarded straight into the LLM prompt, so oversized inputs would drive
    # input-token cost/latency. 2000 chars is generous for a civic question while
    # rejecting abuse at validation time.
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="A question about local City Council legislation.",
    )
    # Optional Legistar client slug to scope the answer to one city; None (default)
    # searches every ingested jurisdiction.
    jurisdiction: str | None = Field(
        default=None,
        max_length=64,
        description="Legistar client slug (e.g. 'phila', 'chicago'); null = all cities.",
    )

    @field_validator("question")
    @classmethod
    def _strip_and_require_nonblank(cls, v: str) -> str:
        # min_length=1 alone lets a whitespace-only body ("   ") through and into
        # retrieval. Strip and reject blanks so a direct API caller can't drive the
        # DB path with an effectively empty question (the UI already blocks this).
        stripped = v.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class Citation(BaseModel):
    """One verified citation returned in an answer."""

    file_no: str             # Legistar MatterFile, e.g. "260633"
    title: str               # the matter title


class AskResponse(BaseModel):
    """Body of the ``POST /civic/ask`` response."""

    answer: str
    citations: list[Citation]
    refused: bool


class IngestResponse(BaseModel):
    """Body of the ``POST /civic/ingest`` response."""

    ingested: int


class CountItem(BaseModel):
    """One labelled tally in an overview breakdown (type/status/month)."""

    label: str
    count: int


class OverviewResponse(BaseModel):
    """Body of ``GET /civic/insights/overview`` — a corpus snapshot."""

    total_documents: int
    by_type: list[CountItem]
    by_status: list[CountItem]
    by_month: list[CountItem]          # label is 'YYYY-MM'
    earliest_intro_date: date | None
    latest_intro_date: date | None


class TopicActivityItem(BaseModel):
    """Bill count for one curated policy topic."""

    topic: str
    bills: int


class TopicActivityResponse(BaseModel):
    """Body of ``GET /civic/insights/topics`` — tracked-topic activity."""

    since: date | None
    topics: list[TopicActivityItem]


class BriefResponse(BaseModel):
    """Body of ``GET /civic/insights/brief`` — a grounded advisory topic briefing."""

    topic: str
    jurisdiction: str | None
    matched_bills: int          # how many bills in the corpus match the topic
    briefing: str               # the advisory synthesis (or a refusal message)
    citations: list[Citation]
    refused: bool


class TimelineEntry(BaseModel):
    """One action in a bill's legislative history."""

    action_date: date | None
    action: str | None
    passed: str | None


class BillTimelineResponse(BaseModel):
    """Body of ``GET /civic/insights/timeline`` — one bill's action history."""

    file_no: str
    found: bool
    jurisdiction: str | None
    title: str | None
    status: str | None
    url: str | None
    timeline: list[TimelineEntry]


class VelocityResponse(BaseModel):
    """Body of ``GET /civic/insights/velocity`` — how fast enacted bills move."""

    jurisdiction: str | None
    enacted: int
    avg_days_to_enact: int | None


class RollCallVote(BaseModel):
    """One member's vote in a roll-call."""

    person: str
    vote: str | None


class RollCallResponse(BaseModel):
    """Body of ``GET /civic/insights/rollcall`` — a bill's roll-call."""

    file_no: str
    found: bool
    title: str | None
    action: str | None
    action_date: date | None
    tally: dict[str, int]
    votes: list[RollCallVote]


class MemberRecordItem(BaseModel):
    """Distinct bills a member voted a given way on."""

    vote: str
    bills: int


class MemberRecordResponse(BaseModel):
    """Body of ``GET /civic/insights/member`` — a member's voting record."""

    person: str
    topic: str | None
    jurisdiction: str | None
    record: list[MemberRecordItem]


class SponsorItem(BaseModel):
    """One sponsor and how many bills they sponsored under the query scope."""

    name: str
    bills: int


class SponsorsResponse(BaseModel):
    """Body of ``GET /civic/insights/sponsors`` — most active sponsors."""

    topic: str | None
    jurisdiction: str | None
    sponsors: list[SponsorItem]


class JurisdictionItem(BaseModel):
    """One ingested jurisdiction and how many Matters it holds."""

    slug: str
    documents: int


class JurisdictionsResponse(BaseModel):
    """Body of ``GET /civic/jurisdictions`` — the cities currently ingested."""

    jurisdictions: list[JurisdictionItem]
