"""POST /civic/ask/stream — token-streamed cite-or-refuse answer as NDJSON.

A streaming twin of ``ask.py``: same ``AskRequest`` validation (422 on
blank/oversized/wrong-type for free), but the answer is streamed token-by-token
over a Starlette ``StreamingResponse`` and the trustworthiness verdict arrives in
a terminal FINAL event. Thin — it delegates to ``app.civic.streaming.stream_answer``.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.civic.schemas import AskRequest

router = APIRouter(prefix="/civic")


@router.post("/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """Stream a grounded answer as newline-delimited JSON events.

    Never raises for the normal failure modes (DB down, Ollama down, refusal):
    those come back as a single ``final`` event with ``refused: true``. The
    response starts 200 and always ends on a ``final``.
    """

    # Imported lazily so mounting this router never pulls in the retrieval/DB
    # stack at import time (keeps app startup and tests import-light).
    from app.civic.streaming import stream_answer

    return StreamingResponse(
        stream_answer(req.question, jurisdiction=req.jurisdiction),
        media_type="application/x-ndjson",
    )
