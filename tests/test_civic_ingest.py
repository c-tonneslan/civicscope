"""Exhaustive tests for the ingest pipeline pure functions + upsert wiring.

No network (httpx.MockTransport for Legistar), no ONNX (embedder patched), no
Postgres (get_conn/upsert_document patched). Covers fetch pagination + error
envelopes, normalize (title cleaning, date parsing, url building), chunking
(overlap, zero-width, empties), and the orchestration skip/drop logic.
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

ingest = pytest.importorskip("app.civic.ingest")

from app.civic.schemas import CivicDocument  # noqa: E402


# ===========================================================================
# fetch_matters — pagination, short-page stop, error envelope, HTTP error
# ===========================================================================


class TestFetchMatters:
    def test_single_short_page_stops(self, legistar_client_factory, make_matter):
        http = legistar_client_factory([[make_matter(MatterId=1)]])
        out = ingest.fetch_matters("phila", http=http, page_size=200)
        assert len(out) == 1

    def test_full_page_then_short_page_walks_both(self, legistar_client_factory,
                                                  make_matter):
        page1 = [make_matter(MatterId=i) for i in range(3)]
        page2 = [make_matter(MatterId=99)]
        http = legistar_client_factory([page1, page2])
        out = ingest.fetch_matters("phila", http=http, page_size=3)
        assert len(out) == 4

    def test_empty_first_page_returns_empty(self, legistar_client_factory):
        http = legistar_client_factory([[]])
        assert ingest.fetch_matters("phila", http=http, page_size=200) == []

    def test_max_pages_caps_the_crawl(self, legistar_client_factory, make_matter):
        # Every page is full so paging never self-terminates; max_pages must bound it.
        full = [make_matter(MatterId=i) for i in range(2)]
        http = legistar_client_factory([full, full, full, full])
        out = ingest.fetch_matters("phila", http=http, page_size=2, max_pages=2)
        assert len(out) == 4  # exactly 2 pages of 2

    def test_non_list_payload_raises_value_error(self, legistar_client_factory):
        # A 200 carrying a JSON OBJECT is an OData/CDN error envelope, not data.
        http = legistar_client_factory([{"error": "throttled"}])
        with pytest.raises(ValueError, match="non-list payload"):
            ingest.fetch_matters("phila", http=http, page_size=200)

    def test_odata_verbose_envelope_under_200_raises(self, legistar_client_factory):
        # The realistic Legistar/Granicus failure: a 200 carrying the OData v3
        # verbose error OBJECT instead of the bare array. It's truthy, so without
        # the isinstance guard its keys would splice into ``matters``. Must raise.
        from tests.conftest import odata_error_body

        http = legistar_client_factory([odata_error_body(code="Throttled")])
        with pytest.raises(ValueError, match="non-list payload"):
            ingest.fetch_matters("phila", http=http, page_size=200)

    def test_json_null_body_raises_value_error(self, legistar_client_factory):
        # A literal JSON ``null`` decodes to None (not a list): rejected by the guard.
        http = legistar_client_factory([None])
        with pytest.raises(ValueError, match="non-list payload"):
            ingest.fetch_matters("phila", http=http, page_size=200)

    @pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
    def test_http_error_status_raises(self, legistar_client_factory, status):
        import httpx

        http = legistar_client_factory([(status, {"error": "boom"})])
        with pytest.raises(httpx.HTTPStatusError):
            ingest.fetch_matters("phila", http=http, page_size=200)

    def test_error_on_second_page_propagates_after_first(
        self, legistar_client_factory, make_matter
    ):
        # A good first (full) page then an error page: the error must surface, not
        # be swallowed — a partial ingest is worse than a visible, retryable error.
        import httpx

        page1 = [make_matter(MatterId=i) for i in range(2)]
        http = legistar_client_factory([page1, (503, {"error": "down"})])
        with pytest.raises(httpx.HTTPStatusError):
            ingest.fetch_matters("phila", http=http, page_size=2, max_pages=5)

    def test_sleeps_between_full_pages_only(
        self, legistar_client_factory, make_matter, monkeypatch
    ):
        # The polite inter-page pause fires after each FULL page, never after the
        # terminal short page (no wasted wait before returning).
        sleeps = {"n": 0}
        monkeypatch.setattr(ingest.time, "sleep", lambda s: sleeps.__setitem__("n", sleeps["n"] + 1))

        page1 = [make_matter(MatterId=i) for i in range(2)]   # full -> sleep
        page2 = [make_matter(MatterId=99)]                    # short -> stop, no sleep
        http = legistar_client_factory([page1, page2])
        ingest.fetch_matters("phila", http=http, page_size=2, max_pages=5)
        assert sleeps["n"] == 1

    def test_default_client_uses_settings_slug(
        self, legistar_client_factory, make_matter, civic_settings
    ):
        # When no client arg is passed, the jurisdiction comes from settings, not a
        # buried literal.
        civic_settings(legistar_client="phila")
        http = legistar_client_factory([[make_matter(MatterId=1)]])
        out = ingest.fetch_matters(http=http, page_size=200)
        assert len(out) == 1

    def test_owned_client_is_closed(self, monkeypatch, make_matter):
        # When no client is injected, fetch_matters OWNS the httpx.Client and must
        # close it (the ``finally: if own_client: http.close()`` path).
        import httpx

        closed = {"n": 0}

        class _OwnedClient:
            def __init__(self, *a, **k):
                pass

            def get(self, url, params=None):
                return httpx.Response(
                    200, json=[make_matter(MatterId=1)],
                    request=httpx.Request("GET", url))

            def close(self):
                closed["n"] += 1

        monkeypatch.setattr(ingest.httpx, "Client", _OwnedClient)
        out = ingest.fetch_matters("phila", page_size=200)
        assert len(out) == 1
        assert closed["n"] == 1


# ===========================================================================
# normalize_matter — mapping, title cleaning, date parsing, url building
# ===========================================================================


class TestNormalizeMatter:
    def test_maps_all_fields(self, make_matter):
        doc = ingest.normalize_matter(make_matter(), client="phila")
        assert doc.source_ref == "27386"
        assert doc.file_no == "260633"
        assert doc.doc_type == "Ordinance"
        assert doc.status == "IN COMMITTEE"
        assert doc.body_name == "CITY COUNCIL"
        assert doc.intro_date == date(2026, 6, 11)

    def test_source_ref_is_stringified_int(self, make_matter):
        doc = ingest.normalize_matter(make_matter(MatterId=555), client="phila")
        assert doc.source_ref == "555"

    def test_html_and_entities_stripped_from_title(self, make_matter):
        doc = ingest.normalize_matter(
            make_matter(MatterTitle="<b>An Ordinance</b> &amp; more"), client="phila")
        assert doc.title == "An Ordinance & more"

    def test_title_falls_back_to_matter_name(self, make_matter):
        doc = ingest.normalize_matter(
            make_matter(MatterTitle=None, MatterName="Fallback name"), client="phila")
        assert doc.title == "Fallback name"

    def test_non_string_title_coerced(self, make_matter):
        doc = ingest.normalize_matter(make_matter(MatterTitle=12345), client="phila")
        assert doc.title == "12345"

    def test_empty_title_becomes_empty_string(self, make_matter):
        doc = ingest.normalize_matter(
            make_matter(MatterTitle=None, MatterName=None), client="phila")
        assert doc.title == ""

    def test_zero_width_chars_stripped(self, make_matter):
        doc = ingest.normalize_matter(
            make_matter(MatterTitle="A​title﻿"), client="phila")
        assert "​" not in doc.title and "﻿" not in doc.title

    def test_bad_date_becomes_none(self, make_matter):
        doc = ingest.normalize_matter(
            make_matter(MatterIntroDate="not-a-date"), client="phila")
        assert doc.intro_date is None

    def test_missing_date_becomes_none(self, make_matter):
        doc = ingest.normalize_matter(
            make_matter(MatterIntroDate=None), client="phila")
        assert doc.intro_date is None

    def test_url_uses_guid_deep_link(self, make_matter):
        doc = ingest.normalize_matter(make_matter(MatterGuid="GUID-1"), client="phila")
        assert "LegislationDetail.aspx?GUID=GUID-1" in doc.url
        assert doc.url.startswith("https://phila.legistar.com")

    def test_url_falls_back_to_api_resource(self, make_matter):
        m = make_matter(MatterId=42)
        m.pop("MatterGuid")
        doc = ingest.normalize_matter(m, client="phila")
        assert doc.url.endswith("/phila/Matters/42")

    def test_raw_record_preserved(self, make_matter):
        m = make_matter()
        doc = ingest.normalize_matter(m, client="phila")
        assert doc.raw is m

    def test_transmittal_preamble_stripped_from_title(self, make_matter):
        # The shared administration preamble is removed so the chunk leads with the
        # bill's own substance (which is what drives retrieval), not the salutation
        # boilerplate every filed Matter shares.
        raw = (
            "June 9, 2026\n\n"
            "TO THE PRESIDENT AND MEMBERS OF THE COUNCIL OF THE CITY OF PHILADELPHIA:\n\n"
            "I am submitting herewith for the consideration of your Honorable Body "
            "the following proposed Ordinance:\n\n"
            "AN ORDINANCE\n\n"
            "Adding a new Chapter 12-1800 to regulate curbside loading zones."
        )
        doc = ingest.normalize_matter(make_matter(MatterTitle=raw), client="phila")
        assert doc.title.startswith("Adding a new Chapter 12-1800")
        assert "TO THE PRESIDENT" not in doc.title


class TestStripBoilerplate:
    def test_strips_salutation_preamble(self):
        raw = (
            "May 26, 2026\n\nTO THE PRESIDENT AND MEMBERS OF THE COUNCIL OF THE "
            "CITY OF PHILADELPHIA:\n\nRESOLUTION\n\nAuthorizing a hearing on transit."
        )
        assert ingest._strip_boilerplate(raw) == "Authorizing a hearing on transit."

    def test_plain_title_unchanged(self):
        # No salutation -> nothing to strip; a normal Council title is untouched.
        title = "Recognizing May 2026 as National Tennis Month."
        assert ingest._strip_boilerplate(title) == title

    def test_only_fires_on_the_salutation(self):
        # Text that merely mentions the president is NOT a transmittal preamble.
        title = "Honoring the President of the Community College Board."
        assert ingest._strip_boilerplate(title) == title

    def test_preamble_without_doc_type_header(self):
        # Cover-letters have no "AN ORDINANCE" header; the salutation still goes.
        raw = (
            "June 10, 2026\n\nTO THE PRESIDENT AND MEMBERS OF THE COUNCIL OF THE "
            "CITY OF PHILADELPHIA:\n\nI am pleased to advise you that I signed "
            "Bill No. 260424."
        )
        out = ingest._strip_boilerplate(raw)
        assert "TO THE PRESIDENT" not in out
        assert "Bill No. 260424" in out


class TestParseIntroDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-06-11T00:00:00", date(2026, 6, 11)),
            ("2026-01-02", date(2026, 1, 2)),
            (None, None),
            ("", None),
            ("garbage", None),
            ("2026-13-40T00:00:00", None),  # out-of-range month/day
        ],
    )
    def test_parse(self, value, expected):
        assert ingest._parse_intro_date(value) == expected


# ===========================================================================
# Chunking — overlap, single window, empties, zero-width
# ===========================================================================


class TestChunking:
    def test_short_text_one_chunk(self):
        assert ingest._split_text("short", 800, 100) == ["short"]

    def test_empty_text_no_chunks(self):
        assert ingest._split_text("", 800, 100) == []

    def test_whitespace_only_no_chunks(self):
        assert ingest._split_text("   \n\t ", 800, 100) == []

    def test_zero_width_only_no_chunks(self):
        assert ingest._split_text("​﻿", 800, 100) == []

    def test_long_text_splits_with_overlap(self):
        text = "a" * 1000
        chunks = ingest._split_text(text, 800, 100)
        assert len(chunks) >= 2
        # step = 700; second window starts at index 700.
        assert chunks[0] == "a" * 800

    def test_exact_size_boundary_one_chunk(self):
        text = "b" * 800
        assert ingest._split_text(text, 800, 100) == [text]

    def test_one_over_size_yields_two_chunks(self):
        # size+1 chars must cross the single-window boundary: [0:size] then a
        # 1-char tail window. Exercises the <= size boundary from the other side.
        text = "c" * 801
        chunks = ingest._split_text(text, 800, 100)
        assert chunks[0] == "c" * 800
        assert chunks[-1].endswith("c") and len(chunks[-1]) >= 1

    def test_interior_whitespace_window_dropped(self):
        # An interior window that strips to empty must be dropped WITHOUT ending
        # the walk (the `if window:` False -> no break branch). size=5 overlap=0:
        # windows are 'abcde', '     '(->dropped), 'fghij'.
        assert ingest._split_text("abcde     fghij", 5, 0) == ["abcde", "fghij"]

    def test_no_overlap_tiles_without_gaps(self):
        # overlap=0 -> step==size -> non-overlapping tiles that exactly reconstruct.
        text = "abcdefghij"
        chunks = ingest._split_text(text, 4, 0)
        assert "".join(chunks) == text

    def test_overlap_ge_size_stride_guarded(self):
        # overlap >= size would make step<=0; the max(1, ...) guard forces stride 1
        # so we still terminate (via the start+size>=len break) instead of looping
        # forever or raising on a zero range step.
        chunks = ingest._split_text("abcdef", 3, 3)
        assert chunks  # terminates and returns something
        assert all(c == c.strip() and c for c in chunks)

    def test_overlap_gt_size_output_is_correct_not_just_terminates(self):
        # overlap > size (size=5, overlap=10 -> step=max(1,-5)=1, a dense 1-char
        # slide). Beyond mere termination, assert the OUTPUT semantics:
        text = "abcdefghij"
        chunks = ingest._split_text(text, 5, 10)
        # 1. no window exceeds the requested size.
        assert all(len(c) <= 5 for c in chunks)
        # 2. chunks appear in source order (each window starts at a later index).
        assert all(text.find(chunks[i]) <= text.find(chunks[i + 1])
                   for i in range(len(chunks) - 1))
        # 3. the union of chunk characters covers every character of the input
        #    (a dense stride-1 slide can drop nothing).
        assert set("".join(chunks)) == set(text)
        # 4. deterministic: running it again is identical, so chunk_index is stable.
        assert ingest._split_text(text, 5, 10) == chunks

    def test_overlap_gt_size_chunk_index_strictly_increasing(self):
        # Under the pathological overlap>size config, chunk_index on the document
        # chunks must still be strictly increasing / deterministic.
        doc = CivicDocument(
            source_ref="1", doc_type="O", file_no="1", title="abcdefghij",
            body_name="C", status="S", intro_date=None, url="u", raw={},
        )
        # Drive the small pathological window through the real chunker knobs.
        import unittest.mock as _mock
        with _mock.patch.object(ingest, "CHUNK_SIZE_CHARS", 5), \
                _mock.patch.object(ingest, "CHUNK_OVERLAP_CHARS", 10):
            chunks = ingest.chunk_document(doc)
        idxs = [c.chunk_index for c in chunks]
        assert idxs == list(range(len(chunks)))
        assert all(idxs[i] < idxs[i + 1] for i in range(len(idxs) - 1))

    def test_chunk_document_indices_are_sequential(self):
        doc = CivicDocument(
            source_ref="1", doc_type="Ordinance", file_no="1",
            title="x" * 2000, body_name="C", status="S",
            intro_date=None, url="u", raw={},
        )
        chunks = ingest.chunk_document(doc)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert all(c.source_ref == "1" and c.file_no == "1" for c in chunks)

    @given(st.text(min_size=1, max_size=50).filter(lambda s: s.strip()))
    @hyp_settings(max_examples=100)
    def test_property_short_text_single_nonempty_chunk(self, text):
        chunks = ingest._split_text(text, 800, 100)
        assert len(chunks) <= 1
        for c in chunks:
            assert c == c.strip() and c != ""

    @given(
        text=st.text(max_size=400),
        size=st.integers(min_value=1, max_value=64),
        overlap=st.integers(min_value=0, max_value=64),
    )
    @hyp_settings(max_examples=300)
    def test_property_split_invariants(self, text, size, overlap):
        chunks = ingest._split_text(text, size, overlap)
        # 1. terminates and returns a list (implicit: no hang/raise across the space)
        assert isinstance(chunks, list)
        for c in chunks:
            # 2. every emitted chunk is non-empty and stripped
            assert c and c == c.strip()
            # 3. no window ever exceeds the requested size
            assert len(c) <= size

    @given(
        text=st.text(max_size=400),
        size=st.integers(min_value=1, max_value=64),
        overlap=st.integers(min_value=0, max_value=64),
    )
    @hyp_settings(max_examples=200)
    def test_property_split_deterministic(self, text, size, overlap):
        # Same input -> same chunks, so chunk_index is stable across re-ingests.
        assert ingest._split_text(text, size, overlap) == ingest._split_text(
            text, size, overlap
        )

    @given(st.text(min_size=1, max_size=200))
    @hyp_settings(max_examples=200)
    def test_property_no_cf_chars_in_output(self, text):
        # Zero-width / format (Cf) chars are dropped before the emptiness test, so
        # they must never appear in any emitted chunk regardless of the input.
        import unicodedata

        for c in ingest._split_text(text, 40, 5):
            assert all(unicodedata.category(ch) != "Cf" for ch in c)

    @given(st.integers(), st.text(max_size=30), st.text(max_size=30))
    @hyp_settings(max_examples=100)
    def test_property_normalize_never_raises_on_scalar_fields(
        self, matter_id, title, file_no
    ):
        # normalize_matter must be total over arbitrary scalar field values: it
        # coerces MatterId/title and never raises on well-typed-but-arbitrary text.
        doc = ingest.normalize_matter(
            {"MatterId": matter_id, "MatterTitle": title, "MatterFile": file_no},
            client="phila",
        )
        assert doc.source_ref == str(matter_id)
        assert isinstance(doc.title, str)


# ===========================================================================
# upsert_documents — batching + delegation (DB/embedder patched)
# ===========================================================================


class TestUpsertDocuments:
    def test_empty_docs_returns_zero_without_touching_db(self, monkeypatch):
        # Guard: no embed, no connection when there's nothing to do.
        assert ingest.upsert_documents([]) == 0

    def test_embeds_once_and_delegates_per_doc(self, monkeypatch):
        from contextlib import contextmanager

        embed_calls = {"n": 0}

        def fake_embed(texts):
            embed_calls["n"] += 1
            return [[0.0] * 384 for _ in texts]

        upserts = []

        @contextmanager
        def fake_get_conn():
            # A MagicMock so the connection carries the .commit() that
            # upsert_documents calls to close its single transaction.
            from unittest.mock import MagicMock

            yield MagicMock()

        # Patch the lazily-imported names at their source modules.
        monkeypatch.setattr("app.civic.embeddings.embed_texts", fake_embed)
        monkeypatch.setattr("app.civic.db.get_conn", fake_get_conn)
        monkeypatch.setattr("app.civic.db.upsert_document",
                            lambda conn, doc, chunks: upserts.append(doc.source_ref))
        monkeypatch.setattr("pgvector.psycopg.register_vector", lambda conn: None)

        docs = [
            CivicDocument(source_ref="1", doc_type="O", file_no="1", title="hello one",
                          body_name="C", status="S", intro_date=None, url="u", raw={}),
            CivicDocument(source_ref="2", doc_type="O", file_no="2", title="hello two",
                          body_name="C", status="S", intro_date=None, url="u", raw={}),
        ]
        assert ingest.upsert_documents(docs) == 2
        assert embed_calls["n"] == 1          # ONE batched embed for the whole run
        assert upserts == ["1", "2"]          # each doc delegated once

    def test_docs_with_no_chunks_skip_embed_but_still_upsert(self, monkeypatch):
        # A doc whose title yields zero chunks (empty/whitespace title) must not
        # trigger an embed call (the `if flat_chunks:` False branch) yet must
        # still be upserted so its metadata row lands. Guards the "never embed []"
        # promise: some backends dislike an empty batch.
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        embed_calls = {"n": 0}

        def fake_embed(texts):
            embed_calls["n"] += 1
            return [[0.0] * 384 for _ in texts]

        upserts = []

        @contextmanager
        def fake_get_conn():
            yield MagicMock()

        monkeypatch.setattr("app.civic.embeddings.embed_texts", fake_embed)
        monkeypatch.setattr("app.civic.db.get_conn", fake_get_conn)
        monkeypatch.setattr(
            "app.civic.db.upsert_document",
            lambda conn, doc, chunks: upserts.append((doc.source_ref, len(chunks))),
        )
        monkeypatch.setattr("pgvector.psycopg.register_vector", lambda conn: None)

        docs = [
            CivicDocument(source_ref="1", doc_type="O", file_no="1", title="   ",
                          body_name="C", status="S", intro_date=None, url="u", raw={}),
        ]
        assert ingest.upsert_documents(docs) == 1
        assert embed_calls["n"] == 0          # empty batch -> embed never called
        assert upserts == [("1", 0)]          # doc still upserted, with zero chunks


# ===========================================================================
# run_ingest — skip id-less, skip malformed, drop empty-title
# ===========================================================================


class TestRunIngest:
    def test_skips_idless_and_empty_title_upserts_rest(self, monkeypatch,
                                                        sample_matters):
        captured = {}

        def fake_upsert(docs):
            captured["docs"] = docs
            return len(docs)

        monkeypatch.setattr(ingest, "fetch_matters", lambda client: sample_matters)
        monkeypatch.setattr(ingest, "upsert_documents", fake_upsert)

        count = ingest.run_ingest("phila")
        refs = {d.source_ref for d in captured["docs"]}
        # id-less (MatterId=None) skipped; null-title (id 3) dropped (empty title).
        assert "None" not in refs
        assert "3" not in refs
        # Clean, HTML, numeric-title, bad-date records survive (all have text).
        assert {"1", "2", "5", "6"}.issubset(refs)
        assert count == len(captured["docs"])

    def test_all_idless_yields_zero(self, monkeypatch, make_matter):
        matters = [make_matter(MatterId=None), make_matter(MatterId=None)]
        monkeypatch.setattr(ingest, "fetch_matters", lambda client: matters)
        monkeypatch.setattr(ingest, "upsert_documents", lambda docs: len(docs))
        assert ingest.run_ingest("phila") == 0

    def test_malformed_record_skipped_not_fatal(self, monkeypatch, make_matter):
        good = make_matter(MatterId=1, MatterTitle="ok")
        monkeypatch.setattr(ingest, "fetch_matters", lambda client: [good])

        real_normalize = ingest.normalize_matter
        calls = {"n": 0}

        def flaky_normalize(m, client=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("bad record")
            return real_normalize(m, client=client)

        # Two matters: first raises during normalize (skipped), second succeeds.
        monkeypatch.setattr(ingest, "fetch_matters",
                            lambda client: [make_matter(MatterId=1),
                                            make_matter(MatterId=2, MatterTitle="ok")])
        monkeypatch.setattr(ingest, "normalize_matter", flaky_normalize)
        monkeypatch.setattr(ingest, "upsert_documents", lambda docs: len(docs))
        assert ingest.run_ingest("phila") == 1
