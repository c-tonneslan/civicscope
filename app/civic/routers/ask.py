"""POST /civic/ask — cite-or-refuse answer over Philadelphia legislation.

Adapted from AwardGuard's ``backend/app/routers/ask.py``. Thin: it validates the
request and delegates to ``app.civic.answer.answer_question``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.civic.schemas import AskRequest, AskResponse

router = APIRouter(prefix="/civic")


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """Answer a Philadelphia-legislation question, grounded with verified citations.

    Never raises for the normal failure modes (Ollama down, model refusal,
    synthesis error) — those come back as ``refused: true`` with an explanatory
    ``answer`` so the caller can always render something useful.
    """

    # Imported lazily so mounting this router never pulls in the retrieval/DB stack
    # at import time (keeps app startup and tests import-light).
    from app.civic.answer import answer_question

    return answer_question(req.question)
