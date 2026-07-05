"""Advisory topic briefings — the insight layer's headline feature.

Where ``/civic/ask`` answers a specific question, a *brief* takes a policy TOPIC
("affordable housing", "zoning") and produces a short, structured, consulting-style
briefing: what the legislation covers, where it stands, and practical guidance —
grounded in retrieved bills and held to the SAME cite-or-refuse discipline as the
Q&A path (every claim cites a real [Bill <file_no>]; unverifiable citations are
dropped; a briefing with nothing groundable becomes a refusal).

It reuses the answer layer's provider dispatch (``synthesize_chat``), context
builder, and independent citation verification, so the trust guarantees are
identical — only the prompt (advisory, structured) and the surrounding quantitative
stats differ.
"""

from __future__ import annotations

from datetime import date

from app.civic.answer import (
    DB_DOWN_TEXT,
    OLLAMA_DOWN_TEXT,
    REFUSAL_TEXT,
    _build_context,
    _is_connection_error,
    synthesize_chat,
    verify_citations,
)
from app.civic.db import get_conn
from app.civic.retrieval import RetrievedChunk, _content_terms, retrieve
from app.civic.schemas import BriefResponse, Citation
from app.config import settings

# How many bills to ground the briefing on — a little wider than a Q&A answer,
# since a briefing summarises a topic rather than answering one narrow question.
BRIEF_TOP_K = 8

# Fixed refusal for a topic with no groundable legislation.
BRIEF_REFUSAL_TEXT = (
    "There isn't enough legislation on this topic in the retrieved records to brief on."
)

_BRIEF_SYSTEM_PROMPT = (
    "You are a nonpartisan legislative analyst briefing a busy stakeholder on local "
    "City Council activity. You are given a set of real bills and a topic. Write a "
    "SHORT, factual briefing using ONLY the bills provided, with these sections:\n"
    "  Overview: what this body of legislation is doing on the topic.\n"
    "  Notable measures: the most significant bills, each cited as [Bill <file_no>].\n"
    "  Status & momentum: what has been enacted vs. is still pending, per the bills' "
    "stated status — never call a pending bill enacted.\n"
    "  What to watch: practical, grounded guidance for someone tracking this topic.\n"
    "Cite every specific claim as [Bill <file_no>]. Do not invent bills, numbers, or "
    "facts not in the provided text. If the bills don't meaningfully cover the topic, "
    f"reply exactly: {BRIEF_REFUSAL_TEXT}"
)


def _matched_bill_count(
    topic: str, jurisdiction: str | None, since: date | None
) -> int:
    """Count distinct bills ON the topic (by TITLE), scoped like the brief.

    Topic membership is decided by the bill's title, not incidental body mentions,
    so the "matching bills" figure isn't inflated by bills that merely reference the
    topic in passing. (The briefing itself still grounds on full-text retrieval.)
    """

    content = _content_terms(topic)
    extra = "" if jurisdiction is None else "AND d.jurisdiction = %s"
    params: tuple = (content, since, since)
    if jurisdiction is not None:
        params = (content, since, since, jurisdiction)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*)
            FROM civic_documents d
            WHERE to_tsvector('english', coalesce(d.title, '')) @@ plainto_tsquery('english', %s)
              AND (%s::date IS NULL OR d.intro_date >= %s)
              {extra};
            """,
            params,
        )
        return cur.fetchone()[0]


def _build_brief_prompt(topic: str, chunks: list[RetrievedChunk]) -> str:
    """Advisory user prompt: the grounding bills plus the topic to brief on."""

    context = _build_context(chunks)
    # The topic is short, low-risk input, but fence it consistently with the Q&A
    # path so a crafted "topic" can't smuggle instructions into the prompt.
    safe_topic = topic.replace("\n", " ").strip()[:200]
    return (
        "Bills you may use (and only these):\n\n"
        f"{context}\n\n"
        "============================\n"
        f"Brief the reader on this topic: {safe_topic}\n"
        "Use only the bills above and cite each specific claim as [Bill <file_no>]."
    )


def _empty(topic: str, jurisdiction: str | None, message: str) -> BriefResponse:
    return BriefResponse(
        topic=topic,
        jurisdiction=jurisdiction,
        matched_bills=0,
        briefing=message,
        citations=[],
        refused=True,
    )


def generate_brief(
    topic: str, jurisdiction: str | None = None, since: date | None = None
) -> BriefResponse:
    """Produce a grounded advisory briefing for a policy topic.

    Never raises for the normal failure modes (DB down, Ollama down, empty topic,
    ungroundable) — each returns ``refused: true`` with an explanatory ``briefing``.
    """

    provider = settings.llm_provider.lower()

    # Retrieve topic-relevant bills (also our DB-reachability probe).
    try:
        chunks = retrieve(topic, top_k=BRIEF_TOP_K, jurisdiction=jurisdiction)
        matched = _matched_bill_count(topic, jurisdiction, since)
    except Exception as exc:  # noqa: BLE001 - briefs never crash
        return _empty(topic, jurisdiction,
                      f"{DB_DOWN_TEXT} (retrieval error: {type(exc).__name__})")

    if not chunks:
        return _empty(topic, jurisdiction, BRIEF_REFUSAL_TEXT)

    def _cite_key(c: RetrievedChunk) -> str:
        return c.file_no or c.source_ref

    allowed = {_cite_key(c) for c in chunks}
    title_by_file_no = {_cite_key(c): (c.title or "") for c in chunks}

    try:
        raw = synthesize_chat(_BRIEF_SYSTEM_PROMPT, _build_brief_prompt(topic, chunks))
    except Exception as exc:  # noqa: BLE001 - briefs never crash
        if provider == "ollama" and _is_connection_error(exc):
            return _empty(topic, jurisdiction, OLLAMA_DOWN_TEXT)
        return _empty(topic, jurisdiction,
                      f"{REFUSAL_TEXT} (synthesis error: {type(exc).__name__})")

    # Explicit refusal from either the brief or the reused answer refusal phrase.
    if BRIEF_REFUSAL_TEXT.lower() in raw.lower() or REFUSAL_TEXT.lower() in raw.lower():
        return _empty(topic, jurisdiction, BRIEF_REFUSAL_TEXT)

    verified = verify_citations(raw, allowed)
    if not verified:
        return _empty(topic, jurisdiction, BRIEF_REFUSAL_TEXT)

    citations = [
        Citation(file_no=file_no, title=title_by_file_no.get(file_no, ""))
        for file_no in verified
    ]
    return BriefResponse(
        topic=topic,
        jurisdiction=jurisdiction,
        matched_bills=matched,
        briefing=raw,
        citations=citations,
        refused=False,
    )
