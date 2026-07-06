"""Token-streamed cite-or-refuse answers (NDJSON) — a streaming twin of /ask.

Reuses the answer layer's grounding + verification wholesale: retrieval, the
system/user prompt, and ``verify_citations`` all come from ``app.civic.answer``.
The only new behaviour is that tokens are emitted live and the trustworthiness
verdict is deferred to a terminal FINAL event.

The contract is identical to ``answer_question``: the SAME cite-or-refuse
guarantee holds, because verification runs on the fully-accumulated answer AFTER
the model's stream closes (never on partial text). A hallucinated or uncited
streamed answer collapses to ``refused: true`` in the final event, and the UI
treats that event as authoritative — partial tokens can never leak an ungrounded
claim as a trusted answer.

Event shapes (one compact JSON object per NDJSON line):
  * {"type": "token", "text": str}                       — a live answer fragment
  * {"type": "final", "answer": str,
     "citations": [{"file_no", "title"}], "refused": bool} — the verdict

Every failure mode (DB down, Ollama down, generic synth error, anthropic-no-key,
empty retrieval, model refusal, no groundable citation) degrades to a single
FINAL refused event and the generator never raises, so the endpoint never 500s.
"""

from __future__ import annotations

import json
from typing import Iterator

from app.config import settings
from app.civic.answer import (
    DB_DOWN_TEXT,
    NO_KEY_TEXT,
    OLLAMA_DOWN_TEXT,
    REFUSAL_TEXT,
    TOP_K,
    _SYSTEM_PROMPT,
    _build_user_prompt,
    _is_connection_error,
    retrieve,
    synthesize_chat,
    verify_citations,
)
from app.civic.retrieval import RetrievedChunk
from app.civic.schemas import Citation


def _line(event: dict) -> str:
    """Serialise one event to a compact NDJSON line."""

    return json.dumps(event, separators=(",", ":")) + "\n"


def _token(text: str) -> str:
    return _line({"type": "token", "text": text})


def _final(answer: str, citations: list[Citation], refused: bool) -> str:
    return _line(
        {
            "type": "final",
            "answer": answer,
            "citations": [{"file_no": c.file_no, "title": c.title} for c in citations],
            "refused": refused,
        }
    )


def _refused_final(answer: str) -> str:
    """Terminal refusal — no citations, refused true."""

    return _final(answer, [], True)


def _ollama_stream(system_prompt: str, user_prompt: str) -> Iterator[str]:
    """Yield message-content fragments from Ollama /api/chat with stream=True.

    ``httpx`` is imported lazily so the module imports without a running Ollama.
    Parses each NDJSON line's ``message.content``, ignores blank/non-JSON
    keepalive lines, and stops on ``done``. Raises on transport/HTTP errors;
    the caller degrades those to a graceful refusal. Temperature 0 stays
    deterministic like the non-streaming path.
    """

    import httpx

    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": True,
        "options": {"temperature": 0.0},
    }
    with httpx.stream(
        "POST", f"{settings.ollama_host}/api/chat", json=payload, timeout=120.0
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or not line.strip():
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            fragment = (data.get("message") or {}).get("content") or ""
            if fragment:
                yield fragment
            if data.get("done"):
                break


def stream_answer(question: str, jurisdiction: str | None = None) -> Iterator[str]:
    """Retrieve -> stream tokens -> verify -> final event, as NDJSON lines.

    Mirrors ``answer_question``'s control flow and guard ordering exactly, but
    emits tokens live and defers the cite-or-refuse verdict to a terminal FINAL
    event. Always ends on a ``final``; never raises.
    """

    provider = settings.llm_provider.lower()

    # anthropic-but-no-key: short-circuit BEFORE retrieval, like answer_question.
    if provider == "anthropic" and not getattr(settings, "anthropic_api_key", None):
        yield _refused_final(NO_KEY_TEXT)
        return

    # Retrieval hits the civic Postgres. Degrade a DB/connection failure to a
    # refused final rather than raising out of the streaming generator.
    try:
        chunks = retrieve(question, top_k=TOP_K, jurisdiction=jurisdiction)
    except Exception as exc:  # noqa: BLE001 - never crash the stream
        yield _refused_final(f"{DB_DOWN_TEXT} (retrieval error: {type(exc).__name__})")
        return

    if not chunks:
        yield _refused_final(REFUSAL_TEXT)
        return

    # Same citation key answer_question uses: ``file_no or source_ref`` (Legistar
    # MatterFile is legitimately null on real records, so keying only off file_no
    # would force-refuse an otherwise-grounded answer built from null-file_no bills).
    def _cite_key(c: RetrievedChunk) -> str:
        return c.file_no or c.source_ref

    allowed = {_cite_key(c) for c in chunks}
    title_by_file_no = {_cite_key(c): (c.title or "") for c in chunks}

    system_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(question, chunks)

    # Accumulate the full answer while emitting each fragment live. Anthropic is
    # intentionally non-streaming (single synthesize_chat call emitted as one
    # token) to keep the new network surface to Ollama only.
    raw = ""
    try:
        if provider == "ollama":
            for fragment in _ollama_stream(system_prompt, user_prompt):
                raw += fragment
                yield _token(fragment)
        else:
            raw = synthesize_chat(system_prompt, user_prompt)
            if raw:
                yield _token(raw)
    except Exception as exc:  # noqa: BLE001 - never crash the stream
        if provider == "ollama" and _is_connection_error(exc):
            yield _refused_final(OLLAMA_DOWN_TEXT)
            return
        yield _refused_final(f"{REFUSAL_TEXT} (synthesis error: {type(exc).__name__})")
        return

    # Post-stream verification is IDENTICAL to answer_question, run on the fully
    # accumulated answer. Explicit refusal phrase anywhere collapses the whole
    # thing to a clean refusal.
    if REFUSAL_TEXT.lower() in raw.lower():
        yield _refused_final(REFUSAL_TEXT)
        return

    verified = verify_citations(raw, allowed)
    if not verified:
        yield _refused_final(REFUSAL_TEXT)
        return

    citations = [
        Citation(file_no=file_no, title=title_by_file_no.get(file_no, ""))
        for file_no in verified
    ]
    yield _final(raw, citations, False)
