"""Tests for the token-streamed answer layer (app.civic.streaming).

Covers the non-network pieces with NO real LLM / NO Postgres: event framing,
the guard ordering that mirrors answer_question, and the deferred cite-or-refuse
verification that runs after the (mocked) token stream closes.

  * event framing — every line is valid JSON ending in \n; the LAST event is
    always ``final``.
  * empty retrieval / DB error / anthropic-no-key short-circuits.
  * happy path — tokens concatenate to the raw answer; final refused false with
    verified citations.
  * hallucinated / uncited / explicit-refusal streams collapse to refused true.
  * ollama connection error vs generic stream error.
  * null-file_no grounds on source_ref (parity with answer_question).

The token producer is stubbed by patching ``streaming._ollama_stream``;
retrieval by patching ``streaming.retrieve``.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

streaming = pytest.importorskip(
    "app.civic.streaming",
    reason="civic streaming deps (pgvector/psycopg) not installed",
)

from app.civic.retrieval import RetrievedChunk  # noqa: E402  (after importorskip)


def _chunk(file_no="260633", source_ref="27386", title="t", text="body",
           status="IN COMMITTEE", doc_type="Ordinance",
           intro_date=date(2026, 6, 11), chunk_id=1, chunk_index=0):
    return RetrievedChunk(
        chunk_id=chunk_id, source_ref=source_ref, file_no=file_no, title=title,
        chunk_index=chunk_index, text=text, doc_type=doc_type, status=status,
        intro_date=intro_date,
    )


def _events(question="q", jurisdiction=None):
    """Drain stream_answer into parsed events, asserting the NDJSON framing."""

    lines = list(streaming.stream_answer(question, jurisdiction=jurisdiction))
    events = []
    for line in lines:
        assert line.endswith("\n")
        events.append(json.loads(line))
    return events


def _patch(monkeypatch, *, chunks, tokens=None, provider="ollama"):
    from app.config import settings
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(streaming, "retrieve",
                        lambda q, top_k=6, jurisdiction=None: chunks)
    if tokens is not None:
        monkeypatch.setattr(streaming, "_ollama_stream",
                            lambda system, user: iter(tokens))


# ===========================================================================
# Event framing
# ===========================================================================


class TestEventFraming:
    def test_last_event_is_always_final(self, monkeypatch):
        _patch(monkeypatch, chunks=[_chunk()],
               tokens=["It is ", "in committee ", "[Bill 260633]."])
        events = _events()
        assert events[-1]["type"] == "final"
        assert all(e["type"] == "token" for e in events[:-1])

    def test_every_line_is_valid_json_ending_in_newline(self, monkeypatch):
        _patch(monkeypatch, chunks=[_chunk()], tokens=["a ", "[Bill 260633]"])
        # _events() already asserts JSON-parse + trailing newline per line.
        events = _events()
        assert len(events) >= 2


# ===========================================================================
# Guard ordering (mirrors answer_question)
# ===========================================================================


class TestGuardOrdering:
    def test_empty_retrieval_single_final_refused_no_tokens(self, monkeypatch):
        _patch(monkeypatch, chunks=[], tokens=["should not run"])
        events = _events()
        assert len(events) == 1
        assert events[0] == {
            "type": "final", "answer": streaming.REFUSAL_TEXT,
            "citations": [], "refused": True,
        }

    def test_db_error_final_refused_never_raises(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "ollama")

        def boom(q, top_k=6, jurisdiction=None):
            raise RuntimeError("pool timeout")

        monkeypatch.setattr(streaming, "retrieve", boom)
        events = _events()  # must not raise
        assert len(events) == 1
        assert events[0]["refused"] is True
        assert streaming.DB_DOWN_TEXT in events[0]["answer"]
        assert "RuntimeError" in events[0]["answer"]

    def test_anthropic_no_key_short_circuits_before_retrieve(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "anthropic")
        monkeypatch.setattr(settings, "anthropic_api_key", None)

        def boom(*a, **k):
            raise AssertionError("retrieve must not run without a key")

        monkeypatch.setattr(streaming, "retrieve", boom)
        events = _events()
        assert events == [{
            "type": "final", "answer": streaming.NO_KEY_TEXT,
            "citations": [], "refused": True,
        }]


# ===========================================================================
# Happy path + deferred verification
# ===========================================================================


class TestHappyPath:
    def test_tokens_concat_to_raw_and_citations_verified(self, monkeypatch):
        tokens = ["It is ", "in committee ", "[Bill 260633]."]
        _patch(monkeypatch, chunks=[_chunk(file_no="260633", title="Ord X")],
               tokens=tokens)
        events = _events()
        token_text = "".join(e["text"] for e in events if e["type"] == "token")
        final = events[-1]
        assert token_text == "".join(tokens)
        assert final["refused"] is False
        assert final["answer"] == "".join(tokens)
        assert final["citations"] == [{"file_no": "260633", "title": "Ord X"}]

    def test_null_file_no_grounds_on_source_ref(self, monkeypatch):
        chunk = _chunk(file_no=None, source_ref="99999", title="Comm Y")
        _patch(monkeypatch, chunks=[chunk],
               tokens=["A communication [Bill 99999]."])
        final = _events()[-1]
        assert final["refused"] is False
        assert final["citations"] == [{"file_no": "99999", "title": "Comm Y"}]


# ===========================================================================
# Deferred verification collapses untrustworthy streams to refused
# ===========================================================================


class TestVerificationCollapse:
    def test_all_hallucinated_refuses_empty_citations(self, monkeypatch):
        _patch(monkeypatch, chunks=[_chunk(file_no="260633")],
               tokens=["It passed [Bill 999999]."])
        final = _events()[-1]
        assert final["refused"] is True
        assert final["citations"] == []
        assert final["answer"] == streaming.REFUSAL_TEXT

    def test_uncited_answer_refuses(self, monkeypatch):
        _patch(monkeypatch, chunks=[_chunk(file_no="260633")],
               tokens=["It does a thing but no cite."])
        final = _events()[-1]
        assert final["refused"] is True
        assert final["citations"] == []

    def test_explicit_refusal_phrase_collapses(self, monkeypatch):
        tokens = [f"In committee [Bill 260633]. {streaming.REFUSAL_TEXT}"]
        _patch(monkeypatch, chunks=[_chunk(file_no="260633")], tokens=tokens)
        final = _events()[-1]
        assert final["refused"] is True
        assert final["citations"] == []
        assert final["answer"] == streaming.REFUSAL_TEXT

    def test_mixed_real_and_hallucinated_keeps_only_real(self, monkeypatch):
        _patch(monkeypatch, chunks=[_chunk(file_no="260633", title="Ord X")],
               tokens=["In committee [Bill 260633]; also [Bill 111111]."])
        final = _events()[-1]
        assert final["refused"] is False
        assert final["citations"] == [{"file_no": "260633", "title": "Ord X"}]


# ===========================================================================
# Stream-time transport failures degrade, never raise
# ===========================================================================


class TestStreamErrors:
    def test_ollama_connection_error_gives_ollama_down_hint(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "ollama")
        monkeypatch.setattr(streaming, "retrieve",
                            lambda q, top_k=6, jurisdiction=None: [_chunk()])

        class ConnectError(Exception):
            pass

        def boom(system, user):
            raise ConnectError("no server")
            yield  # pragma: no cover - marks this a generator

        monkeypatch.setattr(streaming, "_ollama_stream", boom)
        events = _events()
        assert events[-1]["refused"] is True
        assert events[-1]["answer"] == streaming.OLLAMA_DOWN_TEXT

    def test_generic_stream_error_refuses_with_type_name(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "ollama")
        monkeypatch.setattr(streaming, "retrieve",
                            lambda q, top_k=6, jurisdiction=None: [_chunk()])

        def boom(system, user):
            raise ValueError("boom")
            yield  # pragma: no cover

        monkeypatch.setattr(streaming, "_ollama_stream", boom)
        events = _events()
        assert events[-1]["refused"] is True
        assert "ValueError" in events[-1]["answer"]
        assert streaming.REFUSAL_TEXT in events[-1]["answer"]


# ===========================================================================
# Anthropic non-streaming fallback (single token then verify)
# ===========================================================================


class TestAnthropicFallback:
    def test_anthropic_with_key_emits_single_token_then_verifies(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "anthropic")
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
        monkeypatch.setattr(streaming, "retrieve",
                            lambda q, top_k=6, jurisdiction=None:
                            [_chunk(file_no="260633", title="Ord X")])
        monkeypatch.setattr(streaming, "synthesize_chat",
                            lambda system, user: "In committee [Bill 260633].")
        events = _events()
        tokens = [e for e in events if e["type"] == "token"]
        assert len(tokens) == 1
        assert tokens[0]["text"] == "In committee [Bill 260633]."
        assert events[-1]["refused"] is False
        assert events[-1]["citations"] == [{"file_no": "260633", "title": "Ord X"}]
