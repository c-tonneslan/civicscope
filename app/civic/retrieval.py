"""Hybrid retrieval over civic_chunks: dense (pgvector) + lexical (tsvector) + RRF.

The load-bearing search algorithm, adapted from AwardGuard's
``backend/app/core/retrieval.py``. In one breath:

    Pure semantic search (embeddings) is great at "this means the same thing" but
    can miss exact civic terms (a bill number, a body name). Pure lexical search
    (Postgres full-text) nails exact terms but is blind to paraphrase. We run
    BOTH over ``civic_chunks``, then combine the two rankings with Reciprocal Rank
    Fusion (RRF) — a simple, robust, score-scale-free merge.

Domain adaptation from AwardGuard: retrieve over ``civic_chunks`` (keyed by chunk
id) instead of ``sections``; hydrate results back to their parent
``civic_documents`` (file_no + title) so the answer layer can cite bills.

The ``reciprocal_rank_fusion`` function is PURE (lists in, list out) so it is
unit-tested with no DB / network / LLM — see tests/test_civic_rrf.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from pgvector.psycopg import register_vector

from app.civic.db import get_conn
from app.civic.embeddings import embed_query


@dataclass
class RetrievedChunk:
    """A retrieved civic chunk joined to its parent document's citation fields.

    Distinct from ``CivicChunk`` (the ingest-side record): retrieval doesn't need
    the embedding on the way out, but DOES need the parent document's ``title`` so
    the answer layer can build a ``Citation`` (file_no + title) without a second
    round-trip.
    """

    chunk_id: int
    source_ref: str
    file_no: str | None
    title: str | None
    chunk_index: int
    text: str
    # Parent-document metadata carried through so the answer layer can show the
    # AUTHORITATIVE status/type/intro date in the grounding context. Without the
    # status the model has no way to rebut a false "the law that just passed"
    # premise about a bill that is actually still in committee.
    doc_type: str | None = None
    status: str | None = None
    intro_date: date | None = None

# RRF constant. k=60 is the value from the original Cormack et al. paper and the
# de-facto default; it dampens top-rank influence so no single list dominates.
# (Larger k => flatter per-rank contribution; smaller k => the #1 of each list
# dominates.)
RRF_K = 60

# How many candidates to pull from EACH retriever before fusing.
CANDIDATE_K = 20

# How many fused results to actually hand to the LLM as grounding context.
DEFAULT_TOP_K = 6

# Fusion weights (lexical, dense). After the domain-stopword sharpening
# (``_DOMAIN_STOPWORDS``), the lexical arm is high-precision for civic topic
# queries; the dense arm — cosine similarity over short, formulaic bill titles — is
# noisier and tends to surface off-topic procedural records (budget speeches,
# transmittal cover-letters). We therefore trust the lexical ranking more: it
# contributes full weight, the dense ranking half. Dense is NOT dropped — it still
# supplies paraphrase recall for questions whose wording matches no title token —
# only down-weighted so it breaks ties rather than dominating the top-k.
LEXICAL_WEIGHT = 1.0
DENSE_WEIGHT = 0.5


# ===========================================================================
# Pure fusion (unit-tested, no I/O)
# ===========================================================================


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    k: int = RRF_K,
    weights: list[float] | None = None,
) -> list[tuple[int, float]]:
    """Fuse several ranked lists of chunk ids into one ranking via (weighted) RRF.

    RRF score for a document d:

        score(d) = Σ_over_lists  w_list / (k + rank_in_list(d))

    where ``rank_in_list`` is the **1-based** position of d in that list (the top
    item is rank 1) and ``w_list`` is that list's weight. A document missing from a
    list contributes nothing from that list.

    Args:
        ranked_lists: e.g. ``[dense_ids, lexical_ids]``; each inner list is
            ordered best-first and contains chunk ids.
        k: the RRF damping constant (default 60).
        weights: optional per-list multipliers, positionally aligned with
            ``ranked_lists``. Defaults to 1.0 for every list (classic unweighted
            RRF), so a caller that trusts one retriever more can bias the fusion
            without the pure math changing for existing callers.

    Returns:
        ``[(chunk_id, fused_score), ...]`` ordered best-first.

    Determinism note: ties in fused score are broken by chunk id (ascending) so
    the output is stable and testable.
    """

    if weights is None:
        weights = [1.0] * len(ranked_lists)

    scores: dict[int, float] = {}

    # Walk each list; the position within the list IS the rank.
    for ranked, weight in zip(ranked_lists, weights):
        for index, chunk_id in enumerate(ranked):
            rank = index + 1  # 1-based: first element is rank 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)

    # Sort by score desc, then chunk id asc for a deterministic tiebreak.
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


# ===========================================================================
# The two retrievers (DB-backed)
# ===========================================================================


def _dense_candidates(conn, query_vector: list[float], k: int) -> list[int]:
    """Top-k chunk ids by cosine distance (pgvector ``<=>`` operator).

    ``<=>`` is pgvector's cosine *distance* (smaller = more similar), so ascending
    order = best first. The bound query vector is a plain ``list[float]``; pgvector
    has no ``vector <=> double precision[]`` operator, so we cast the parameter with
    ``%s::vector`` to coerce the array literal to the vector type before the
    distance operator sees it.
    """

    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM civic_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (query_vector, k),
        )
        return [row[0] for row in cur.fetchall()]


# Civic-generic terms that appear in nearly every record ("bill", "ordinance",
# "council") AND in the scaffolding of most questions ("what recent legislation
# concerning ..."). Standard English stop-words are already dropped by
# ``plainto_tsquery('english', ...)``; these are the DOMAIN stop-words it can't
# know about. Left in the lexical query they match *everything* — a question about
# "convenience fees" otherwise ranks every procedural communication that merely
# contains the word "bill" above the actual fee ordinance. Stripping them lets the
# DISCRIMINATIVE topic words ("convenience", "fees", "zoning") drive the lexical
# rank. The dense (semantic) arm still sees the FULL query, so paraphrase recall is
# untouched — this only sharpens the lexical arm.
_DOMAIN_STOPWORDS = frozenset(
    {
        "legislation", "legislative", "legislature", "bill", "bills", "ordinance",
        "ordinances", "resolution", "resolutions", "council", "councilmember",
        "city", "philadelphia", "recent", "recently", "concern", "concerns",
        "concerning", "relate", "relates", "related", "relating", "honor",
        "honors", "honoring", "message", "transmit", "transmitting", "advise",
        "advising", "matter", "matters", "pass", "passed", "law", "laws",
        "committee", "propose", "proposed", "amend", "amending",
    }
)

# Word = a run of letters or digits (Unicode-aware). Digits are kept on purpose:
# a bill number ("260640") is one of the most discriminative things a question can
# contain. Underscores/punctuation are the separators.
_WORD_RE = re.compile(r"[^\W_]+")


def _content_terms(query: str) -> str:
    """Reduce a natural-language question to its discriminative topic words.

    Drops civic-generic terms (see ``_DOMAIN_STOPWORDS``) and returns the survivors
    space-joined for ``plainto_tsquery``. If nothing survives — a question built
    only of generic terms — returns the original ``query`` unchanged so the lexical
    arm still runs rather than searching for an empty string.
    """

    terms = [w for w in _WORD_RE.findall(query.lower()) if w not in _DOMAIN_STOPWORDS]
    return " ".join(terms) if terms else query


def _lexical_candidates(conn, query: str, k: int) -> list[int]:
    """Top-k chunk ids by full-text relevance (``ts_rank`` over the tsv column).

    ``plainto_tsquery`` turns the query into a tsquery (handles English stop-words
    and stemming). ``ts_rank`` scores how well tsv matches it; higher is better,
    hence DESC. Rows that don't match at all are filtered by the ``tsv @@ q`` WHERE
    clause so they never enter the lexical ranking.

    We feed ``_content_terms(query)`` rather than the raw question so civic-generic
    words don't drown the discriminative topic words in the ranking (see
    ``_DOMAIN_STOPWORDS``).
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM civic_chunks, plainto_tsquery('english', %s) AS q
            WHERE tsv @@ q
            ORDER BY ts_rank(tsv, q) DESC
            LIMIT %s;
            """,
            (_content_terms(query), k),
        )
        return [row[0] for row in cur.fetchall()]


def _fetch_chunks(conn, chunk_ids: list[int]) -> dict[int, RetrievedChunk]:
    """Hydrate chunk ids into records carrying their parent document's citation.

    Joins each chunk back to its parent ``civic_documents`` so the returned record
    carries the bill ``file_no`` and ``title`` the answer layer needs to cite.
    """

    if not chunk_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, d.source_ref, d.file_no, d.title, c.chunk_index, c.text,
                   d.doc_type, d.status, d.intro_date
            FROM civic_chunks c
            JOIN civic_documents d ON d.id = c.document_id
            WHERE c.id = ANY(%s);
            """,
            (chunk_ids,),
        )
        return {
            row[0]: RetrievedChunk(
                chunk_id=row[0],
                source_ref=row[1],
                file_no=row[2],
                title=row[3],
                chunk_index=row[4],
                text=row[5],
                doc_type=row[6],
                status=row[7],
                intro_date=row[8],
            )
            for row in cur.fetchall()
        }


# ===========================================================================
# Public entry point
# ===========================================================================


def retrieve(query: str, top_k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
    """Hybrid-retrieve the top_k most relevant civic chunks for a query.

    Flow:
        1. Embed the query once.
        2. Dense retriever -> ranked list of chunk ids.
        3. Lexical retriever -> ranked list of chunk ids.
        4. RRF-fuse the two rankings.
        5. Hydrate the top_k fused ids into RetrievedChunk records (in fused order),
           each carrying its parent document's file_no + title for citation.
    """

    query_vector = embed_query(query)

    with get_conn() as conn:
        dense_ids = _dense_candidates(conn, query_vector, CANDIDATE_K)
        lexical_ids = _lexical_candidates(conn, query, CANDIDATE_K)

        # Down-weight the noisier dense arm so the sharpened lexical arm leads (see
        # LEXICAL_WEIGHT / DENSE_WEIGHT). Order here MUST match the weights order.
        fused = reciprocal_rank_fusion(
            [dense_ids, lexical_ids], weights=[DENSE_WEIGHT, LEXICAL_WEIGHT]
        )
        top_ids = [cid for cid, _score in fused[:top_k]]

        by_id = _fetch_chunks(conn, top_ids)

    # Preserve fused order; skip any id that somehow didn't hydrate.
    return [by_id[cid] for cid in top_ids if cid in by_id]
