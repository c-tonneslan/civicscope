"""Tests for advisory topic briefings (brief.generate_brief) + the /brief route.

No network/LLM/DB: retrieval, the matched-bill count, and the LLM dispatch are
stubbed at their module boundary. Citation verification runs for real so the
cite-or-refuse guarantee is exercised, not mocked.
"""

from __future__ import annotations

import pytest

brief = pytest.importorskip(
    "app.civic.brief",
    reason="civic deps (pgvector/psycopg) not installed",
)

from app.civic.retrieval import RetrievedChunk  # noqa: E402


def _chunk(file_no="260475", title="Affordable Housing Month"):
    return RetrievedChunk(
        chunk_id=1, source_ref="27386", file_no=file_no, title=title,
        chunk_index=0, text="An ordinance about affordable housing.",
    )


def _wire(monkeypatch, *, chunks, synth, matched=42):
    monkeypatch.setattr(brief, "retrieve", lambda t, top_k=8, jurisdiction=None: chunks)
    monkeypatch.setattr(brief, "_matched_bill_count", lambda t, j, s: matched)
    if isinstance(synth, Exception):
        def _raise(system, user):
            raise synth
        monkeypatch.setattr(brief, "synthesize_chat", _raise)
    else:
        monkeypatch.setattr(brief, "synthesize_chat", lambda system, user: synth)


class TestGenerateBrief:
    def test_grounded_briefing_returns_cited_answer(self, monkeypatch):
        _wire(monkeypatch, chunks=[_chunk("260475")],
              synth="Overview: housing action. [Bill 260475]", matched=69)
        b = brief.generate_brief("affordable housing", jurisdiction="phila")
        assert b.refused is False
        assert b.matched_bills == 69
        assert [c.file_no for c in b.citations] == ["260475"]
        assert b.jurisdiction == "phila"

    def test_no_chunks_refuses(self, monkeypatch):
        _wire(monkeypatch, chunks=[], synth="unused")
        b = brief.generate_brief("obscure topic")
        assert b.refused is True
        assert b.matched_bills == 0
        assert b.briefing == brief.BRIEF_REFUSAL_TEXT

    def test_uncited_briefing_refuses(self, monkeypatch):
        # A briefing that cites nothing groundable is not trustworthy -> refuse.
        _wire(monkeypatch, chunks=[_chunk("260475")], synth="Some prose with no citations.")
        b = brief.generate_brief("housing")
        assert b.refused is True

    def test_hallucinated_citation_dropped_then_refuses(self, monkeypatch):
        # The model cites a bill that was NOT retrieved -> verification drops it -> refuse.
        _wire(monkeypatch, chunks=[_chunk("260475")], synth="Claim [Bill 999999].")
        b = brief.generate_brief("housing")
        assert b.refused is True

    def test_explicit_refusal_phrase_collapses(self, monkeypatch):
        _wire(monkeypatch, chunks=[_chunk()], synth=brief.BRIEF_REFUSAL_TEXT)
        b = brief.generate_brief("housing")
        assert b.refused is True

    def test_ollama_connection_error_gives_hint(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "ollama")

        class ConnectError(Exception):
            pass

        _wire(monkeypatch, chunks=[_chunk()], synth=ConnectError("down"))
        b = brief.generate_brief("housing")
        assert b.refused is True
        assert b.briefing == brief.OLLAMA_DOWN_TEXT

    def test_retrieval_error_degrades_to_db_hint(self, monkeypatch):
        def _boom(t, top_k=8, jurisdiction=None):
            raise RuntimeError("pool timeout")
        monkeypatch.setattr(brief, "retrieve", _boom)
        b = brief.generate_brief("housing")
        assert b.refused is True
        assert brief.DB_DOWN_TEXT in b.briefing


class TestBriefRoute:
    def test_brief_route_shape(self, civic_client, monkeypatch):
        from app.civic.schemas import BriefResponse, Citation
        monkeypatch.setattr(
            "app.civic.brief.generate_brief",
            lambda topic, jurisdiction=None, since=None: BriefResponse(
                topic=topic, jurisdiction=jurisdiction, matched_bills=5,
                briefing="Overview [Bill 1]",
                citations=[Citation(file_no="1", title="t")], refused=False),
        )
        resp = civic_client.get("/civic/insights/brief?topic=housing")
        assert resp.status_code == 200
        assert resp.json()["matched_bills"] == 5

    def test_brief_route_requires_topic(self, civic_client):
        assert civic_client.get("/civic/insights/brief").status_code == 422

    def test_brief_route_passes_scope_through(self, civic_client, monkeypatch):
        seen = {}

        def fake(topic, jurisdiction=None, since=None):
            seen.update(topic=topic, jurisdiction=jurisdiction)
            from app.civic.schemas import BriefResponse
            return BriefResponse(topic=topic, jurisdiction=jurisdiction,
                                 matched_bills=0, briefing="x", citations=[], refused=True)

        monkeypatch.setattr("app.civic.brief.generate_brief", fake)
        civic_client.get("/civic/insights/brief?topic=zoning&jurisdiction=chicago")
        assert seen == {"topic": "zoning", "jurisdiction": "chicago"}
