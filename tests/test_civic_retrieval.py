"""Exhaustive tests for hybrid retrieval: RRF fusion + the ``retrieve`` pipeline.

Two layers:

  * PURE fusion (``reciprocal_rank_fusion``) — enumerated edge cases via
    ``parametrize`` plus property-based invariants via Hypothesis. No I/O.
  * The ``retrieve`` orchestration — the DB retrievers and embedder are mocked so
    the fusion/hydration/ordering wiring is exercised with NO Postgres, NO ONNX.

Uses ``importorskip`` so the file collects cleanly on a machine without the civic
DB deps (pgvector/psycopg), matching the existing civic test convention.
"""

from __future__ import annotations

import math
from datetime import date
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

retrieval = pytest.importorskip(
    "app.civic.retrieval",
    reason="civic retrieval deps (pgvector/psycopg) not installed",
)

rrf = retrieval.reciprocal_rank_fusion
RRF_K = retrieval.RRF_K


# ===========================================================================
# Pure RRF — enumerated edge cases
# ===========================================================================


class TestRRFEnumerated:
    def test_empty_outer_list_is_empty(self):
        assert rrf([]) == []

    def test_all_inner_lists_empty_is_empty(self):
        assert rrf([[], [], []]) == []

    def test_single_list_preserves_its_order(self):
        # With one list, RRF is a monotonic transform of rank, so order is kept.
        fused = rrf([[10, 20, 30]])
        assert [cid for cid, _ in fused] == [10, 20, 30]

    def test_single_list_scores_match_formula(self):
        fused = dict(rrf([[10, 20, 30]]))
        assert fused[10] == pytest.approx(1.0 / (RRF_K + 1))
        assert fused[20] == pytest.approx(1.0 / (RRF_K + 2))
        assert fused[30] == pytest.approx(1.0 / (RRF_K + 3))

    def test_k_60_math_exact(self):
        # Default k=60: a rank-1 item scores 1/61.
        fused = dict(rrf([[7]]))
        assert fused[7] == pytest.approx(1.0 / 61)

    def test_custom_k_changes_scale(self):
        fused = dict(rrf([[7]], k=0))
        # k=0 => rank-1 scores 1/1 = 1.0.
        assert fused[7] == pytest.approx(1.0)

    def test_duplicate_chunk_across_lists_sums_contributions(self):
        # id 5 is rank-1 in both lists => 2 * 1/(k+1).
        fused = dict(rrf([[5], [5]]))
        assert fused[5] == pytest.approx(2.0 / (RRF_K + 1))

    def test_duplicate_within_single_list_takes_last_rank(self):
        # A pathological list repeating an id: the dict assignment overwrites, so
        # the LAST occurrence's rank wins (this documents the actual behavior — the
        # code uses ``scores[cid] = scores.get(...) + ...`` per position, but a
        # repeat re-reads the freshly-updated value, so both contributions add).
        fused = dict(rrf([[5, 5]]))
        # position 0 (rank1): 1/(k+1); position 1 (rank2) adds 1/(k+2).
        assert fused[5] == pytest.approx(1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 2))

    def test_agreement_beats_single_list_presence(self):
        fused = rrf([[1, 2, 3], [2, 1, 4]])
        ids = [cid for cid, _ in fused]
        assert set(ids[:2]) == {1, 2}
        assert set(ids[2:]) == {3, 4}

    def test_ties_broken_by_chunk_id_ascending(self):
        fused = rrf([[5, 3], [7, 9]])
        scores = dict(fused)
        assert scores[5] == scores[7]
        order = [cid for cid, _ in fused]
        assert order.index(5) < order.index(7)

    def test_full_tie_all_ranks_sorted_by_id(self):
        # Four ids each appearing once at rank 1 in four separate lists: all tie,
        # so the whole output is id-ascending.
        fused = rrf([[40], [10], [30], [20]])
        assert [cid for cid, _ in fused] == [10, 20, 30, 40]

    @pytest.mark.parametrize(
        "lists,expected_top",
        [
            ([[1, 2]], 1),                 # single list, top is rank-1
            ([[2, 1], [2, 3]], 2),         # 2 agrees across both
            ([[9], [9], [9]], 9),          # unanimous
            # Symmetric [1,2,3]/[3,2,1]: RRF's convex 1/(k+rank) rewards a strong
            # #1, so ids 1 and 3 (rank1+rank3) each BEAT id 2 (rank2 twice) — 1
            # and 3 tie, so the id-ascending tiebreak makes 1 the top result.
            ([[1, 2, 3], [3, 2, 1]], 1),
        ],
    )
    def test_top_result(self, lists, expected_top):
        assert rrf(lists)[0][0] == expected_top

    def test_scores_are_descending(self):
        fused = rrf([[1, 2, 3], [3, 4, 5]])
        scores = [s for _, s in fused]
        assert scores == sorted(scores, reverse=True)

    def test_negative_ids_supported(self):
        # chunk ids are just ints; nothing forbids negatives — tiebreak still asc.
        fused = rrf([[-1], [-2]])
        assert [cid for cid, _ in fused] == [-2, -1]

    def test_symmetric_pair_endpoints_beat_the_middle(self):
        # [1,2,3] and [3,2,1]: id 2 is rank-2 in BOTH lists -> 2/(k+2). ids 1 and 3
        # are rank1 in one list and rank3 in the other -> 1/(k+1)+1/(k+3). Because
        # 1/(k+rank) is convex, the (rank1,rank3) pair sums to MORE than 2*(rank2):
        # a strong #1 outweighs a matched middle. So 1 and 3 beat 2, and tie each
        # other (mirror images).
        fused = dict(rrf([[1, 2, 3], [3, 2, 1]]))
        assert fused[1] > fused[2]
        assert fused[3] > fused[2]
        assert fused[1] == pytest.approx(fused[3])


# ===========================================================================
# Pure RRF — property-based (Hypothesis) over the combinatorial input space
# ===========================================================================

# Ranked lists of small non-negative ids. Lists may share ids, be empty, differ
# in length — the whole combinatorial space RRF must survive.
_id = st.integers(min_value=0, max_value=12)
_ranked_list = st.lists(_id, max_size=8, unique=True)
_ranked_lists = st.lists(_ranked_list, max_size=4)


class TestRRFProperties:
    @given(_ranked_lists)
    @hyp_settings(max_examples=250)
    def test_output_is_permutation_of_union(self, lists):
        fused = rrf(lists)
        out_ids = [cid for cid, _ in fused]
        union = set().union(*[set(l) for l in lists]) if lists else set()
        assert set(out_ids) == union
        assert len(out_ids) == len(union)  # no duplicates in output

    @given(_ranked_lists)
    @hyp_settings(max_examples=250)
    def test_scores_non_increasing(self, lists):
        fused = rrf(lists)
        scores = [s for _, s in fused]
        assert all(a >= b for a, b in zip(scores, scores[1:]))

    @given(_ranked_lists)
    @hyp_settings(max_examples=250)
    def test_all_scores_strictly_positive(self, lists):
        # Every id that appears at least once has a strictly positive score.
        for _cid, score in rrf(lists):
            assert score > 0.0

    @given(_ranked_lists)
    @hyp_settings(max_examples=250)
    def test_equal_scores_are_id_sorted(self, lists):
        fused = rrf(lists)
        for (id_a, s_a), (id_b, s_b) in zip(fused, fused[1:]):
            # RRF's sort key is (-score, id), so id-ascending is guaranteed only on
            # EXACT score ties. Two merely-close-but-distinct scores are ordered by
            # score, not id, so math.isclose would over-assert here.
            if s_a == s_b:
                assert id_a < id_b

    @given(_ranked_lists)
    @hyp_settings(max_examples=200)
    def test_determinism_same_input_same_output(self, lists):
        assert rrf(lists) == rrf(lists)

    @given(st.permutations(list(range(6))))
    @hyp_settings(max_examples=120)
    def test_single_list_is_rank_order(self, perm):
        perm = list(perm)
        assert [cid for cid, _ in rrf([perm])] == perm

    @given(_ranked_list)
    @hyp_settings(max_examples=150)
    def test_duplicating_a_list_preserves_order(self, one):
        # Fusing a list with an identical copy doubles every score but cannot
        # change the relative ordering.
        single = [cid for cid, _ in rrf([one])]
        doubled = [cid for cid, _ in rrf([one, one])]
        assert single == doubled


# ===========================================================================
# retrieve() orchestration — DB retrievers + embedder mocked (no I/O)
# ===========================================================================


class _FakeConn:
    """Stand-in for a psycopg connection used as a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestRetrieveOrchestration:
    def _patch(self, monkeypatch, *, dense, lexical, hydrate):
        monkeypatch.setattr(retrieval, "embed_query", lambda q: [0.0] * 384)

        from contextlib import contextmanager

        @contextmanager
        def fake_get_conn():
            yield _FakeConn()

        monkeypatch.setattr(retrieval, "get_conn", fake_get_conn)
        monkeypatch.setattr(retrieval, "_dense_candidates",
                            lambda c, v, k, jz=None: dense)
        monkeypatch.setattr(retrieval, "_lexical_candidates",
                            lambda c, q, k, jz=None: lexical)
        monkeypatch.setattr(retrieval, "_fetch_chunks", lambda c, ids: hydrate)

    def _chunk(self, cid, file_no="260633"):
        return retrieval.RetrievedChunk(
            chunk_id=cid, source_ref=str(cid), file_no=file_no,
            title="t", chunk_index=0, text="x",
        )

    def test_returns_top_k_in_fused_order(self, monkeypatch):
        # dense=[1,2,3] (weight 0.5), lexical=[3,2,1] (weight 1.0). The lexical arm
        # is trusted 2x, so its ranking leads and the down-weighted dense arm only
        # nudges: fused scores come out 3 > 2 > 1 -> lexical's order is preserved.
        hydrate = {i: self._chunk(i) for i in (1, 2, 3)}
        self._patch(monkeypatch, dense=[1, 2, 3], lexical=[3, 2, 1], hydrate=hydrate)
        out = retrieval.retrieve("q", top_k=3)
        assert [c.chunk_id for c in out] == [3, 2, 1]

    def test_top_k_truncates(self, monkeypatch):
        hydrate = {i: self._chunk(i) for i in (1, 2, 3)}
        self._patch(monkeypatch, dense=[1, 2, 3], lexical=[1, 2, 3], hydrate=hydrate)
        out = retrieval.retrieve("q", top_k=2)
        assert [c.chunk_id for c in out] == [1, 2]

    def test_empty_retrievers_yield_empty(self, monkeypatch):
        self._patch(monkeypatch, dense=[], lexical=[], hydrate={})
        assert retrieval.retrieve("q") == []

    def test_unhydrated_id_is_skipped(self, monkeypatch):
        # id 3 fused in but not returned by _fetch_chunks -> silently dropped.
        hydrate = {1: self._chunk(1), 2: self._chunk(2)}
        self._patch(monkeypatch, dense=[1, 2, 3], lexical=[1, 2, 3], hydrate=hydrate)
        out = retrieval.retrieve("q", top_k=3)
        assert [c.chunk_id for c in out] == [1, 2]

    def test_dense_only_still_returns(self, monkeypatch):
        hydrate = {5: self._chunk(5)}
        self._patch(monkeypatch, dense=[5], lexical=[], hydrate=hydrate)
        out = retrieval.retrieve("q")
        assert [c.chunk_id for c in out] == [5]

    def test_lexical_only_still_returns(self, monkeypatch):
        hydrate = {8: self._chunk(8)}
        self._patch(monkeypatch, dense=[], lexical=[8], hydrate=hydrate)
        out = retrieval.retrieve("q")
        assert [c.chunk_id for c in out] == [8]

    def test_query_is_embedded_once(self, monkeypatch):
        calls = []
        monkeypatch.setattr(retrieval, "embed_query",
                            lambda q: calls.append(q) or [0.0] * 384)
        from contextlib import contextmanager

        @contextmanager
        def fake_get_conn():
            yield _FakeConn()

        monkeypatch.setattr(retrieval, "get_conn", fake_get_conn)
        monkeypatch.setattr(retrieval, "_dense_candidates", lambda c, v, k, jz=None: [1])
        monkeypatch.setattr(retrieval, "_lexical_candidates", lambda c, q, k, jz=None: [1])
        monkeypatch.setattr(retrieval, "_fetch_chunks",
                            lambda c, ids: {1: self._chunk(1)})
        retrieval.retrieve("only once")
        assert calls == ["only once"]


# ===========================================================================
# RetrievedChunk record — grounding metadata is carried through
# ===========================================================================


class TestRetrievedChunkRecord:
    def test_grounding_metadata_defaults_none(self):
        c = retrieval.RetrievedChunk(
            chunk_id=1, source_ref="x", file_no="1", title="t",
            chunk_index=0, text="body",
        )
        assert c.doc_type is None
        assert c.status is None
        assert c.intro_date is None

    def test_carries_status_type_intro(self):
        c = retrieval.RetrievedChunk(
            chunk_id=1, source_ref="x", file_no="1", title="t",
            chunk_index=0, text="body", doc_type="Ordinance",
            status="ENACTED", intro_date=date(2026, 1, 2),
        )
        assert (c.doc_type, c.status, c.intro_date) == (
            "Ordinance", "ENACTED", date(2026, 1, 2))


# ===========================================================================
# SQL retrievers — mocked psycopg (no Postgres)
#
# These exercise the SQL-building / param-binding / row-mapping of the three
# DB-backed helpers WITHOUT a live database. The psycopg cursor is a MagicMock
# whose ``fetchall`` returns canned rows; we assert both the returned
# ids/records AND the exact SQL fragments (the ``%s::vector`` cast, the
# ``tsv @@ q`` lexical filter, the ``ANY(%s)`` id-array bind) so a regression in
# the query text is caught here rather than only against a real Postgres.
#
# ``register_vector`` is patched to a no-op so no pgvector adapter registration
# reaches a real connection.
# ===========================================================================


def _mock_conn(fetchall_rows=None, fetchone_row=None):
    """A MagicMock connection whose ``cursor()`` is a context manager.

    ``conn._cur`` exposes the cursor mock for asserting on executed SQL/params.
    """

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    if fetchall_rows is not None:
        cur.fetchall.return_value = fetchall_rows
    if fetchone_row is not None:
        cur.fetchone.return_value = fetchone_row
    conn._cur = cur
    return conn


def _sql_and_params(conn):
    """Pull the (sql, params) positional args of the last cursor.execute call."""

    return conn._cur.execute.call_args[0]


class TestDenseCandidatesSQL:
    def test_registers_vector_on_the_connection(self, monkeypatch):
        seen = []
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: seen.append(conn))
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, [0.0] * 384, 20)
        assert seen == [conn]

    def test_returns_ids_in_fetch_order(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[(3,), (1,), (2,)])
        assert retrieval._dense_candidates(conn, [0.0] * 384, 20) == [3, 1, 2]

    def test_empty_rows_yield_empty_list(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[])
        assert retrieval._dense_candidates(conn, [0.0] * 384, 20) == []

    def test_uses_vector_cast_and_cosine_operator(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, [0.1] * 384, 7)
        sql, _params = _sql_and_params(conn)
        # The ::vector cast is load-bearing: pgvector has no
        # ``vector <=> double precision[]`` operator, so the bound list must be
        # coerced to vector before the cosine-distance operator sees it.
        assert "%s::vector" in sql
        assert "<=>" in sql

    def test_orders_ascending_by_distance(self, monkeypatch):
        # cosine DISTANCE: smaller = more similar, so ascending = best-first. The
        # query must NOT say DESC on the distance ordering.
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, [0.0] * 384, 20)
        sql, _ = _sql_and_params(conn)
        assert "ORDER BY embedding <=> %s::vector" in sql
        assert "<=> %s::vector DESC" not in sql

    def test_filters_null_embeddings(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, [0.0] * 384, 20)
        sql, _ = _sql_and_params(conn)
        assert "embedding IS NOT NULL" in sql

    def test_binds_vector_then_limit(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        vec = [0.1] * 384
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, vec, 7)
        _sql, params = _sql_and_params(conn)
        # Order matters: the vector param feeds the ::vector cast, the k feeds LIMIT.
        assert params == (vec, 7)

    @pytest.mark.parametrize("k", [0, 1, 20, 200])
    def test_limit_bind_passes_k_through(self, monkeypatch, k):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[])
        retrieval._dense_candidates(conn, [0.0] * 384, k)
        _sql, params = _sql_and_params(conn)
        assert params[1] == k


class TestLexicalCandidatesSQL:
    def test_returns_ids_in_fetch_order(self):
        conn = _mock_conn(fetchall_rows=[(9,), (8,)])
        assert retrieval._lexical_candidates(conn, "trash pickup", 20) == [9, 8]

    def test_empty_rows_yield_empty_list(self):
        conn = _mock_conn(fetchall_rows=[])
        assert retrieval._lexical_candidates(conn, "anything", 20) == []

    def test_uses_plainto_tsquery(self):
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "trash pickup", 5)
        sql, _ = _sql_and_params(conn)
        assert "plainto_tsquery('english', %s)" in sql

    def test_filters_on_tsv_match(self):
        # The ``tsv @@ q`` WHERE clause keeps non-matching rows out of the lexical
        # ranking entirely — without it every row would rank (at score 0).
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "trash pickup", 5)
        sql, _ = _sql_and_params(conn)
        assert "tsv @@ q" in sql

    def test_ranks_by_ts_rank_descending(self):
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "trash pickup", 5)
        sql, _ = _sql_and_params(conn)
        # Higher ts_rank = better lexical match, so DESC.
        assert "ORDER BY ts_rank(tsv, q) DESC" in sql

    def test_binds_content_terms_then_limit(self):
        # A query with no civic-generic terms passes through unchanged, so the
        # bound param is just the query (content-reduced) followed by the limit.
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "trash pickup", 5)
        _sql, params = _sql_and_params(conn)
        assert params == ("trash pickup", 5)

    def test_binds_reduced_content_terms_not_raw_query(self):
        # The lexical arm searches the DISCRIMINATIVE terms, not the raw question:
        # civic-generic scaffolding ("what recent legislation concerns ...") is
        # dropped before binding so it can't drown the topic word in the ranking.
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "What recent legislation concerns zoning?", 5)
        _sql, params = _sql_and_params(conn)
        assert params[0] == "what zoning"  # "recent/legislation/concerns" stripped

    @pytest.mark.parametrize("query", ["", "   ", "!@#$%", "café", "a" * 500])
    def test_odd_queries_do_not_crash_and_bind_a_string(self, query):
        # Odd/empty/unicode text must not raise and must still bind a str param
        # (content-reduction never turns a query into a non-string or None).
        conn = _mock_conn(fetchall_rows=[])
        retrieval._lexical_candidates(conn, query, 5)
        _sql, params = _sql_and_params(conn)
        assert isinstance(params[0], str)


class TestContentTerms:
    def test_drops_civic_generic_terms(self):
        assert retrieval._content_terms(
            "What recent legislation concerns zoning?"
        ) == "what zoning"

    def test_keeps_multiword_topic(self):
        # Only DOMAIN-generic terms are dropped here ("bills"); ordinary English
        # stop-words ("are/there/any/about") are left for plainto_tsquery to drop
        # downstream, so the topic words "convenience fees" survive.
        assert retrieval._content_terms(
            "Are there any bills about convenience fees?"
        ) == "are there any about convenience fees"

    def test_keeps_bill_numbers(self):
        # Bill numbers are highly discriminative; digits survive reduction.
        assert "260640" in retrieval._content_terms("what does bill 260640 do")

    def test_all_generic_query_falls_back_to_original(self):
        # If every word is generic, reducing to "" would search nothing, so we
        # return the original query so the lexical arm still runs.
        q = "legislation ordinance resolution council"
        assert retrieval._content_terms(q) == q

    def test_unicode_word_is_preserved_whole(self):
        assert retrieval._content_terms("café") == "café"


class TestJurisdictionFilter:
    def test_dense_default_query_has_no_jurisdiction_join(self, monkeypatch):
        # Whole-corpus search keeps the original single-table query (no join).
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, [0.0] * 384, 20)
        sql, params = _sql_and_params(conn)
        assert "civic_documents" not in sql
        assert params == ([0.0] * 384, 20)

    def test_dense_scoped_query_joins_and_binds_jurisdiction_first(self, monkeypatch):
        monkeypatch.setattr(retrieval, "register_vector", lambda conn: None)
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._dense_candidates(conn, [0.0] * 384, 20, jurisdiction="chicago")
        sql, params = _sql_and_params(conn)
        assert "JOIN civic_documents d" in sql
        assert "d.jurisdiction = %s" in sql
        assert params == ("chicago", [0.0] * 384, 20)

    def test_lexical_default_query_has_no_jurisdiction_join(self):
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "zoning", 20)
        sql, _ = _sql_and_params(conn)
        assert "civic_documents" not in sql

    def test_lexical_scoped_query_joins_and_binds_jurisdiction(self):
        conn = _mock_conn(fetchall_rows=[(1,)])
        retrieval._lexical_candidates(conn, "zoning", 20, jurisdiction="chicago")
        sql, params = _sql_and_params(conn)
        assert "JOIN civic_documents d" in sql
        assert "d.jurisdiction = %s" in sql
        # (content_terms, jurisdiction, k)
        assert params == ("zoning", "chicago", 20)

    def test_retrieve_threads_jurisdiction_to_both_retrievers(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(retrieval, "embed_query", lambda q: [0.0] * 384)

        from contextlib import contextmanager

        @contextmanager
        def fake_get_conn():
            yield _FakeConn()

        monkeypatch.setattr(retrieval, "get_conn", fake_get_conn)
        monkeypatch.setattr(retrieval, "_dense_candidates",
                            lambda c, v, k, jz=None: seen.setdefault("dense", jz) or [1])
        monkeypatch.setattr(retrieval, "_lexical_candidates",
                            lambda c, q, k, jz=None: seen.setdefault("lex", jz) or [1])
        monkeypatch.setattr(retrieval, "_fetch_chunks",
                            lambda c, ids: {1: retrieval.RetrievedChunk(
                                chunk_id=1, source_ref="1", file_no="1",
                                title="t", chunk_index=0, text="x")})
        retrieval.retrieve("q", jurisdiction="chicago")
        assert seen == {"dense": "chicago", "lex": "chicago"}


class TestFetchChunksSQL:
    def test_empty_ids_short_circuit_no_query(self):
        conn = MagicMock()
        assert retrieval._fetch_chunks(conn, []) == {}
        conn.cursor.assert_not_called()

    def test_joins_document_for_citation_fields(self):
        conn = _mock_conn(fetchall_rows=[])
        retrieval._fetch_chunks(conn, [1])
        sql, _ = _sql_and_params(conn)
        assert "JOIN civic_documents" in sql

    def test_binds_id_array_for_any(self):
        conn = _mock_conn(fetchall_rows=[])
        retrieval._fetch_chunks(conn, [5, 6, 7])
        sql, params = _sql_and_params(conn)
        assert "ANY(%s)" in sql
        assert params == ([5, 6, 7],)

    def test_maps_rows_to_records_keyed_by_id(self):
        rows = [
            (1, "27386", "260633", "Ord X", 0, "body one",
             "Ordinance", "IN COMMITTEE", date(2026, 6, 11)),
            (2, "27400", None, "Comm Y", 3, "body two",
             "Communication", "PLACED ON FILE", None),
        ]
        conn = _mock_conn(fetchall_rows=rows)
        by_id = retrieval._fetch_chunks(conn, [1, 2])
        assert set(by_id) == {1, 2}
        one = by_id[1]
        assert (one.chunk_id, one.source_ref, one.file_no, one.title,
                one.chunk_index, one.text) == (
            1, "27386", "260633", "Ord X", 0, "body one")
        assert (one.doc_type, one.status, one.intro_date) == (
            "Ordinance", "IN COMMITTEE", date(2026, 6, 11))

    def test_null_document_fields_are_preserved(self):
        # A chunk whose parent has a null file_no / status / intro_date (real
        # records do) must round-trip those Nones rather than crash or coerce.
        rows = [(2, "27400", None, None, 0, "body", None, None, None)]
        conn = _mock_conn(fetchall_rows=rows)
        rec = retrieval._fetch_chunks(conn, [2])[2]
        assert rec.file_no is None
        assert rec.status is None
        assert rec.intro_date is None
        assert rec.title is None

    def test_result_is_dict_not_ordered_list(self):
        # ``retrieve`` re-orders by fused rank using this dict, so hydration order
        # is irrelevant — but every requested-and-present id must be a key.
        rows = [(2, "b", "f2", "t2", 0, "x2", None, None, None),
                (1, "a", "f1", "t1", 0, "x1", None, None, None)]
        conn = _mock_conn(fetchall_rows=rows)
        by_id = retrieval._fetch_chunks(conn, [1, 2])
        assert isinstance(by_id, dict)
        assert set(by_id) == {1, 2}


class TestSQLRetrieverProperties:
    """Hypothesis over the row -> id-list mapping of the ranked retrievers."""

    @given(st.lists(st.integers(min_value=-50, max_value=50), max_size=25))
    @hyp_settings(max_examples=150)
    def test_lexical_preserves_row_order_exactly(self, ids):
        conn = _mock_conn(fetchall_rows=[(i,) for i in ids])
        assert retrieval._lexical_candidates(conn, "q", 20) == ids

    @given(st.lists(st.integers(min_value=-50, max_value=50), max_size=25))
    @hyp_settings(max_examples=150)
    def test_dense_preserves_row_order_exactly(self, ids):
        # Function-scoped fixtures (monkeypatch) don't compose with @given's
        # per-example re-invocation, so patch register_vector by hand and restore.
        original = retrieval.register_vector
        retrieval.register_vector = lambda conn: None
        try:
            conn = _mock_conn(fetchall_rows=[(i,) for i in ids])
            assert retrieval._dense_candidates(conn, [0.0] * 384, 20) == ids
        finally:
            retrieval.register_vector = original

    @given(st.lists(st.integers(min_value=0, max_value=99), max_size=15, unique=True))
    @hyp_settings(max_examples=150)
    def test_fetch_chunks_keys_match_returned_rows(self, ids):
        rows = [(i, str(i), None, None, 0, "x", None, None, None) for i in ids]
        conn = _mock_conn(fetchall_rows=rows)
        by_id = retrieval._fetch_chunks(conn, ids)
        assert set(by_id) == set(ids)
