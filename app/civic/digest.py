"""What's-new digest over the civic corpus (no LLM, pure SQL).

One read-only view the ``/civic/insights/recent`` route exposes: the bills that
moved lately, so the app opens with content instead of a blank Ask box. It pairs
two lists —

  * recently INTRODUCED — Matters whose ``intro_date`` falls in the window;
  * recently ENACTED — Matters at status ``ENACTED`` whose latest action (from
    ``civic_history``) falls in the window.

Both are thin SQL over ``civic_documents`` (+ ``civic_history`` for the enacted
last-action date), so they unit-test with a mocked cursor.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.civic.db import get_conn


def _rows_to_items(rows: list[tuple], enacted: bool) -> list[dict]:
    """Shape ``(file_no, title, status, intro_date[, last_action])`` rows into items.

    ``last_action_date`` is None for the introduced list and the max action date
    (last tuple element) for the enacted list.
    """

    return [
        {
            "file_no": r[0],
            "title": r[1],
            "status": r[2],
            "intro_date": r[3],
            "last_action_date": r[4] if enacted else None,
        }
        for r in rows
    ]


def recent_activity(
    jurisdiction: str | None = None, days: int = 14, limit: int = 10
) -> dict:
    """Recently introduced + recently enacted bills, optionally scoped to one city.

    The ``extra`` fragment is a fixed literal (never user text) that adds the
    jurisdiction predicate only when one is requested; the slug itself is always a
    bound parameter. ``since`` is the start of the window (``days`` back from today).
    """

    since = date.today() - timedelta(days=days)
    extra = "" if jurisdiction is None else "AND d.jurisdiction = %s"

    intro_params: tuple = (since,) if jurisdiction is None else (since, jurisdiction)
    intro_params += (limit,)
    enacted_params: tuple = (since,) if jurisdiction is None else (since, jurisdiction)
    enacted_params += (limit,)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT file_no, title, status, intro_date
            FROM civic_documents d
            WHERE d.intro_date >= %s {extra}
            ORDER BY d.intro_date DESC NULLS LAST, d.id DESC
            LIMIT %s;
            """,
            intro_params,
        )
        introduced = _rows_to_items(cur.fetchall(), enacted=False)

        cur.execute(
            f"""
            SELECT d.file_no, d.title, d.status, d.intro_date, h.last_action
            FROM civic_documents d
            JOIN (
                SELECT document_id, max(action_date) AS last_action
                FROM civic_history GROUP BY document_id
            ) h ON h.document_id = d.id
            WHERE d.status = 'ENACTED' AND h.last_action >= %s {extra}
            ORDER BY h.last_action DESC NULLS LAST, d.id DESC
            LIMIT %s;
            """,
            enacted_params,
        )
        enacted = _rows_to_items(cur.fetchall(), enacted=True)

    return {
        "jurisdiction": jurisdiction,
        "days": days,
        "introduced": introduced,
        "enacted": enacted,
    }
