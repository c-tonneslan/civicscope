"""HTTP contract tests for the civic routers — every error code + success shape.

No Postgres, no LLM, no network: the answer/ingest entry points are stubbed at
their module boundary. Covers:

  POST /civic/ask     — 422 validation, success shape, refusal shape, never-500.
  POST /civic/ingest  — 503 (disabled), 401 (bad/missing token), 200 (success),
                        409 (single-flight), 500 (handled pipeline failure).

Uses the ``civic_client`` fixture (a bare TestClient) from conftest.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("app.civic.answer",
                    reason="civic deps (pgvector/psycopg) not installed")

from app.civic.schemas import AskResponse, Citation  # noqa: E402


# ===========================================================================
# POST /civic/ask
# ===========================================================================


class TestAskEndpoint:
    @pytest.mark.parametrize(
        "body",
        [
            {},                              # missing question
            {"question": ""},                # below min_length=1
            {"question": "x" * 2001},        # above max_length=2000
            {"question": 123},               # wrong type
            {"question": None},              # null
        ],
    )
    def test_validation_errors_422(self, civic_client, body):
        resp = civic_client.post("/civic/ask", json=body)
        assert resp.status_code == 422

    def test_max_length_boundary_ok(self, civic_client, monkeypatch):
        # exactly 2000 chars is allowed.
        monkeypatch.setattr(
            "app.civic.answer.answer_question",
            lambda q, jurisdiction=None: AskResponse(
                answer="ok [Bill 1]",
                citations=[Citation(file_no="1", title="t")],
                refused=False),
        )
        resp = civic_client.post("/civic/ask", json={"question": "q" * 2000})
        assert resp.status_code == 200

    def test_success_shape(self, civic_client, monkeypatch):
        monkeypatch.setattr(
            "app.civic.answer.answer_question",
            lambda q, jurisdiction=None: AskResponse(
                answer="In committee [Bill 260633].",
                citations=[Citation(file_no="260633", title="Ord X")],
                refused=False),
        )
        resp = civic_client.post("/civic/ask", json={"question": "what passed?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["refused"] is False
        assert data["answer"] == "In committee [Bill 260633]."
        assert data["citations"] == [{"file_no": "260633", "title": "Ord X"}]

    def test_refusal_shape_is_200_not_error(self, civic_client, monkeypatch):
        # A refusal is a NORMAL 200 response, not an HTTP error.
        monkeypatch.setattr(
            "app.civic.answer.answer_question",
            lambda q, jurisdiction=None: AskResponse(
                answer="I can't ground this.", citations=[], refused=True),
        )
        resp = civic_client.post("/civic/ask", json={"question": "obscure"})
        assert resp.status_code == 200
        assert resp.json()["refused"] is True
        assert resp.json()["citations"] == []

    def test_passes_question_through(self, civic_client, monkeypatch):
        seen = {}

        def fake_answer(q, jurisdiction=None):
            seen["q"] = q
            seen["jurisdiction"] = jurisdiction
            return AskResponse(
                answer="[Bill 1] ok", citations=[Citation(file_no="1", title="t")],
                refused=False)

        monkeypatch.setattr("app.civic.answer.answer_question", fake_answer)
        civic_client.post("/civic/ask", json={"question": "specific text"})
        assert seen["q"] == "specific text"

    def test_passes_jurisdiction_through(self, civic_client, monkeypatch):
        seen = {}

        def fake_answer(q, jurisdiction=None):
            seen["jurisdiction"] = jurisdiction
            return AskResponse(answer="[Bill 1] ok",
                               citations=[Citation(file_no="1", title="t")],
                               refused=False)

        monkeypatch.setattr("app.civic.answer.answer_question", fake_answer)
        civic_client.post("/civic/ask",
                          json={"question": "q", "jurisdiction": "chicago"})
        assert seen["jurisdiction"] == "chicago"


# ===========================================================================
# POST /civic/ask/stream
# ===========================================================================


class TestAskStreamEndpoint:
    @pytest.mark.parametrize(
        "body",
        [
            {},                              # missing question
            {"question": ""},                # below min_length=1
            {"question": "x" * 2001},        # above max_length=2000
            {"question": 123},               # wrong type
            {"question": None},              # null
        ],
    )
    def test_validation_errors_422(self, civic_client, body):
        # Same AskRequest validation as /ask, before the stream starts.
        resp = civic_client.post("/civic/ask/stream", json=body)
        assert resp.status_code == 422

    def test_streams_ndjson_ending_in_final(self, civic_client, monkeypatch):
        canned = [
            '{"type":"token","text":"In committee [Bill 260633]."}\n',
            '{"type":"final","answer":"In committee [Bill 260633]."'
            ',"citations":[{"file_no":"260633","title":"Ord X"}],"refused":false}\n',
        ]
        monkeypatch.setattr("app.civic.streaming.stream_answer",
                            lambda q, jurisdiction=None: iter(canned))
        resp = civic_client.post("/civic/ask/stream",
                                 json={"question": "what passed?"})
        assert resp.status_code == 200
        assert "application/x-ndjson" in resp.headers["content-type"]
        lines = [ln for ln in resp.text.split("\n") if ln]
        final = json.loads(lines[-1])
        assert final["type"] == "final"
        assert final["refused"] is False
        assert final["citations"] == [{"file_no": "260633", "title": "Ord X"}]

    def test_refusal_stream_is_200_with_refused_final(self, civic_client, monkeypatch):
        canned = [
            '{"type":"final","answer":"I can\'t ground this."'
            ',"citations":[],"refused":true}\n',
        ]
        monkeypatch.setattr("app.civic.streaming.stream_answer",
                            lambda q, jurisdiction=None: iter(canned))
        resp = civic_client.post("/civic/ask/stream", json={"question": "obscure"})
        assert resp.status_code == 200
        final = json.loads([ln for ln in resp.text.split("\n") if ln][-1])
        assert final["refused"] is True
        assert final["citations"] == []


# ===========================================================================
# POST /civic/ingest
# ===========================================================================


class TestIngestEndpoint:
    def test_disabled_returns_503_when_no_token(self, civic_client, civic_settings):
        civic_settings(ingest_token=None)
        resp = civic_client.post("/civic/ingest")
        assert resp.status_code == 503
        assert "disabled" in resp.json()["detail"]

    def test_missing_token_401_when_enabled(self, civic_client, civic_settings):
        civic_settings(ingest_token="secret")
        resp = civic_client.post("/civic/ingest")
        assert resp.status_code == 401

    def test_wrong_token_401(self, civic_client, civic_settings):
        civic_settings(ingest_token="secret")
        resp = civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "nope"})
        assert resp.status_code == 401

    def test_valid_token_success_200(self, civic_client, civic_settings, monkeypatch):
        civic_settings(ingest_token="secret")
        monkeypatch.setattr("app.civic.ingest.run_ingest", lambda: 7)
        resp = civic_client.post("/civic/ingest",
                                 headers={"X-Ingest-Token": "secret"})
        assert resp.status_code == 200
        assert resp.json() == {"ingested": 7}

    def test_pipeline_failure_is_generic_500(self, civic_client, civic_settings,
                                             monkeypatch):
        civic_settings(ingest_token="secret")

        def boom():
            raise RuntimeError("legistar down; secret-ish detail")

        monkeypatch.setattr("app.civic.ingest.run_ingest", boom)
        resp = civic_client.post("/civic/ingest",
                                 headers={"X-Ingest-Token": "secret"})
        assert resp.status_code == 500
        # The raw exception detail must NOT leak to the client.
        assert resp.json()["detail"] == "ingest failed"
        assert "secret-ish" not in resp.text

    def test_single_flight_returns_409(self, civic_client, civic_settings,
                                       monkeypatch):
        civic_settings(ingest_token="secret")
        from app.civic.routers import ingest as ingest_router

        # Hold the single-flight lock so the request finds it already taken.
        acquired = ingest_router._INGEST_LOCK.acquire(blocking=False)
        assert acquired
        try:
            resp = civic_client.post("/civic/ingest",
                                     headers={"X-Ingest-Token": "secret"})
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"]
        finally:
            ingest_router._INGEST_LOCK.release()

    def test_lock_released_after_success(self, civic_client, civic_settings,
                                         monkeypatch):
        civic_settings(ingest_token="secret")
        monkeypatch.setattr("app.civic.ingest.run_ingest", lambda: 1)
        from app.civic.routers import ingest as ingest_router
        civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "secret"})
        # Lock must be free again (acquirable) after the call returns.
        got = ingest_router._INGEST_LOCK.acquire(blocking=False)
        assert got
        ingest_router._INGEST_LOCK.release()

    def test_lock_released_after_failure(self, civic_client, civic_settings,
                                         monkeypatch):
        civic_settings(ingest_token="secret")

        def boom():
            raise RuntimeError("fail")

        monkeypatch.setattr("app.civic.ingest.run_ingest", boom)
        from app.civic.routers import ingest as ingest_router
        civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "secret"})
        got = ingest_router._INGEST_LOCK.acquire(blocking=False)
        assert got
        ingest_router._INGEST_LOCK.release()
