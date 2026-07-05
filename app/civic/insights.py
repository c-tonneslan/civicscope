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
                SELECT count(*)
                FROM civic_documents d
                WHERE to_tsvector('english', coalesce(d.title, '')) @@ to_tsquery('english', %s)
                  AND (%s::date IS NULL OR d.intro_date >= %s)
                  {extra};
                """,
                params,
            )
            items.append({"topic": label, "bills": cur.fetchone()[0]})

    items.sort(key=lambda it: it["bills"], reverse=True)
    return {"since": since, "topics": items}


def topic_trends(jurisdiction: str | None = None) -> dict:
    """Per-topic bill counts BY YEAR — the multi-year activity trend.

    One query per curated topic buckets its (title-matched) bills by introduction
    year. Returns a dense year axis (every year from first to last, zero-filled) so
    the client can render a comparable series per topic without gap handling.
    """

    extra = "" if jurisdiction is None else "AND d.jurisdiction = %s"

    topics: list[dict] = []
    years: set[int] = set()
    with get_conn() as conn, conn.cursor() as cur:
        for label, query in TRACKED_TOPICS:
            params = (query,) if jurisdiction is None else (query, jurisdiction)
            cur.execute(
                f"""
                SELECT EXTRACT(YEAR FROM d.intro_date)::int AS yr, count(*)
                FROM civic_documents d
                WHERE to_tsvector('english', coalesce(d.title, '')) @@ to_tsquery('english', %s)
                  AND d.intro_date IS NOT NULL
                  {extra}
                GROUP BY yr ORDER BY yr;
                """,
                params,
            )
            counts = {yr: n for yr, n in cur.fetchall()}
            years.update(counts)
            topics.append({"topic": label, "counts": counts})

    axis = list(range(min(years), max(years) + 1)) if years else []
    return {
        "years": axis,
        "topics": [
            {"topic": t["topic"], "series": [t["counts"].get(y, 0) for y in axis]}
            for t in topics
        ],
    }


def top_sponsors(
    topic: str | None = None,
    jurisdiction: str | None = None,
    since: date | None = None,
    limit: int = 10,
) -> dict:
    """Most active sponsors, optionally scoped by topic / jurisdiction / since.

    ``bills`` counts distinct Matters a person sponsored under the scope — so with
    ``topic="housing"`` it answers "who leads on housing?". Built from the
    ``civic_sponsors`` enrichment table joined to documents (and, for a topic, to
    the matching chunks).
    """

    # Lazy import: reuse the same content-term reduction the lexical arm uses so a
    # topic here means the same thing it does in retrieval / topic_activity.
    from app.civic.retrieval import _content_terms

    clauses: list[str] = []
    params: list = []
    if topic:
        # Topic membership is decided by the bill's TITLE (its human summary), not
        # incidental full-text mentions — matching the body over-counts (a bill that
        # says "housing" once anywhere becomes a "housing bill").
        clauses.append(
            "to_tsvector('english', coalesce(d.title, '')) @@ plainto_tsquery('english', %s)"
        )
        params.append(_content_terms(topic))
    if jurisdiction is not None:
        clauses.append("d.jurisdiction = %s")
        params.append(jurisdiction)
    if since is not None:
        clauses.append("d.intro_date >= %s")
        params.append(since)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT s.name, count(DISTINCT d.id) AS bills
            FROM civic_sponsors s
            JOIN civic_documents d ON d.id = s.document_id
            {where}
            GROUP BY s.name
            ORDER BY bills DESC, s.name
            LIMIT %s;
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    return {
        "topic": topic,
        "jurisdiction": jurisdiction,
        "sponsors": [{"name": name, "bills": bills} for name, bills in rows],
    }


def bill_timeline(file_no: str, jurisdiction: str | None = None) -> dict:
    """The action history (legislative timeline) for one bill, chronologically.

    Resolves ``file_no`` (optionally within a jurisdiction) to a document, then
    returns its ordered history. ``found`` is False when no such bill exists.
    """

    clause = "" if jurisdiction is None else " AND jurisdiction = %s"
    params: tuple = (file_no,) if jurisdiction is None else (file_no, jurisdiction)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, jurisdiction, title, status, url FROM civic_documents "
            f"WHERE file_no = %s{clause} ORDER BY intro_date DESC NULLS LAST LIMIT 1;",
            params,
        )
        row = cur.fetchone()
        if row is None:
            return {"file_no": file_no, "found": False, "jurisdiction": jurisdiction,
                    "title": None, "status": None, "url": None, "timeline": []}
        doc_id, jz, title, status, url = row
        cur.execute(
            "SELECT action_date, action_name, passed_flag FROM civic_history "
            "WHERE document_id = %s ORDER BY action_date NULLS LAST, seq;",
            (doc_id,),
        )
        timeline = [
            {"action_date": d, "action": a, "passed": p}
            for d, a, p in cur.fetchall()
        ]

    return {"file_no": file_no, "found": True, "jurisdiction": jz, "title": title,
            "status": status, "url": url, "timeline": timeline}


def legislative_velocity(
    jurisdiction: str | None = None, since: date | None = None
) -> dict:
    """How fast enacted legislation moves: count + avg days intro -> final action.

    Joins each enacted bill to the latest date in its history; the day count is the
    DATE subtraction Postgres does natively. Returns ``avg_days_to_enact = None``
    when nothing qualifies (so the caller can render "n/a" rather than 0).
    """

    where = ["d.status = 'ENACTED'", "d.intro_date IS NOT NULL", "h.last_action IS NOT NULL"]
    params: list = []
    if jurisdiction is not None:
        where.append("d.jurisdiction = %s")
        params.append(jurisdiction)
    if since is not None:
        where.append("d.intro_date >= %s")
        params.append(since)
    wsql = " AND ".join(where)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) AS enacted,
                   round(avg(h.last_action - d.intro_date))::int AS avg_days
            FROM civic_documents d
            JOIN (
                SELECT document_id, max(action_date) AS last_action
                FROM civic_history GROUP BY document_id
            ) h ON h.document_id = d.id
            WHERE {wsql};
            """,
            tuple(params),
        )
        enacted, avg_days = cur.fetchone()

    return {
        "jurisdiction": jurisdiction,
        "enacted": enacted or 0,
        "avg_days_to_enact": avg_days,  # None when no enacted bills in scope
    }


def bill_rollcall(file_no: str, jurisdiction: str | None = None) -> dict:
    """The most recent roll-call for a bill: each member's vote + the tally."""

    clause = "" if jurisdiction is None else " AND jurisdiction = %s"
    params: tuple = (file_no,) if jurisdiction is None else (file_no, jurisdiction)

    empty = {"file_no": file_no, "found": False, "title": None, "action": None,
             "action_date": None, "tally": {}, "votes": []}

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, title FROM civic_documents "
            f"WHERE file_no = %s{clause} ORDER BY intro_date DESC NULLS LAST LIMIT 1;",
            params,
        )
        row = cur.fetchone()
        if row is None:
            return empty
        doc_id, title = row
        # Latest action that recorded a roll-call for this bill.
        cur.execute(
            "SELECT history_ref, action_name, action_date FROM civic_votes "
            "WHERE document_id = %s ORDER BY action_date DESC NULLS LAST, "
            "history_ref DESC LIMIT 1;",
            (doc_id,),
        )
        latest = cur.fetchone()
        if latest is None:
            return {**empty, "found": True, "title": title}
        href, action, action_date = latest
        cur.execute(
            "SELECT person_name, vote_value FROM civic_votes "
            "WHERE document_id = %s AND history_ref = %s ORDER BY person_name;",
            (doc_id, href),
        )
        votes = [{"person": p, "vote": v} for p, v in cur.fetchall()]

    tally: dict[str, int] = {}
    for v in votes:
        key = v["vote"] or "Unknown"
        tally[key] = tally.get(key, 0) + 1
    return {"file_no": file_no, "found": True, "title": title, "action": action,
            "action_date": action_date, "tally": tally, "votes": votes}


def bill_sponsors(file_no: str, jurisdiction: str | None = None) -> dict:
    """The sponsors of one bill, in sponsorship order (seq 0 = primary)."""

    clause = "" if jurisdiction is None else " AND jurisdiction = %s"
    params: tuple = (file_no,) if jurisdiction is None else (file_no, jurisdiction)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM civic_documents "
            f"WHERE file_no = %s{clause} ORDER BY intro_date DESC NULLS LAST LIMIT 1;",
            params,
        )
        row = cur.fetchone()
        if row is None:
            return {"file_no": file_no, "found": False, "jurisdiction": jurisdiction,
                    "sponsors": []}
        cur.execute(
            "SELECT name, seq FROM civic_sponsors "
            "WHERE document_id = %s ORDER BY seq NULLS LAST, name;",
            (row[0],),
        )
        sponsors = [{"name": n, "seq": s} for n, s in cur.fetchall()]

    return {"file_no": file_no, "found": True, "jurisdiction": jurisdiction,
            "sponsors": sponsors}


def member_record(
    person: str, topic: str | None = None, jurisdiction: str | None = None
) -> dict:
    """A member's voting record: distinct bills per vote value, optionally on a topic."""

    from app.civic.retrieval import _content_terms

    where = []
    params: list = []
    if topic:
        # Title-based topic membership (see top_sponsors) — avoids counting a bill
        # that merely mentions the topic once in its body.
        where.append(
            "to_tsvector('english', coalesce(d.title, '')) @@ plainto_tsquery('english', %s)"
        )
        params.append(_content_terms(topic))
    where.append("v.person_name = %s")
    params.append(person)
    if jurisdiction is not None:
        where.append("d.jurisdiction = %s")
        params.append(jurisdiction)
    wsql = " AND ".join(where)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT v.vote_value, count(DISTINCT d.id) AS bills
            FROM civic_votes v
            JOIN civic_documents d ON d.id = v.document_id
            WHERE {wsql}
            GROUP BY v.vote_value ORDER BY bills DESC;
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    return {"person": person, "topic": topic, "jurisdiction": jurisdiction,
            "record": [{"vote": val or "Unknown", "bills": n} for val, n in rows]}


def list_jurisdictions() -> dict:
    """List every ingested jurisdiction (Legistar client slug) with its bill count."""

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT jurisdiction, count(*) FROM civic_documents "
            "GROUP BY jurisdiction ORDER BY count(*) DESC;"
        )
        rows = cur.fetchall()
    return {"jurisdictions": [{"slug": slug, "documents": n} for slug, n in rows]}
