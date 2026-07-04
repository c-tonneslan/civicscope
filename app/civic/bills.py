"""Browse/list view over the civic corpus (no LLM, pure SQL).

Backs ``GET /civic/bills``: a paginated, filterable listing of Matters — the
kiosk "browse" surface alongside the grounded Q&A. Filters are optional and
combine with AND; every user value is a bound parameter, never interpolated.
``?topic=`` matches Matters whose chunks hit a ``plainto_tsquery`` over the
same content-term reduction the insights briefings use.
Thin and DB-backed so it unit-tests with a mocked cursor.
"""

from __future__ import annotations

from datetime import date

from app.civic.db import get_conn


def list_bills(
    q: str | None = None,
    status: str | None = None,
    jurisdiction: str | None = None,
    since: date | None = None,
    limit: int = 50,
    offset: int = 0,
    sponsor: str | None = None,
    topic: str | None = None,
) -> dict:
    """A page of Matters (newest first), plus a ``total`` for pagination.

    The ``clauses`` are fixed literal fragments chosen by which filters are
    present; all values bind as %s params. ``q`` is a substring match — the
    wildcards live in the bound value (``f"%{q}%"``), never in the SQL string.
    ``sponsor`` filters to Matters carrying a matching ``civic_sponsors.name``
    via a correlated EXISTS subquery, so the single-table count/select and
    totals are unchanged (a JOIN would duplicate multi-sponsor rows).
    ``topic`` matches the same way over ``civic_chunks``, reducing the topic to
    content terms (``_content_terms``) fed to ``plainto_tsquery`` — one bound
    param, one row per document.
    Ordered ``intro_date DESC NULLS LAST, id DESC`` so pagination is stable
    across the nullable ``intro_date``.
    """

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    clauses: list[str] = []
    params: list = []
    if q:
        clauses.append("title ILIKE %s")
        params.append(f"%{q}%")
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    if jurisdiction is not None:
        clauses.append("jurisdiction = %s")
        params.append(jurisdiction)
    if since is not None:
        clauses.append("intro_date >= %s")
        params.append(since)
    if sponsor:
        clauses.append(
            "EXISTS (SELECT 1 FROM civic_sponsors s "
            "WHERE s.document_id = civic_documents.id AND s.name = %s)"
        )
        params.append(sponsor)
    if topic:
        from app.civic.retrieval import _content_terms

        clauses.append(
            "EXISTS (SELECT 1 FROM civic_chunks c "
            "WHERE c.document_id = civic_documents.id "
            "AND c.tsv @@ plainto_tsquery('english', %s))"
        )
        params.append(_content_terms(topic))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM civic_documents {where};", tuple(params))
        total = cur.fetchone()[0]

        cur.execute(
            "SELECT file_no, title, status, doc_type, intro_date "
            f"FROM civic_documents {where} "
            "ORDER BY intro_date DESC NULLS LAST, id DESC LIMIT %s OFFSET %s;",
            tuple(params) + (limit, offset),
        )
        rows = cur.fetchall()

    bills = [
        {"file_no": file_no, "title": title, "status": status_,
         "doc_type": doc_type, "intro_date": intro_date}
        for file_no, title, status_, doc_type, intro_date in rows
    ]
    return {"bills": bills, "total": total, "limit": limit, "offset": offset}
