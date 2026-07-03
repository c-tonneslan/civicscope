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


def test_rrf_default_weights_are_uniform():
    # Omitting weights must reproduce classic unweighted RRF exactly, so the
    # existing callers/tests are unaffected by the weighted extension.
    unweighted = rrf.reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]])
    explicit_ones = rrf.reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]], weights=[1.0, 1.0])
    assert unweighted == explicit_ones


def test_rrf_weight_lets_one_list_lead():
    # Two lists disagree completely (reversed). With the SECOND list weighted
    # higher, its ordering must win: 3 (its rank-1) ends up ahead of 1 (its rank-3).
    fused = rrf.reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]], weights=[0.5, 1.0])
    order = [cid for cid, _ in fused]
    assert order == [3, 2, 1]


def test_rrf_zero_weight_ignores_a_list():
    # A list weighted 0 contributes nothing; the ranking is the other list's.
    fused = rrf.reciprocal_rank_fusion([[9, 8, 7], [1, 2, 3]], weights=[0.0, 1.0])
    order = [cid for cid, _ in fused]
    assert order[:3] == [1, 2, 3]
