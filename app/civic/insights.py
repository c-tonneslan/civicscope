"""Insight aggregates over the civic corpus (no LLM, pure SQL).

Two read-only views the ``/civic/insights`` routes expose:

  * ``corpus_overview`` — a quantitative snapshot: how many Matters, broken down
    by type and by legislative status, monthly introduction volume, and the date
    span covered. Answers "what is in here and how active is Council?".
  * ``topic_activity`` — bill counts for a CURATED set of policy topics
    (housing, zoning, transit, ...), optionally since a date. This is the
    "legislation on tracked topics" view: unsupervised term-frequency over civic
    text is dominated by procedural boilerplate, so we count against a hand-built
    topic->keyword map instead, which is interpretable and stable.

All heavy lifting is SQL aggregation over ``civic_documents`` / ``civic_chunks``;
these functions are thin and DB-backed so they unit-test with a mocked cursor.
"""

from __future__ import annotations

from datetime import date

from app.civic.db import get_conn

# Curated policy topics -> a Postgres ``to_tsquery`` expression (single-word
# lexemes OR-ed together). Kept small and legible on purpose: this is editorial
# ("what beats does Council cover?"), so a reviewer can see and adjust exactly what
# each topic matches. Terms are single words so ``to_tsquery`` never needs phrase
# operators; stemming ('housing' also matches 'housed') is Postgres's job.
TRACKED_TOPICS: list[tuple[str, str]] = [
    ("Housing", "housing | affordable | rent | eviction | tenant | landlord"),
    ("Zoning & Land Use", "zoning | rezone | overlay | redevelopment | subdivision"),
    ("Transit & Streets", "transit | septa | traffic | parking | bicycle | pedestrian"),
    ("Public Safety", "police | crime | firearm | gun | violence | safety"),
    ("Education", "school | education | student | teacher | scholarship"),
    ("Budget & Taxes", "budget | tax | appropriation | fiscal | levy | revenue"),
    ("Health", "health | hospital | opioid | medical | mental"),
    ("Environment", "environment | climate | energy | recycling | stormwater"),
    ("Jobs & Labor", "worker | wage | employment | labor | union"),
]


def _rows_as_count_items(rows: list[tuple]) -> list[dict]:
    """Map ``(label, count)`` rows into ``{"label", "count"}`` dicts.

    A NULL label (e.g. a Matter with no status) is surfaced as "Unknown" rather
    than dropped, so the breakdown totals still reconcile with the grand total.
    """

    return [{"label": (label if label is not None else "Unknown"), "count": count}
            for label, count in rows]


def corpus_overview(jurisdiction: str | None = None) -> dict:
    """Quantitative snapshot of the corpus, optionally scoped to one jurisdiction.

    The ``where``/``and_`` fragments are fixed literals (never user text) that add
    the jurisdiction predicate only when one is requested; the value itself is
    always a bound parameter.
    """

    where = "" if jurisdiction is None else "WHERE jurisdiction = %s"
    and_ = "" if jurisdiction is None else "AND jurisdiction = %s"
    p: tuple = () if jurisdiction is None else (jurisdiction,)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM civic_documents {where};", p)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT doc_type, count(*) FROM civic_documents {where} "
            "GROUP BY doc_type ORDER BY count(*) DESC;", p
        )
        by_type = _rows_as_count_items(cur.fetchall())

        cur.execute(
            f"SELECT status, count(*) FROM civic_documents {where} "
            "GROUP BY status ORDER BY count(*) DESC;", p
        )
        by_status = _rows_as_count_items(cur.fetchall())

        # Recent monthly introduction volume (newest first, last 12 months present).
        cur.execute(
            "SELECT to_char(date_trunc('month', intro_date), 'YYYY-MM') AS m, count(*) "
            f"FROM civic_documents WHERE intro_date IS NOT NULL {and_} "
            "GROUP BY m ORDER BY m DESC LIMIT 12;", p
        )
        by_month = _rows_as_count_items(cur.fetchall())

        cur.execute(f"SELECT min(intro_date), max(intro_date) FROM civic_documents {where};", p)
        earliest, latest = cur.fetchone()

    return {
        "total_documents": total,
        "by_type": by_type,
        "by_status": by_status,
        "by_month": by_month,
        "earliest_intro_date": earliest,
        "latest_intro_date": latest,
    }


def topic_activity(since: date | None = None, jurisdiction: str | None = None) -> dict:
    """Bill counts per curated topic, optionally scoped by ``since`` and jurisdiction.

    One count query per topic (each hits the GIN-indexed ``tsv``), then sorted by
    volume. ``count(DISTINCT d.id)`` so a bill with several matching chunks is
    counted once. Returned sorted busiest-first.
    """

    extra = "" if jurisdiction is None else "AND d.jurisdiction = %s"

    items: list[dict] = []
    with get_conn() as conn, conn.cursor() as cur:
        for label, query in TRACKED_TOPICS:
            params = (query, since, since)
            if jurisdiction is not None:
                params = (query, since, since, jurisdiction)
            cur.execute(
                f"""
                SELECT count(DISTINCT d.id)
                FROM civic_documents d
                JOIN civic_chunks c ON c.document_id = d.id
                WHERE c.tsv @@ to_tsquery('english', %s)
                  AND (%s::date IS NULL OR d.intro_date >= %s)
                  {extra};
                """,
                params,
            )
            items.append({"topic": label, "bills": cur.fetchone()[0]})

    items.sort(key=lambda it: it["bills"], reverse=True)
    return {"since": since, "topics": items}


def list_jurisdictions() -> dict:
    """List every ingested jurisdiction (Legistar client slug) with its bill count."""

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT jurisdiction, count(*) FROM civic_documents "
            "GROUP BY jurisdiction ORDER BY count(*) DESC;"
        )
        rows = cur.fetchall()
    return {"jurisdictions": [{"slug": slug, "documents": n} for slug, n in rows]}
