"""Tests for the insight aggregates + their HTTP routes.

No Postgres: ``get_conn`` is replaced with a mock cursor that returns canned
aggregate rows, so the SQL wiring, row mapping, and sorting are exercised without
a database. Route tests stub the insight functions at their module boundary and
drive the real FastAPI app via the ``civic_client`` fixture.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

insights = pytest.importorskip(
    "app.civic.insights",
    reason="civic deps (pgvector/psycopg) not installed",
)


def _patch_conn(monkeypatch, cur):
    """Point ``insights.get_conn`` at a context-manager conn whose cursor is ``cur``."""

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    monkeypatch.setattr(insights, "get_conn", lambda: cm)


# ===========================================================================
# _rows_as_count_items
# ===========================================================================


class TestRowsAsCountItems:
    def test_maps_label_and_count(self):
        assert insights._rows_as_count_items([("Bill", 5), ("Resolution", 3)]) == [
            {"label": "Bill", "count": 5},
            {"label": "Resolution", "count": 3},
        ]

    def test_null_label_becomes_unknown(self):
        # A Matter with no status must still be counted, surfaced as "Unknown", so
        # the breakdown reconciles with the grand total rather than silently losing rows.
        assert insights._rows_as_count_items([(None, 7)]) == [
            {"label": "Unknown", "count": 7}
        ]

    def test_empty_is_empty(self):
        assert insights._rows_as_count_items([]) == []


# ===========================================================================
# corpus_overview
# ===========================================================================


class TestCorpusOverview:
    def _cursor(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (1996,),                              # total
            (date(2024, 10, 10), date(2026, 6, 11)),  # min/max intro_date
        ]
        cur.fetchall.side_effect = [
            [("Resolution", 1044), ("Bill", 514)],    # by_type
            [("ADOPTED", 1013), (None, 5)],           # by_status (incl. a NULL)
            [("2026-06", 50), ("2026-05", 153)],      # by_month
        ]
        return cur

    def test_shapes_the_snapshot(self, monkeypatch):
        cur = self._cursor()
        _patch_conn(monkeypatch, cur)
        out = insights.corpus_overview()
        assert out["total_documents"] == 1996
        assert out["by_type"][0] == {"label": "Resolution", "count": 1044}
        assert out["earliest_intro_date"] == date(2024, 10, 10)
        assert out["latest_intro_date"] == date(2026, 6, 11)

    def test_null_status_surfaced_as_unknown(self, monkeypatch):
        cur = self._cursor()
        _patch_conn(monkeypatch, cur)
        out = insights.corpus_overview()
        assert {"label": "Unknown", "count": 5} in out["by_status"]

    def test_month_breakdown_carried_through(self, monkeypatch):
        cur = self._cursor()
        _patch_conn(monkeypatch, cur)
        out = insights.corpus_overview()
        assert out["by_month"] == [
            {"label": "2026-06", "count": 50},
            {"label": "2026-05", "count": 153},
        ]


# ===========================================================================
# topic_activity
# ===========================================================================


class TestTopicActivity:
    def _cursor_returning(self, counts):
        cur = MagicMock()
        cur.fetchone.side_effect = [(c,) for c in counts]
        return cur

    def test_one_item_per_tracked_topic(self, monkeypatch):
        counts = list(range(len(insights.TRACKED_TOPICS)))
        _patch_conn(monkeypatch, self._cursor_returning(counts))
        out = insights.topic_activity()
        assert len(out["topics"]) == len(insights.TRACKED_TOPICS)
        assert {t["topic"] for t in out["topics"]} == {
            label for label, _q in insights.TRACKED_TOPICS
        }

    def test_sorted_busiest_first(self, monkeypatch):
        # Counts returned in topic order; output must be sorted by bills DESC.
        counts = [3, 9, 1] + [0] * (len(insights.TRACKED_TOPICS) - 3)
        _patch_conn(monkeypatch, self._cursor_returning(counts))
        out = insights.topic_activity()
        bills = [t["bills"] for t in out["topics"]]
        assert bills == sorted(bills, reverse=True)
        assert out["topics"][0]["bills"] == 9

    def test_since_none_bound_twice(self, monkeypatch):
        cur = self._cursor_returning([0] * len(insights.TRACKED_TOPICS))
        _patch_conn(monkeypatch, cur)
        insights.topic_activity(since=None)
        # Each topic query binds (tsquery, since, since) — since appears twice.
        first_params = cur.execute.call_args_list[0].args[1]
        assert first_params[1] is None and first_params[2] is None

    def test_since_date_passed_through_and_echoed(self, monkeypatch):
        cur = self._cursor_returning([0] * len(insights.TRACKED_TOPICS))
        _patch_conn(monkeypatch, cur)
        out = insights.topic_activity(since=date(2026, 6, 1))
        assert out["since"] == date(2026, 6, 1)
        params = cur.execute.call_args_list[0].args[1]
        assert params[1] == date(2026, 6, 1) and params[2] == date(2026, 6, 1)

    def test_query_uses_tsquery_and_distinct(self, monkeypatch):
        cur = self._cursor_returning([0] * len(insights.TRACKED_TOPICS))
        _patch_conn(monkeypatch, cur)
        insights.topic_activity()
        sql = cur.execute.call_args_list[0].args[0]
        assert "to_tsquery('english', %s)" in sql
        # Topic membership is by TITLE (no chunk join) so incidental body mentions
        # don't inflate the count.
        assert "civic_chunks" not in sql
        assert "to_tsvector('english', coalesce(d.title" in sql


class TestTopicTrends:
    def test_dense_axis_and_zero_filled_series(self, monkeypatch):
        cur = MagicMock()
        # One topic returns 2012 & 2014 (a gap year 2013), the rest return nothing.
        cur.fetchall.side_effect = (
            [[(2012, 5), (2014, 3)]] + [[]] * (len(insights.TRACKED_TOPICS) - 1)
        )
        _patch_conn(monkeypatch, cur)
        out = insights.topic_trends()
        assert out["years"] == [2012, 2013, 2014]      # dense, gap filled
        assert out["topics"][0]["series"] == [5, 0, 3]  # zero-filled at 2013
        assert out["topics"][1]["series"] == [0, 0, 0]

    def test_empty_corpus_has_no_years(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.side_effect = [[]] * len(insights.TRACKED_TOPICS)
        _patch_conn(monkeypatch, cur)
        out = insights.topic_trends()
        assert out["years"] == []
        assert all(t["series"] == [] for t in out["topics"])

    def test_jurisdiction_bound(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.side_effect = [[]] * len(insights.TRACKED_TOPICS)
        _patch_conn(monkeypatch, cur)
        insights.topic_trends(jurisdiction="phila")
        sql, params = cur.execute.call_args_list[0].args
        assert "d.jurisdiction = %s" in sql and params[-1] == "phila"

    def test_trends_route(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.topic_trends", lambda jurisdiction=None: {
            "years": [2024, 2025],
            "topics": [{"topic": "Housing", "series": [10, 7]}],
        })
        resp = civic_client.get("/civic/insights/trends?jurisdiction=phila")
        assert resp.status_code == 200
        assert resp.json()["topics"][0]["series"] == [10, 7]


class TestMemberActivity:
    def test_dense_axis_and_zero_filled_series(self, monkeypatch):
        cur = MagicMock()
        # 2012 & 2014 sponsored (a gap year 2013) — single query, so return_value.
        cur.fetchall.return_value = [(2012, 5), (2014, 3)]
        _patch_conn(monkeypatch, cur)
        out = insights.member_activity("CM Bass")
        assert out["years"] == [2012, 2013, 2014]  # dense, gap filled
        assert out["series"] == [5, 0, 3]          # zero-filled at 2013
        assert out["person"] == "CM Bass"

    def test_empty_case(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = []
        _patch_conn(monkeypatch, cur)
        out = insights.member_activity("Nobody")
        assert out["years"] == []
        assert out["series"] == []

    def test_jurisdiction_bound(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = []
        _patch_conn(monkeypatch, cur)
        insights.member_activity("CM Bass", jurisdiction="phila")
        sql, params = cur.execute.call_args.args
        assert "d.jurisdiction = %s" in sql
        assert "s.name = %s" in sql
        assert "civic_sponsors" in sql
        assert params == ("CM Bass", "phila")
        # A no-jurisdiction call still binds the person as the first param.
        insights.member_activity("CM Bass")
        _, params = cur.execute.call_args.args
        assert params[0] == "CM Bass"

    def test_member_activity_route(self, civic_client, monkeypatch):
        monkeypatch.setattr(
            "app.civic.insights.member_activity",
            lambda person, jurisdiction=None: {
                "person": person,
                "jurisdiction": jurisdiction,
                "years": [2024, 2025],
                "series": [3, 5],
            },
        )
        resp = civic_client.get(
            "/civic/insights/member-activity?person=CM%20Bass&jurisdiction=phila"
        )
        assert resp.status_code == 200
        assert resp.json()["series"] == [3, 5]
        assert resp.json()["person"] == "CM Bass"


# ===========================================================================
# HTTP routes
# ===========================================================================


class TestInsightRoutes:
    def test_overview_route_shape(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.corpus_overview", lambda jurisdiction=None: {
            "total_documents": 3,
            "by_type": [{"label": "Bill", "count": 3}],
            "by_status": [{"label": "ADOPTED", "count": 3}],
            "by_month": [{"label": "2026-06", "count": 3}],
            "earliest_intro_date": date(2026, 1, 1),
            "latest_intro_date": date(2026, 6, 1),
        })
        resp = civic_client.get("/civic/insights/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_documents"] == 3
        assert body["by_type"] == [{"label": "Bill", "count": 3}]

    def test_topics_route_shape(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.topic_activity", lambda since=None, jurisdiction=None: {
            "since": since,
            "topics": [{"topic": "Housing", "bills": 12}],
        })
        resp = civic_client.get("/civic/insights/topics")
        assert resp.status_code == 200
        assert resp.json()["topics"][0] == {"topic": "Housing", "bills": 12}

    def test_topics_route_passes_since(self, civic_client, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            "app.civic.insights.topic_activity",
            lambda since=None, jurisdiction=None: (
                seen.update(since=since) or {"since": since, "topics": []}
            ),
        )
        resp = civic_client.get("/civic/insights/topics?since=2026-06-01")
        assert resp.status_code == 200
        assert seen["since"] == date(2026, 6, 1)

    def test_topics_route_rejects_bad_date(self, civic_client):
        resp = civic_client.get("/civic/insights/topics?since=not-a-date")
        assert resp.status_code == 422


# ===========================================================================
# Multi-jurisdiction scoping + /civic/jurisdictions
# ===========================================================================


class TestJurisdictionScoping:
    def test_overview_scoped_binds_jurisdiction(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.side_effect = [(3,), (None, None)]
        cur.fetchall.side_effect = [[], [], []]
        _patch_conn(monkeypatch, cur)
        insights.corpus_overview(jurisdiction="chicago")
        # The count query (first execute) must carry the jurisdiction as a param.
        first = cur.execute.call_args_list[0].args
        assert "WHERE jurisdiction = %s" in first[0]
        assert first[1] == ("chicago",)

    def test_overview_unscoped_binds_nothing(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.side_effect = [(3,), (None, None)]
        cur.fetchall.side_effect = [[], [], []]
        _patch_conn(monkeypatch, cur)
        insights.corpus_overview()
        first = cur.execute.call_args_list[0].args
        assert first[1] == ()

    def test_topics_scoped_appends_jurisdiction_param(self, monkeypatch):
        cur = MagicMock()
        cur.fetchone.side_effect = [(0,)] * len(insights.TRACKED_TOPICS)
        _patch_conn(monkeypatch, cur)
        insights.topic_activity(jurisdiction="chicago")
        params = cur.execute.call_args_list[0].args[1]
        assert params[-1] == "chicago" and len(params) == 4

    def test_list_jurisdictions_shape(self, monkeypatch):
        cur = MagicMock()
        cur.fetchall.return_value = [("phila", 1996), ("chicago", 400)]
        _patch_conn(monkeypatch, cur)
        assert insights.list_jurisdictions() == {
            "jurisdictions": [
                {"slug": "phila", "documents": 1996},
                {"slug": "chicago", "documents": 400},
            ]
        }

    def test_jurisdictions_route(self, civic_client, monkeypatch):
        monkeypatch.setattr("app.civic.insights.list_jurisdictions", lambda: {
            "jurisdictions": [{"slug": "phila", "documents": 5}]
        })
        resp = civic_client.get("/civic/jurisdictions")
        assert resp.status_code == 200
        assert resp.json()["jurisdictions"][0] == {"slug": "phila", "documents": 5}
