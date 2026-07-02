"""Pure unit tests for citation extraction/verification (no DB / network / LLM).

Uses ``importorskip`` so the suite stays green without the civic DB deps that
``app.civic.answer`` transitively imports (it pulls in ``app.civic.retrieval``,
which imports pgvector/psycopg at module load). Where those deps ARE installed,
these tests exercise the real cite-or-refuse guard.
"""

import pytest

answer = pytest.importorskip(
    "app.civic.answer",
    reason="civic answer deps (pgvector/psycopg) not installed",
)


def test_extract_citations_dedups_in_first_appearance_order():
    text = "Council passed [Bill 260633], then [260633] again, then [Bill 240100-A]."
    # De-duplicated, first-appearance order; both the labelled and bare forms of
    # 260633 collapse to one entry.
    assert answer.extract_citations(text) == ["260633", "240100-A"]


def test_verify_citations_drops_hallucinated_bill():
    # 260633 was retrieved; 111111 was invented by the model and must be dropped.
    text = "The measure was approved [Bill 260633]. See also [Bill 111111]."
    assert answer.verify_citations(text, {"260633"}) == ["260633"]


def test_verify_citations_keeps_retrieved_bills():
    text = "See [Bill 260633] and [Bill 240100-A]."
    assert answer.verify_citations(text, {"260633", "240100-A"}) == [
        "260633",
        "240100-A",
    ]
