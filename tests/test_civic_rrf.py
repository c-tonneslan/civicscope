"""Pure unit tests for Reciprocal Rank Fusion (no DB / network / LLM).

Uses ``importorskip`` so the suite stays green in an environment without the
civic DB deps (pgvector/psycopg), which ``app.civic.retrieval`` imports at module
load. Where those deps ARE installed, these tests exercise the real fusion.
"""

import pytest

rrf = pytest.importorskip(
    "app.civic.retrieval",
    reason="civic retrieval deps (pgvector/psycopg) not installed",
)


def test_rrf_rewards_agreement_between_lists():
    # id 2 is rank-1 in the second list and rank-2 in the first; id 1 is the
    # mirror. Both appear in BOTH lists, so both must outrank ids that appear in
    # only one list (3 and 4).
    fused = rrf.reciprocal_rank_fusion([[1, 2, 3], [2, 1, 4]])
    ids = [cid for cid, _score in fused]

    # 1 and 2 (present in both lists) come before 3 and 4 (present in one).
    assert set(ids[:2]) == {1, 2}
    assert set(ids[2:]) == {3, 4}


def test_rrf_breaks_ties_by_id_ascending():
    # ids 5 and 7 each appear once at rank 1 (in different lists) => identical
    # scores; the deterministic tiebreak must order them by id ascending.
    fused = rrf.reciprocal_rank_fusion([[5, 3], [7, 9]])
    scores = dict(fused)
    assert scores[5] == scores[7]           # genuine tie
    order = [cid for cid, _ in fused]
    assert order.index(5) < order.index(7)  # tie broken by id ascending


def test_rrf_empty_input_is_empty():
    assert rrf.reciprocal_rank_fusion([]) == []
    assert rrf.reciprocal_rank_fusion([[], []]) == []
