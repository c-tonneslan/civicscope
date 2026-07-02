import pytest
import sqlite3
from app import db
from fastapi.testclient import TestClient
from app.main import app, get_db

@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    yield conn
    conn.close()

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test.db"

    conn = sqlite3.connect(test_db)
    db.init_db(conn)
    conn.close()

    def override_get_db():
        conn = sqlite3.connect(test_db)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ===========================================================================
# Civic-slice shared fixtures (no network / no real LLM / no real Postgres).
#
# Everything below supports the exhaustive civic test suite. The design rule:
# the DEFAULT suite must stay green with NO Postgres, NO Ollama, NO Anthropic
# key, and NO live Legistar. We achieve that by mocking httpx transport for
# Legistar, stubbing the LLM synthesis boundary, and building plain
# RetrievedChunk records in-process so retrieval/answer logic is exercised
# without touching a database.
# ===========================================================================

from datetime import date

import httpx


# --- RetrievedChunk builders -----------------------------------------------

def _retrieved_chunk(**overrides):
    """Build a civic ``RetrievedChunk`` with sensible defaults, overridable.

    Imported lazily so a machine missing the civic DB deps (pgvector/psycopg)
    still collects the file; callers that use this fixture already gate on the
    civic import via ``importorskip`` in their own module.
    """

    from app.civic.retrieval import RetrievedChunk

    base = dict(
        chunk_id=1,
        source_ref="27386",
        file_no="260633",
        title="An Ordinance authorizing a thing.",
        chunk_index=0,
        text="An Ordinance authorizing a thing for the City of Philadelphia.",
        doc_type="Ordinance",
        status="IN COMMITTEE",
        intro_date=date(2026, 6, 11),
    )
    base.update(overrides)
    return RetrievedChunk(**base)


@pytest.fixture
def make_chunk():
    """Factory fixture: build a RetrievedChunk with overrides."""

    return _retrieved_chunk


@pytest.fixture
def sample_chunks():
    """A small, deterministic set of retrieved chunks with distinct file_nos."""

    return [
        _retrieved_chunk(
            chunk_id=1, source_ref="27386", file_no="260633",
            title="An Ordinance authorizing a thing.",
            text="An Ordinance authorizing a thing.",
            status="IN COMMITTEE",
        ),
        _retrieved_chunk(
            chunk_id=2, source_ref="27400", file_no="240100-A",
            title="A Resolution recognizing something.",
            text="A Resolution recognizing something.",
            doc_type="Resolution", status="ADOPTED",
        ),
    ]


@pytest.fixture
def null_file_no_chunk():
    """A chunk whose Legistar file_no is null — legitimately happens on real
    records. The answer layer must fall back to keying/citing off source_ref."""

    return _retrieved_chunk(
        chunk_id=9, source_ref="99999", file_no=None,
        title="A communication with no MatterFile.",
        text="A communication with no MatterFile.",
    )


# --- Settings patcher -------------------------------------------------------

@pytest.fixture
def civic_settings(monkeypatch):
    """Patch fields on the shared ``app.config.settings`` for a single test.

    Returns a setter ``set(**kwargs)`` that monkeypatches attributes so nothing
    leaks between tests (monkeypatch restores on teardown).
    """

    from app.config import settings

    def _set(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(settings, key, value, raising=False)
        return settings

    return _set


# --- Fake Legistar Matters --------------------------------------------------

def _matter(**overrides):
    """One realistic raw Legistar Matter dict (the fields ingest keeps)."""

    base = {
        "MatterId": 27386,
        "MatterFile": "260633",
        "MatterName": None,
        "MatterTitle": "An Ordinance authorizing the City to do a thing.",
        "MatterTypeName": "Ordinance",
        "MatterStatusName": "IN COMMITTEE",
        "MatterIntroDate": "2026-06-11T00:00:00",
        "MatterBodyName": "CITY COUNCIL",
        "MatterGuid": "AAAA-BBBB",
    }
    base.update(overrides)
    return base


@pytest.fixture
def make_matter():
    """Factory fixture: build a raw Legistar Matter with overrides."""

    return _matter


@pytest.fixture
def sample_matters():
    """A mixed batch of Matters: clean, HTML-laden, null-title, id-less,
    non-string title, malformed date — exercises the normalize/skip paths."""

    return [
        _matter(MatterId=1, MatterFile="000001", MatterTitle="A clean ordinance."),
        _matter(MatterId=2, MatterFile="000002",
                MatterTitle="<b>An Ordinance</b> &amp; more"),
        _matter(MatterId=3, MatterFile="000003", MatterTitle=None, MatterName=None),
        _matter(MatterId=None, MatterFile="000004", MatterTitle="No id."),
        _matter(MatterId=5, MatterFile="000005", MatterTitle=12345),
        _matter(MatterId=6, MatterFile="000006",
                MatterTitle="Dated", MatterIntroDate="not-a-date"),
    ]


# --- Fake httpx transport for Legistar --------------------------------------

# The OData v3 "verbose" error envelope. On failure Legistar/Granicus (an IIS +
# OData service) can answer with THIS JSON OBJECT instead of the bare array the
# happy path returns — sometimes even under a 200. Shape per the OData v3.0
# JSON-verbose spec: a top-level "error" object with a string "code" and a
# {"lang","value"} "message".
def odata_error_body(code="InternalServerError", message="An error has occurred."):
    """A Legistar/OData-v3 verbose error envelope (a JSON object, not an array)."""

    return {"error": {"code": code, "message": {"lang": "en-US", "value": message}}}


def _make_legistar_transport(pages):
    """Build an ``httpx.MockTransport`` that serves ``pages`` for /Matters.

    ``pages`` is a list where each element is the JSON body for one $skip page
    (a list of Matters, or a non-list to simulate an OData error envelope).
    Requests past the last defined page get an empty list (end-of-data signal).
    A non-2xx page is expressed as a ``(status, body)`` tuple; extra response
    headers (e.g. ``Retry-After`` on a 429) as a ``(status, body, headers)``
    triple.
    """

    page_size = 200

    import json as _json

    def _response(status, body, headers=None):
        # Serialize the body ourselves rather than via httpx's ``json=`` shortcut:
        # ``json=None`` sends an EMPTY body (so resp.json() raises a decode error),
        # but we want a literal JSON ``null`` so the source's isinstance(list) guard
        # is what rejects it. Explicit dumps makes None -> "null" faithfully while
        # still setting the application/json content-type.
        return httpx.Response(
            status,
            content=_json.dumps(body),
            headers={"content-type": "application/json", **(headers or {})},
        )

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params.get("$skip", 0))
        top = int(request.url.params.get("$top", page_size))
        index = skip // top if top else 0
        if index < len(pages):
            entry = pages[index]
            if isinstance(entry, tuple):
                if len(entry) == 3:
                    status, body, headers = entry
                    return _response(status, body, headers)
                status, body = entry
                return _response(status, body)
            return _response(200, entry)
        return _response(200, [])

    return httpx.MockTransport(handler)


@pytest.fixture
def legistar_client_factory():
    """Factory returning an ``httpx.Client`` wired to a mock Legistar transport.

    Usage: ``http = legistar_client_factory([[matter, matter], [matter]])`` then
    pass ``http`` into ``fetch_matters(http=http)``.
    """

    def _factory(pages):
        return httpx.Client(transport=_make_legistar_transport(pages))

    return _factory


# --- Bare TestClient for the civic routers ----------------------------------

@pytest.fixture
def civic_client():
    """A TestClient with no SQLite override — the civic routes don't use it.

    Kept separate from the tasks ``client`` fixture so the two slices never
    share setup. The civic Postgres pool is never opened because every civic
    dependency the tests hit is stubbed at its boundary.
    """

    return TestClient(app)


# --- Stubbed LLM synthesis (no real Ollama / Anthropic) ---------------------

@pytest.fixture
def stub_synthesize(monkeypatch):
    """Patch ``answer._synthesize`` so the answer layer never calls a real LLM.

    Returns a setter ``set(reply)`` where ``reply`` is either the string the
    fake model should return, or a callable ``(question, chunks) -> str`` / an
    ``Exception`` instance to raise (to exercise the graceful-degradation
    paths). Skips cleanly if the civic answer module can't be imported.
    """

    answer = pytest.importorskip("app.civic.answer")

    def _set(reply):
        def _fake(question, chunks):
            if isinstance(reply, BaseException):
                raise reply
            if callable(reply):
                return reply(question, chunks)
            return reply

        monkeypatch.setattr(answer, "_synthesize", _fake)
        return answer

    return _set


@pytest.fixture
def stub_retrieve(monkeypatch):
    """Patch ``answer.retrieve`` so the answer layer never touches Postgres.

    Returns a setter ``set(chunks)`` that makes ``retrieve(question, top_k)``
    return the given list of ``RetrievedChunk`` records regardless of input.
    """

    answer = pytest.importorskip("app.civic.answer")

    def _set(chunks):
        monkeypatch.setattr(answer, "retrieve", lambda q, top_k=6: list(chunks))
        return answer

    return _set


# --- Mock psycopg connection (pure-SQL upsert logic, no Postgres) -----------

@pytest.fixture
def mock_conn():
    """A MagicMock psycopg connection recording SQL executed on its cursor.

    ``conn.cursor()`` is a context manager yielding ``cur``; ``cur.fetchone()``
    returns ``(1,)`` by default (the surviving document id from the upsert
    RETURNING clause). ``conn._cur`` exposes the cursor mock for assertions on
    the executed statements.
    """

    from unittest.mock import MagicMock

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (1,)
    conn._cur = cur
    return conn
