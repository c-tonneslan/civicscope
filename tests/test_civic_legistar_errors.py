"""The REAL Legistar/Granicus Web API error + edge surface, reproduced offline.

This file is the focused, exhaustive test of the ingest fetch layer against the
documented and observed failure modes of the live Legistar Web API
(``webapi.legistar.com``, client ``phila``, verified 2026-07). Everything runs
through ``httpx.MockTransport`` — no network.

The adverse responses modelled here:

  HTTP status codes the service actually emits
    400  malformed OData query (bad ``$filter``/``$orderby``)
    401  the client's token policy rejects an unauthenticated read
    403  forbidden
    404  unknown client slug (``/v1/<bad>/Matters``)
    429  rate limited — may carry a ``Retry-After`` header
    500  server error
    502/503/504  gateway / unavailable / gateway-timeout (CDN in front of IIS)

  Non-array 200 bodies (the silent-corruption trap)
    The happy path returns a BARE JSON ARRAY. On trouble the service (IIS +
    OData v3) can answer *200* with a JSON OBJECT instead:
      * OData v3 verbose error envelope:
            {"error": {"code": "...", "message": {"lang": "...", "value": "..."}}}
      * ASP.NET/IIS error object: {"Message": "An error has occurred."}
      * OData v2 wrapper: {"d": {"results": [...]}}
      * OData v4 wrapper: {"value": [...]}
    A dict is truthy, so blindly ``extend()``-ing it would splice its string KEYS
    into the results and crash normalize later with an opaque 500. fetch_matters
    must reject any non-array body with a clear, retryable ValueError.

  Pagination stability + the 1000-row cap
    ``$skip`` offset paging on a busy site can silently skip/duplicate rows unless
    the ``$orderby`` is a TOTAL order — hence ``MatterIntroDate desc,MatterId
    desc`` (the MatterId tiebreak forces determinism). Query replies are capped at
    1000 rows, so a page_size above the cap comes back short and the short-page
    rule stops the walk.

Uses ``importorskip`` on the ingest module (dependency-light — the pure fetch
path imports with none of the DB/ONNX stack) and the shared conftest fixtures
(``legistar_client_factory``, ``make_matter``, ``odata_error_body``).
"""

from __future__ import annotations

import httpx
import pytest

ingest = pytest.importorskip("app.civic.ingest")

from tests.conftest import odata_error_body  # noqa: E402


# ===========================================================================
# HTTP status codes
# ===========================================================================


class TestHttpStatusCodes:
    @pytest.mark.parametrize(
        "status",
        [400, 401, 403, 404, 429, 500, 502, 503, 504],
    )
    def test_every_error_status_raises_and_preserves_code(
        self, legistar_client_factory, status
    ):
        # Any non-2xx must raise (fetch calls raise_for_status): a partial/garbage
        # ingest is worse than a visible, retryable error. The status is preserved
        # so a retry policy can tell a 429 (back off) from a 400 (fix the query).
        http = legistar_client_factory([(status, odata_error_body())])
        with pytest.raises(httpx.HTTPStatusError) as exc:
            ingest.fetch_matters("phila", http=http, page_size=200)
        assert exc.value.response.status_code == status

    def test_429_preserves_retry_after_header(self, legistar_client_factory):
        # 429 Too Many Requests can carry Retry-After; it must survive on the
        # response for a future backoff policy to read.
        http = legistar_client_factory(
            [(429, odata_error_body("TooManyRequests", "rate limited"),
              {"Retry-After": "30"})]
        )
        with pytest.raises(httpx.HTTPStatusError) as exc:
            ingest.fetch_matters("phila", http=http, page_size=200)
        assert exc.value.response.status_code == 429
        assert exc.value.response.headers.get("Retry-After") == "30"

    def test_401_body_is_odata_error_envelope(self, legistar_client_factory):
        # A client whose token policy rejects the read returns 401 with the OData
        # error envelope. We still fail loud on the status (the body is incidental).
        http = legistar_client_factory(
            [(401, odata_error_body("Unauthorized", "token required"))]
        )
        with pytest.raises(httpx.HTTPStatusError) as exc:
            ingest.fetch_matters("phila", http=http, page_size=200)
        assert exc.value.response.status_code == 401

    def test_error_on_a_later_page_rejects_the_whole_run(
        self, legistar_client_factory, make_matter
    ):
        # First page is FULL (forces a second request) which then 500s. The partial
        # first page must NOT be returned silently.
        full = [make_matter(MatterId=i) for i in range(3)]
        http = legistar_client_factory([full, (500, odata_error_body())])
        with pytest.raises(httpx.HTTPStatusError):
            ingest.fetch_matters("phila", http=http, page_size=3)


# ===========================================================================
# Non-array 200 bodies — the silent-corruption trap
# ===========================================================================


class TestNonArrayPayloads:
    @pytest.mark.parametrize(
        "payload,type_name",
        [
            (odata_error_body(), "dict"),                      # OData v3 error obj
            ({"Message": "An error has occurred."}, "dict"),   # ASP.NET/IIS error
            ({"d": {"results": []}}, "dict"),                  # OData v2 wrapper
            ({"value": []}, "dict"),                           # OData v4 wrapper
            ({}, "dict"),                                      # bare empty object
            ("throttled", "str"),                              # a JSON string
            (7, "int"),                                        # a JSON number
            (True, "bool"),                                    # a JSON bool
        ],
    )
    def test_non_array_200_is_rejected_with_typed_valueerror(
        self, legistar_client_factory, payload, type_name
    ):
        http = legistar_client_factory([(200, payload)])
        with pytest.raises(ValueError, match=rf"non-list payload \({type_name}\)"):
            ingest.fetch_matters("phila", http=http, page_size=200)

    def test_json_null_200_is_rejected_as_nonetype(self):
        # A body that is the literal JSON ``null`` decodes to None -> not an array,
        # so the isinstance(list) guard rejects it as NoneType. (Sent as raw bytes
        # because httpx.Response(json=None) sends an EMPTY body, not the null
        # literal — a different, still-ValueError, JSON-decode path.)
        def handler(request):
            return httpx.Response(200, content=b"null",
                                  headers={"content-type": "application/json"})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(ValueError, match=r"non-list payload \(NoneType\)"):
            ingest.fetch_matters("phila", http=http, page_size=200)

    def test_empty_body_200_raises_valueerror(self):
        # An EMPTY 200 body (no JSON at all) still surfaces as a ValueError
        # (JSONDecodeError) rather than a silent success — a retryable failure the
        # router converts to a generic 500, never a partial ingest.
        def handler(request):
            return httpx.Response(200, content=b"",
                                  headers={"content-type": "application/json"})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(ValueError):
            ingest.fetch_matters("phila", http=http, page_size=200)

    def test_error_envelope_never_reaches_normalize(self, legistar_client_factory):
        # Regression guard for the actual failure this protects against: if the
        # dict were extend()-ed, normalize would later choke on a string "key". The
        # ValueError must fire at fetch time, before any normalize call.
        http = legistar_client_factory([(200, odata_error_body())])
        with pytest.raises(ValueError):
            ingest.fetch_matters("phila", http=http, page_size=200)


# ===========================================================================
# Pagination stability + the 1000-row cap
# ===========================================================================


class TestPaginationStability:
    def test_orderby_is_a_total_order_with_matterid_tiebreak(self, make_matter):
        seen = []

        def handler(request):
            seen.append(dict(request.url.params))
            skip = int(request.url.params.get("$skip", 0))
            if skip == 0:
                return httpx.Response(
                    200, json=[make_matter(MatterId=i) for i in range(2)]
                )
            return httpx.Response(200, json=[])

        http = httpx.Client(transport=httpx.MockTransport(handler))
        ingest.fetch_matters("phila", http=http, page_size=2)
        # MatterId tiebreak is what makes $skip paging deterministic across pages.
        assert seen[0]["$orderby"] == "MatterIntroDate desc,MatterId desc"

    def test_skip_advances_by_exactly_one_page(self, make_matter):
        seen = []

        def handler(request):
            seen.append(int(request.url.params.get("$skip", 0)))
            skip = int(request.url.params.get("$skip", 0))
            if skip < 4:  # two full pages of 2, then stop
                base = skip
                return httpx.Response(
                    200, json=[make_matter(MatterId=base + i) for i in range(2)]
                )
            return httpx.Response(200, json=[])

        http = httpx.Client(transport=httpx.MockTransport(handler))
        ingest.fetch_matters("phila", http=http, page_size=2)
        assert seen == [0, 2, 4]  # 0, then +2, then +2 (empty -> stop)

    def test_client_slug_is_in_the_request_path(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            return httpx.Response(200, json=[])

        http = httpx.Client(transport=httpx.MockTransport(handler))
        ingest.fetch_matters("nyc", http=http, page_size=5)
        assert seen["path"] == "/v1/nyc/Matters"

    def test_1000_row_cap_short_page_stops_the_walk(
        self, legistar_client_factory, make_matter
    ):
        # Legistar caps replies at 1000 rows: a request for page_size > 1000 comes
        # back short (<= 1000), which the short-page rule treats as the last page.
        capped = [make_matter(MatterId=i) for i in range(1000)]
        http = legistar_client_factory([capped])
        out = ingest.fetch_matters("phila", http=http, page_size=2000, max_pages=5)
        assert len(out) == 1000
