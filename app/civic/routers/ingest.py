"""POST /civic/ingest — pull Philadelphia Matters from Legistar (idempotent, gated).

Adapted from AwardGuard's ``backend/app/routers/ingest.py``. This triggers an
expensive pipeline (paginated network fetch, ONNX embedding, DB upserts), so it
is NOT part of the public surface:

  * Gated behind a shared secret (``X-Ingest-Token`` vs ``settings.ingest_token``).
    If ``ingest_token`` is unset the endpoint is DISABLED entirely (503), so a
    fresh deploy is never open to anonymous ingest spam.
  * A single-flight lock makes concurrent calls fail fast (409) instead of piling
    up parallel fetch/embed/upsert runs.
  * The raw exception is logged server-side but never echoed to the client.
"""

from __future__ import annotations

import logging
import secrets
import threading

from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.civic.schemas import IngestResponse

logger = logging.getLogger("docket")

router = APIRouter(prefix="/civic")

# Single-flight guard: only one ingest may run at a time. A non-blocking acquire
# lets a second concurrent request fail fast (409) instead of queueing behind a
# multi-second fetch/embed/upsert run and holding a connection/worker.
_INGEST_LOCK = threading.Lock()


def _authorize(token: str | None) -> None:
    """Reject the request unless a configured ingest token matches.

    Disabled-by-default: with no ``ingest_token`` set, ingest is unavailable over
    HTTP (503) rather than open to everyone. A set-but-mismatched token is 401.
    """

    if not settings.ingest_token:
        raise HTTPException(status_code=503, detail="ingest endpoint is disabled")
    # Constant-time compare so a plain != can't leak the token length/prefix via a
    # timing side-channel (compare_digest also handles the missing-token case).
    if not token or not secrets.compare_digest(token, settings.ingest_token):
        raise HTTPException(status_code=401, detail="invalid or missing ingest token")


@router.post("/ingest", response_model=IngestResponse)
def ingest(x_ingest_token: str | None = Header(default=None)) -> IngestResponse:
    """Run the full fetch -> normalize -> chunk -> embed -> upsert pipeline (gated).

    Requires a valid ``X-Ingest-Token`` header. Returns the number of documents
    ingested. Concurrent calls get 409; pipeline failures get a generic 500 (the
    detail is logged server-side, not returned to the caller).
    """

    _authorize(x_ingest_token)

    if not _INGEST_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="an ingest is already running")
    try:
        # Imported lazily so mounting this router never pulls in the DB/ONNX stack.
        from app.civic.ingest import run_ingest

        count = run_ingest()
    except Exception as exc:  # noqa: BLE001
        logger.exception("civic ingest failed")
        raise HTTPException(status_code=500, detail="ingest failed") from exc
    finally:
        _INGEST_LOCK.release()
    return IngestResponse(ingested=count)
