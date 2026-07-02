"""FastAPI routers for the civic slice.

  * ``ingest`` — POST /civic/ingest (token-gated; 503 when no token configured).
  * ``ask``    — POST /civic/ask (cite-or-refuse grounded answer).

Both are wired into the app in ``app.main`` without disturbing the existing
tasks/auth/health routes.
"""
