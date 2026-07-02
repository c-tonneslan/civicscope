"""Endpoint tests for POST /civic/ingest and POST /civic/ask.

Every error code and success/refusal/degradation shape is exercised through the
real FastAPI app (TestClient) with the network, the LLM, and Postgres all stubbed
at their boundaries:

  * /civic/ingest -> the lazily-imported ``app.civic.ingest.run_ingest`` is
    patched, and ``settings.ingest_token`` is toggled, so the token gate (503 /
    401), the single-flight lock (409), success (200), and handled failures (500)
    are all reachable with no pipeline, no Legistar, no DB.
  * /civic/ask -> ``app.civic.answer.retrieve`` and ``app.civic.answer._synthesize``
    are patched, so validation (422), success shape, all four refusal/degradation
    paths, and provider dispatch are reachable with no retrieval, no LLM, no DB.

The suite stays green with none of those present. The two civic routers are
mounted on the shared app object in app/main.py, so ``civic_client`` (a plain
TestClient) reaches them directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

pytest.importorskip("app.civic.answer", reason="civic deps (pgvector/psycopg) absent")

from app.civic.retrieval import RetrievedChunk  # noqa: E402


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _chunk(file_no="260633", title="An Ordinance", source_ref="27386", text="body"):
    return RetrievedChunk(
        chunk_id=1, source_ref=source_ref, file_no=file_no,
        title=title, chunk_index=0, text=text,
    )


# Patch the synthesis + retrieval boundaries for the /ask path. retrieve and
# _synthesize are both looked up on the answer module at call time, so patching
# there intercepts them.
def _patch_ask(chunks, raw):
    return patch.multiple(
        "app.civic.answer",
        retrieve=lambda *a, **k: chunks,
        _synthesize=lambda *a, **k: raw,
    )


# ===========================================================================
# POST /civic/ingest — token gate + lock + success + handled failure
# ===========================================================================


class TestIngestAuth:
    def test_503_when_ingest_token_unset(self, civic_client, civic_settings):
        # Disabled-by-default: with no token configured the route is unavailable,
        # so a fresh deploy is never open to anonymous ingest spam.
        civic_settings(ingest_token=None)
        resp = civic_client.post("/civic/ingest")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "ingest endpoint is disabled"

    def test_503_takes_priority_over_missing_header(self, civic_client, civic_settings):
        # Even with a (would-be) header present, no configured token => 503, not 401.
        civic_settings(ingest_token=None)
        resp = civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "x"})
        assert resp.status_code == 503

    def test_401_when_token_set_but_header_missing(self, civic_client, civic_settings):
        civic_settings(ingest_token="s3cret")
        resp = civic_client.post("/civic/ingest")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid or missing ingest token"

    @pytest.mark.parametrize("bad", ["wrong", "", "s3cre", "s3crett", "S3CRET"])
    def test_401_on_mismatched_token(self, civic_client, civic_settings, bad):
        civic_settings(ingest_token="s3cret")
        resp = civic_client.post("/civic/ingest", headers={"X-Ingest-Token": bad})
        assert resp.status_code == 401

    def test_401_does_not_reveal_the_expected_token(self, civic_client, civic_settings):
        civic_settings(ingest_token="s3cret")
        body = civic_client.post(
            "/civic/ingest", headers={"X-Ingest-Token": "wrong"}
        ).json()
        assert "s3cret" not in str(body)


class TestIngestSuccess:
    @pytest.mark.parametrize("count", [0, 1, 7, 200])
    def test_200_returns_ingested_count(self, civic_client, civic_settings, count):
        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", return_value=count):
            resp = civic_client.post(
                "/civic/ingest", headers={"X-Ingest-Token": "s3cret"}
            )
        assert resp.status_code == 200
        assert resp.json() == {"ingested": count}

    def test_response_matches_ingest_response_schema(self, civic_client, civic_settings):
        from app.civic.schemas import IngestResponse

        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", return_value=3):
            data = civic_client.post(
                "/civic/ingest", headers={"X-Ingest-Token": "s3cret"}
            ).json()
        # Round-trips through the response model with no extra/missing keys.
        assert IngestResponse(**data).ingested == 3
        assert set(data) == {"ingested"}

    def test_valid_token_calls_run_ingest_once(self, civic_client, civic_settings):
        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", return_value=1) as run:
            civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "s3cret"})
        run.assert_called_once()


class TestIngestFailure:
    def test_500_on_pipeline_exception_is_generic(self, civic_client, civic_settings):
        # The raw exception is logged server-side but never echoed to the client.
        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", side_effect=RuntimeError("boom secret")):
            resp = civic_client.post(
                "/civic/ingest", headers={"X-Ingest-Token": "s3cret"}
            )
        assert resp.status_code == 500
        assert resp.json() == {"detail": "ingest failed"}
        assert "boom secret" not in str(resp.json())

    @pytest.mark.parametrize(
        "exc",
        [RuntimeError("x"), ValueError("y"), KeyError("z"), Exception("generic")],
    )
    def test_500_for_any_pipeline_exception_type(self, civic_client, civic_settings, exc):
        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", side_effect=exc):
            resp = civic_client.post(
                "/civic/ingest", headers={"X-Ingest-Token": "s3cret"}
            )
        assert resp.status_code == 500

    def test_lock_released_after_failure(self, civic_client, civic_settings):
        # A failing run must release the single-flight lock, or the endpoint would
        # be wedged at 409 forever. A second call after a failure must reach the
        # pipeline again (here: succeed).
        civic_settings(ingest_token="s3cret")
        hdr = {"X-Ingest-Token": "s3cret"}
        with patch("app.civic.ingest.run_ingest", side_effect=RuntimeError("x")):
            assert civic_client.post("/civic/ingest", headers=hdr).status_code == 500
        with patch("app.civic.ingest.run_ingest", return_value=2):
            assert civic_client.post("/civic/ingest", headers=hdr).status_code == 200


class TestIngestConcurrency:
    def test_409_when_an_ingest_is_already_running(self, civic_client, civic_settings):
        # Hold the single-flight lock from the outside so the request's
        # non-blocking acquire fails fast with 409 instead of queueing.
        from app.civic.routers import ingest as ingest_router

        civic_settings(ingest_token="s3cret")
        acquired = ingest_router._INGEST_LOCK.acquire(blocking=False)
        assert acquired
        try:
            resp = civic_client.post(
                "/civic/ingest", headers={"X-Ingest-Token": "s3cret"}
            )
            assert resp.status_code == 409
            assert resp.json()["detail"] == "an ingest is already running"
        finally:
            ingest_router._INGEST_LOCK.release()

    def test_lock_is_free_again_after_release(self, civic_client, civic_settings):
        from app.civic.routers import ingest as ingest_router

        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", return_value=0):
            civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "s3cret"})
        # Lock must be releasable => it was released by the finally in the handler.
        assert ingest_router._INGEST_LOCK.acquire(blocking=False)
        ingest_router._INGEST_LOCK.release()


# ===========================================================================
# POST /civic/ask — validation (422)
# ===========================================================================


class TestAskValidation:
    @pytest.mark.parametrize(
        "body",
        [
            {},                       # missing question
            {"question": ""},         # empty (min_length=1)
            {"question": None},       # null
            {"question": 123},        # wrong type
            {"question": ["a"]},      # wrong type (list)
            {"wrong_key": "hi"},      # extra/wrong field, question absent
        ],
    )
    def test_422_on_invalid_body(self, civic_client, body):
        resp = civic_client.post("/civic/ask", json=body)
        assert resp.status_code == 422

    def test_422_on_question_over_max_length(self, civic_client):
        # max_length=2000 caps the body before it reaches the model.
        resp = civic_client.post("/civic/ask", json={"question": "x" * 2001})
        assert resp.status_code == 422

    def test_422_body_reports_question_field(self, civic_client):
        detail = civic_client.post("/civic/ask", json={}).json()["detail"]
        assert any("question" in str(err.get("loc", "")) for err in detail)

    def test_2000_char_question_is_accepted(self, civic_client):
        # Exactly at the boundary is valid (min_length=1 <= 2000 <= max_length).
        with _patch_ask([_chunk()], "X [Bill 260633]."):
            resp = civic_client.post("/civic/ask", json={"question": "x" * 2000})
        assert resp.status_code == 200

    def test_single_char_question_is_accepted(self, civic_client):
        with _patch_ask([_chunk()], "X [Bill 260633]."):
            resp = civic_client.post("/civic/ask", json={"question": "x"})
        assert resp.status_code == 200


# ===========================================================================
# POST /civic/ask — success shape
# ===========================================================================


class TestAskSuccess:
    def test_grounded_answer_shape(self, civic_client):
        with _patch_ask([_chunk()], "Council did X [Bill 260633]."):
            resp = civic_client.post("/civic/ask", json={"question": "q"})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"answer", "citations", "refused"}
        assert data["refused"] is False
        assert data["answer"] == "Council did X [Bill 260633]."
        assert data["citations"] == [{"file_no": "260633", "title": "An Ordinance"}]

    def test_response_round_trips_ask_response_schema(self, civic_client):
        from app.civic.schemas import AskResponse

        with _patch_ask([_chunk()], "X [Bill 260633]."):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        model = AskResponse(**data)
        assert model.refused is False
        assert model.citations[0].file_no == "260633"

    def test_multiple_distinct_citations_preserved_in_order(self, civic_client):
        chunks = [_chunk(file_no="260633", title="A"),
                  _chunk(file_no="240100-A", title="B", source_ref="27400")]
        with _patch_ask(chunks, "First [Bill 240100-A] then [Bill 260633]."):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        # Citation order follows first appearance in the answer text.
        assert [c["file_no"] for c in data["citations"]] == ["240100-A", "260633"]

    def test_null_file_no_bill_is_citable_by_source_ref(self, civic_client):
        # Legistar MatterFile is legitimately null on some records; the answer
        # layer keys and cites off source_ref so such bills aren't force-refused.
        chunk = _chunk(file_no=None, source_ref="99999", title="A communication")
        with _patch_ask([chunk], "See [Bill 99999]."):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is False
        assert data["citations"] == [{"file_no": "99999", "title": "A communication"}]


# ===========================================================================
# POST /civic/ask — refusal + graceful degradation (never 5xx)
# ===========================================================================


class TestAskRefusalAndDegradation:
    REFUSAL = "I can't ground this in the retrieved Philadelphia legislation."

    def test_empty_retrieval_refuses(self, civic_client):
        with _patch_ask([], "unused"):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is True
        assert data["answer"] == self.REFUSAL
        assert data["citations"] == []

    def test_hallucinated_citation_dropped_then_refuses(self, civic_client):
        # 999999 was never retrieved; after the invented cite is stripped there is
        # nothing groundable left, so the whole answer collapses to a refusal.
        with _patch_ask([_chunk(file_no="260633")], "See [Bill 999999]."):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is True
        assert data["citations"] == []

    def test_answer_with_no_citation_refuses(self, civic_client):
        with _patch_ask([_chunk()], "The council did a thing with no citation."):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is True

    def test_model_emitting_refusal_phrase_refuses(self, civic_client):
        # The refusal phrase anywhere in the output collapses to a clean refusal,
        # even if the model also (contradictorily) cited a real bill.
        raw = f"Here is an answer [Bill 260633]. {self.REFUSAL}"
        with _patch_ask([_chunk()], raw):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is True
        assert data["answer"] == self.REFUSAL

    def test_ollama_unreachable_degrades_with_hint(self, civic_client, civic_settings):
        civic_settings(llm_provider="ollama")

        class ConnectError(Exception):
            pass

        with patch("app.civic.answer.retrieve", return_value=[_chunk()]), patch(
            "app.civic.answer._synthesize", side_effect=ConnectError("down")
        ):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is True
        assert "Ollama" in data["answer"]
        assert data["citations"] == []

    def test_generic_synthesis_error_degrades_to_refusal(self, civic_client, civic_settings):
        civic_settings(llm_provider="ollama")
        with patch("app.civic.answer.retrieve", return_value=[_chunk()]), patch(
            "app.civic.answer._synthesize", side_effect=RuntimeError("boom")
        ):
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        assert data["refused"] is True
        assert "synthesis error" in data["answer"]
        # The exception TYPE is surfaced, but not its message (no leak).
        assert "RuntimeError" in data["answer"]
        assert "boom" not in data["answer"]

    def test_anthropic_provider_no_key_short_circuits_before_retrieval(
        self, civic_client, civic_settings
    ):
        civic_settings(llm_provider="anthropic", anthropic_api_key=None)
        with patch("app.civic.answer.retrieve") as retrieve:
            data = civic_client.post("/civic/ask", json={"question": "q"}).json()
        # No wasted DB round-trip when the deploy is misconfigured.
        retrieve.assert_not_called()
        assert data["refused"] is True
        assert "Anthropic API key" in data["answer"]

    def test_ask_never_returns_5xx_on_degradation(self, civic_client, civic_settings):
        # The endpoint's contract: normal failure modes come back 200 + refused,
        # never a 500. Sweep the degradation paths and assert status 200 each time.
        civic_settings(llm_provider="ollama")
        scenarios = [
            ("app.civic.answer._synthesize", RuntimeError("x")),
            ("app.civic.answer._synthesize", ValueError("x")),
        ]
        for target, exc in scenarios:
            with patch("app.civic.answer.retrieve", return_value=[_chunk()]), patch(
                target, side_effect=exc
            ):
                resp = civic_client.post("/civic/ask", json={"question": "q"})
            assert resp.status_code == 200
            assert resp.json()["refused"] is True


# ===========================================================================
# Provider dispatch through the endpoint
# ===========================================================================


class TestAskProviderDispatch:
    def test_ollama_provider_calls_ollama_backend(self, civic_client, civic_settings):
        civic_settings(llm_provider="ollama")
        with patch("app.civic.answer.retrieve", return_value=[_chunk()]), patch(
            "app.civic.answer._call_ollama", return_value="X [Bill 260633].",
        ) as ollama, patch("app.civic.answer._call_anthropic") as anthropic:
            resp = civic_client.post("/civic/ask", json={"question": "q"})
        assert resp.status_code == 200
        ollama.assert_called_once()
        anthropic.assert_not_called()

    def test_anthropic_provider_with_key_calls_anthropic_backend(
        self, civic_client, civic_settings
    ):
        civic_settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
        with patch("app.civic.answer.retrieve", return_value=[_chunk()]), patch(
            "app.civic.answer._call_anthropic", return_value="X [Bill 260633].",
        ) as anthropic, patch("app.civic.answer._call_ollama") as ollama:
            resp = civic_client.post("/civic/ask", json={"question": "q"})
        assert resp.status_code == 200
        anthropic.assert_called_once()
        ollama.assert_not_called()

    def test_unknown_provider_degrades_to_refusal_not_500(
        self, civic_client, civic_settings
    ):
        # _synthesize raises ValueError for an unknown provider; the endpoint must
        # catch it and refuse, never 500.
        civic_settings(llm_provider="gpt4all")
        with patch("app.civic.answer.retrieve", return_value=[_chunk()]):
            resp = civic_client.post("/civic/ask", json={"question": "q"})
        assert resp.status_code == 200
        assert resp.json()["refused"] is True


# ===========================================================================
# Method / routing sanity (the endpoints exist and are POST-only)
# ===========================================================================


class TestRouting:
    @pytest.mark.parametrize("path", ["/civic/ingest", "/civic/ask"])
    def test_get_not_allowed(self, civic_client, path):
        assert civic_client.get(path).status_code == 405

    def test_both_routes_are_mounted_in_openapi(self, civic_client):
        paths = civic_client.get("/openapi.json").json()["paths"]
        assert "/civic/ingest" in paths
        assert "/civic/ask" in paths

    def test_existing_health_route_still_works(self, civic_client):
        # Guard: mounting the civic routers didn't disturb the base app.
        assert civic_client.get("/health").json() == {"status": "ok"}


# ===========================================================================
# Property-based (Hypothesis) — combinatorial input space of both endpoints
#
# The parametrized cases above enumerate specific rows; these properties assert
# the INVARIANTS that must hold across the whole input space. Fixtures here are
# function-scoped and stateless (a fresh TestClient / a monkeypatch setter), so
# reusing them across Hypothesis examples is safe — we suppress the
# function_scoped_fixture health check to acknowledge that intentionally.
# ===========================================================================

# A strategy for questions the AskRequest model accepts (1..2000 chars). We keep
# the LLM/retrieval stubbed, so the exact text never reaches a real model; it
# only has to survive validation and prompt construction.
_valid_question = st.text(min_size=1, max_size=2000)

# HTTP header values are latin-1 at the wire, and httpx additionally rejects
# non-ASCII / control chars before sending. To probe the TOKEN GATE (not httpx's
# encoder) we draw header-safe tokens: printable ASCII minus whitespace.
_header_chars = st.characters(min_codepoint=0x21, max_codepoint=0x7E)
_header_token = st.text(alphabet=_header_chars, max_size=24)

# A distinctive, unmistakable secret payload for leak assertions. Short random
# messages (")", "'") give false positives because those chars occur naturally
# in the generic response bodies; a sentinel-prefixed token cannot collide.
_secret_msg = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), min_size=1, max_size=40
).map(lambda s: "LEAKSENTINEL_" + s)


class TestAskPropertyContract:
    # The endpoint's central contract, swept over the input space: for ANY valid
    # question and ANY synthesis output, /ask returns 200 with a schema-shaped
    # body — never a 5xx, never a malformed payload.
    @given(question=_valid_question, raw=st.text(max_size=300))
    @hyp_settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ask_is_never_5xx_and_always_well_shaped(self, civic_client, question, raw):
        from app.civic.schemas import AskResponse

        with _patch_ask([_chunk()], raw):
            resp = civic_client.post("/civic/ask", json={"question": question})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"answer", "citations", "refused"}
        assert isinstance(data["answer"], str)
        assert isinstance(data["refused"], bool)
        # Round-trips the response contract with no extra/missing keys.
        AskResponse(**data)

    # Grounding invariant: whatever the model emits, every citation returned was
    # actually in the retrieved set (no hallucinated file_no can survive), and a
    # non-refusal always carries at least one citation.
    @given(
        question=_valid_question,
        cited=st.lists(st.from_regex(r"[0-9]{3,6}", fullmatch=True), max_size=6, unique=True),
    )
    @hyp_settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ask_citations_are_always_grounded(self, civic_client, question, cited):
        retrieved_file_no = "260633"
        text = "Answer " + " ".join(f"[Bill {c}]" for c in cited) + "."
        with _patch_ask([_chunk(file_no=retrieved_file_no)], text):
            data = civic_client.post("/civic/ask", json={"question": question}).json()
        returned = {c["file_no"] for c in data["citations"]}
        # Only the genuinely-retrieved file_no may ever appear.
        assert returned.issubset({retrieved_file_no})
        if data["refused"]:
            assert data["citations"] == []
        else:
            assert returned == {retrieved_file_no}

    # Validation boundary swept: length strictly inside [1, 2000] is never
    # rejected for length; length 0 or >2000 is always a 422.
    @given(n=st.integers(min_value=0, max_value=2600))
    @hyp_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ask_length_boundary_property(self, civic_client, n):
        with _patch_ask([_chunk()], "X [Bill 260633]."):
            resp = civic_client.post("/civic/ask", json={"question": "x" * n})
        if n == 0 or n > 2000:
            assert resp.status_code == 422
        else:
            assert resp.status_code == 200

    # Empty retrieval always refuses with empty citations, no matter the question
    # or what the (unreached) model would have said.
    @given(question=_valid_question, raw=st.text(max_size=200))
    @hyp_settings(max_examples=120, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ask_empty_retrieval_always_refuses(self, civic_client, question, raw):
        with _patch_ask([], raw):
            data = civic_client.post("/civic/ask", json={"question": question}).json()
        assert data["refused"] is True
        assert data["citations"] == []

    # Any synthesis exception, of any type, degrades to a 200 refusal that never
    # leaks the exception message.
    @given(
        question=_valid_question,
        msg=_secret_msg,
        exc_cls=st.sampled_from([RuntimeError, ValueError, KeyError, TypeError, Exception]),
    )
    @hyp_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ask_any_synthesis_error_degrades_without_leak(
        self, civic_client, civic_settings, question, msg, exc_cls
    ):
        civic_settings(llm_provider="ollama")
        with patch("app.civic.answer.retrieve", return_value=[_chunk()]), patch(
            "app.civic.answer._synthesize", side_effect=exc_cls(msg)
        ):
            resp = civic_client.post("/civic/ask", json={"question": question})
        assert resp.status_code == 200
        data = resp.json()
        assert data["refused"] is True
        # The message is never echoed; only the exception type name may appear.
        assert msg not in data["answer"]


class TestIngestPropertyGate:
    # Token gate swept over (configured, presented) pairs:
    #   * unset configured token   -> always 503 (disabled), regardless of header
    #   * set + non-matching header -> always 401
    #   * set + matching header     -> reaches the (stubbed) pipeline -> 200
    # And the configured token is never present in any error body.
    @given(
        # A distinctive configured secret so the "never leaks" assertion is real:
        # a bare single-char token like ':' occurs naturally in the JSON body and
        # would be a false positive.
        configured=_header_token.map(lambda s: "TOKENSENTINEL_" + s),
        presented=st.one_of(st.none(), _header_token),
    )
    @hyp_settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ingest_token_gate_property(
        self, civic_client, civic_settings, configured, presented
    ):
        civic_settings(ingest_token=configured)
        headers = {} if presented is None else {"X-Ingest-Token": presented}
        with patch("app.civic.ingest.run_ingest", return_value=0):
            resp = civic_client.post("/civic/ingest", headers=headers)
        if presented == configured:
            assert resp.status_code == 200
            assert resp.json() == {"ingested": 0}
        else:
            assert resp.status_code == 401
            # A wrong/absent token must never reveal the configured secret.
            assert configured not in str(resp.json())

    @given(presented=st.one_of(st.none(), _header_token))
    @hyp_settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ingest_disabled_is_503_for_any_header(
        self, civic_client, civic_settings, presented
    ):
        civic_settings(ingest_token=None)
        headers = {} if presented is None else {"X-Ingest-Token": presented}
        resp = civic_client.post("/civic/ingest", headers=headers)
        assert resp.status_code == 503

    # Any non-negative count the pipeline returns is echoed verbatim in the body.
    @given(count=st.integers(min_value=0, max_value=10_000_000))
    @hyp_settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ingest_echoes_any_count(self, civic_client, civic_settings, count):
        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", return_value=count):
            resp = civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "s3cret"})
        assert resp.status_code == 200
        assert resp.json() == {"ingested": count}

    # Any pipeline exception, of any type, becomes a generic 500 that never leaks
    # the exception message, and the single-flight lock is always released after.
    @given(
        msg=_secret_msg,
        exc_cls=st.sampled_from([RuntimeError, ValueError, KeyError, TypeError, Exception]),
    )
    @hyp_settings(max_examples=120, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ingest_any_failure_is_generic_500_and_frees_lock(
        self, civic_client, civic_settings, msg, exc_cls
    ):
        from app.civic.routers import ingest as ingest_router

        civic_settings(ingest_token="s3cret")
        with patch("app.civic.ingest.run_ingest", side_effect=exc_cls(msg)):
            resp = civic_client.post("/civic/ingest", headers={"X-Ingest-Token": "s3cret"})
        assert resp.status_code == 500
        assert resp.json() == {"detail": "ingest failed"}
        assert msg not in str(resp.json())
        # The lock must be free again (finally released it), or the endpoint wedges.
        assert ingest_router._INGEST_LOCK.acquire(blocking=False)
        ingest_router._INGEST_LOCK.release()
