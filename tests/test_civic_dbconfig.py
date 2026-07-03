"""EXHAUSTIVE tests for the civic DB + config layers (``app/civic/db.py`` and the
civic-additive fields on ``app/config.py``).

Design constraints (obeyed here, matching the slice's test-infra rules):

  * NO network, NO real LLM, NO real Postgres in the default suite. The pool is
    NEVER opened: every DB test either drives ``upsert_document`` / ``init`` /
    ``get_conn`` against a MagicMock psycopg connection, inspects the DDL/SQL as
    strings, or is gated behind ``skipif`` on real-Postgres availability.
  * The suite stays green with none of Postgres / Ollama / Anthropic present.

This file is intentionally broader than ``test_civic_db_logic.py`` and
``test_civic_config.py``: it drives the pool-lifecycle functions
(``get_pool`` / ``close_pool`` / ``get_conn``), the full column-binding surface
of the upsert, every config field's default + env-override + type behavior, and
adds Hypothesis property tests over the combinatorial input space.

Enumerated cases use ``pytest.mark.parametrize``; the combinatorial input space
is covered with Hypothesis property tests.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest

# The DB layer imports psycopg / psycopg_pool / pgvector at module import. Skip
# the whole file cleanly if those civic deps are absent so collection never
# breaks a bare environment.
db = pytest.importorskip(
    "app.civic.db", reason="civic db deps (pgvector/psycopg/psycopg_pool) absent"
)

from app.civic.schemas import CivicChunk, CivicDocument  # noqa: E402
from app.config import Settings, settings  # noqa: E402


# ===========================================================================
# Shared local builders
# ===========================================================================


def _make_doc(**over) -> CivicDocument:
    base = dict(
        source_ref="27386",
        doc_type="Ordinance",
        file_no="260633",
        title="An Ordinance authorizing a thing.",
        body_name="CITY COUNCIL",
        status="IN COMMITTEE",
        intro_date=None,
        url="https://example.test/1",
        raw={"MatterId": 27386},
    )
    base.update(over)
    return CivicDocument(**base)


def _make_chunks(n: int) -> list[CivicChunk]:
    return [
        CivicChunk(
            source_ref="27386",
            file_no="260633",
            chunk_index=i,
            text=f"chunk {i}",
            embedding=[float(i)] * 3,
        )
        for i in range(n)
    ]


def _fresh_mock_conn():
    """A standalone MagicMock psycopg conn whose cursor() is a context manager."""

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (1,)
    conn._cur = cur
    return conn


def _executed(conn) -> list[str]:
    return [c.args[0].strip() for c in conn._cur.execute.call_args_list]


def _verbs(conn) -> list[str]:
    return [sql.split()[0].upper() for sql in _executed(conn)]


# ===========================================================================
# Pool lifecycle: get_pool / close_pool / get_conn (mocked ConnectionPool)
#
# These functions were previously untested. We patch ``db.ConnectionPool`` with
# a factory so no socket is ever opened, and assert the lazy-singleton contract.
# ===========================================================================


@pytest.fixture
def no_real_pool(monkeypatch):
    """Replace ``db.ConnectionPool`` with a MagicMock factory and reset the
    module singleton before AND after, so pool tests never open a socket and
    never leak a fake pool into other tests."""

    created = []

    def _factory(*args, **kwargs):
        pool = MagicMock(name="FakeConnectionPool")
        pool._init_args = args
        pool._init_kwargs = kwargs
        created.append(pool)
        return pool

    monkeypatch.setattr(db, "ConnectionPool", _factory)
    monkeypatch.setattr(db, "_pool", None, raising=False)
    yield created
    # Drop any singleton this test created so nothing bleeds across tests.
    monkeypatch.setattr(db, "_pool", None, raising=False)


def test_get_pool_creates_pool_on_first_call(no_real_pool):
    pool = db.get_pool()
    assert pool is not None
    assert len(no_real_pool) == 1  # exactly one pool constructed


def test_get_pool_is_a_singleton_across_calls(no_real_pool):
    first = db.get_pool()
    second = db.get_pool()
    assert first is second
    assert len(no_real_pool) == 1  # NOT reconstructed on the second call


def test_get_pool_uses_settings_conninfo(no_real_pool, monkeypatch):
    monkeypatch.setattr(
        settings, "civic_database_url", "postgresql://u:p@h:5432/x", raising=False
    )
    db.get_pool()
    kwargs = no_real_pool[0]._init_kwargs
    assert kwargs["conninfo"] == "postgresql://u:p@h:5432/x"


def test_get_pool_opens_eagerly_with_bounded_size(no_real_pool):
    db.get_pool()
    kwargs = no_real_pool[0]._init_kwargs
    # Opened eagerly (so worker threads exist / must be torn down) and bounded.
    assert kwargs["open"] is True
    assert kwargs["min_size"] == 1
    assert kwargs["max_size"] == 10
    assert kwargs["min_size"] <= kwargs["max_size"]


def test_close_pool_closes_and_drops_singleton(no_real_pool):
    pool = db.get_pool()
    db.close_pool()
    pool.close.assert_called_once()
    assert db._pool is None


def test_close_pool_is_a_noop_when_never_opened(no_real_pool):
    # Import-time / never-used process: close_pool must not blow up on a None pool.
    assert db._pool is None
    db.close_pool()  # must not raise
    assert db._pool is None
    assert len(no_real_pool) == 0  # nothing was ever constructed


def test_get_pool_recreates_after_close(no_real_pool):
    first = db.get_pool()
    db.close_pool()
    second = db.get_pool()
    assert first is not second
    assert len(no_real_pool) == 2


def test_close_pool_is_idempotent(no_real_pool):
    db.get_pool()
    db.close_pool()
    db.close_pool()  # second call on an already-None singleton must be safe
    assert db._pool is None


def test_get_conn_yields_pooled_connection_and_returns_it(no_real_pool):
    # get_conn is a context manager that borrows conn from pool.connection() and
    # returns it on exit. Wire the fake pool's connection() as a context manager.
    fake_conn = MagicMock(name="pooled_conn")
    pool = db.get_pool()
    pool.connection.return_value.__enter__.return_value = fake_conn

    with db.get_conn() as conn:
        assert conn is fake_conn

    pool.connection.return_value.__exit__.assert_called()  # returned to the pool


def test_get_conn_creates_pool_lazily_if_absent(no_real_pool):
    # Entering get_conn with no pool yet must construct exactly one.
    assert db._pool is None
    db.get_pool().connection.return_value.__enter__.return_value = MagicMock()
    with db.get_conn():
        pass
    assert len(no_real_pool) == 1


# ===========================================================================
# init(): drives every DDL statement then commits (mocked get_conn)
# ===========================================================================


@pytest.fixture
def patched_get_conn(monkeypatch):
    """Patch ``db.get_conn`` to yield a fresh mock conn; return that conn."""

    conn = _fresh_mock_conn()

    @contextmanager
    def _fake():
        yield conn

    monkeypatch.setattr(db, "get_conn", _fake)
    return conn


def test_init_executes_one_statement_per_ddl(patched_get_conn):
    db.init()
    assert patched_get_conn._cur.execute.call_count == len(db._DDL_STATEMENTS)


def test_init_commits_exactly_once(patched_get_conn):
    db.init()
    patched_get_conn.commit.assert_called_once()


def test_init_executes_ddl_in_declared_order(patched_get_conn):
    db.init()
    executed = _executed(patched_get_conn)
    expected = [s.strip() for s in db._DDL_STATEMENTS]
    assert executed == expected


def test_init_creates_extension_before_any_table(patched_get_conn):
    db.init()
    verbs_and_sql = _executed(patched_get_conn)
    ext_idx = next(i for i, s in enumerate(verbs_and_sql) if "extension" in s.lower())
    tbl_idx = next(i for i, s in enumerate(verbs_and_sql) if "create table" in s.lower())
    assert ext_idx < tbl_idx


# ===========================================================================
# DDL / schema string-level contract (no execution)
# ===========================================================================


def test_embedding_dim_is_384():
    assert db.EMBEDDING_DIM == 384


def test_ddl_first_statement_enables_vector_extension():
    assert "create extension if not exists vector" in db._DDL_STATEMENTS[0].lower()


@pytest.mark.parametrize(
    "needle",
    [
        "create table if not exists civic_documents",
        "create table if not exists civic_chunks",
        "jurisdiction text not null default 'phila'",
        "source_ref text not null",
        "unique (jurisdiction, source_ref)",
        "raw jsonb not null",
        "loaded_at timestamptz not null default now()",
        "document_id bigint not null references civic_documents(id) on delete cascade",
        "unique (document_id, chunk_index)",
        "tsvector generated always as",
        "stored",
        "create index if not exists civic_chunks_tsv_gin",
        "using gin (tsv)",
        "create index if not exists civic_chunks_embedding_ivfflat",
        "using ivfflat",
        "vector_cosine_ops",
        "with (lists = 100)",
        "create index if not exists civic_documents_jurisdiction_idx",
        "create table if not exists civic_sponsors",
        "create index if not exists civic_sponsors_name_idx",
    ],
)
def test_ddl_declares_expected_object(needle):
    import re

    # Collapse the column-alignment whitespace so needles are insensitive to it.
    blob = re.sub(r"\s+", " ", " ".join(db._DDL_STATEMENTS)).lower()
    assert needle in blob


def test_vector_column_width_matches_embedding_dim():
    blob = " ".join(db._DDL_STATEMENTS).lower()
    assert f"vector({db.EMBEDDING_DIM})".lower() in blob


def test_no_ddl_statement_hardcodes_a_different_vector_width():
    # Guard against a stray VECTOR(1536)/(768) drift that would silently break
    # inserts. The only vector(...) width anywhere must be EMBEDDING_DIM.
    import re

    blob = " ".join(db._DDL_STATEMENTS).lower()
    widths = {int(w) for w in re.findall(r"vector\((\d+)\)", blob)}
    assert widths == {db.EMBEDDING_DIM}


def test_all_ddl_statements_are_idempotent():
    for stmt in db._DDL_STATEMENTS:
        low = stmt.strip().lower()
        # Every statement is safe to re-run: CREATE/ALTER ... IF (NOT) EXISTS, or a
        # DO block that guards its ALTER with its own existence check.
        assert (
            "if not exists" in low
            or "if exists" in low
            or low.startswith("do $$")
        )


def test_ddl_has_expected_statement_count():
    # extension + documents table + 3 migration stmts (add col, drop old constraint,
    # add composite constraint) + jurisdiction index + chunks table + 2 chunk
    # indexes + sponsors table + 2 sponsor indexes.
    assert len(db._DDL_STATEMENTS) == 12


def test_tsv_generated_from_text_with_english_config():
    chunks_ddl = next(
        s
        for s in db._DDL_STATEMENTS
        if "civic_chunks" in s.lower() and "create table" in s.lower()
    )
    low = chunks_ddl.lower()
    assert "to_tsvector('english', coalesce(text, ''))" in low
    assert "stored" in low


def test_chunks_cascade_delete_from_documents():
    chunks_ddl = next(
        s
        for s in db._DDL_STATEMENTS
        if "civic_chunks" in s.lower() and "create table" in s.lower()
    )
    assert "on delete cascade" in chunks_ddl.lower()


# ===========================================================================
# upsert SQL constants: the ON CONFLICT idempotency contract
# ===========================================================================


def test_document_upsert_conflicts_on_jurisdiction_source_ref():
    low = db._UPSERT_DOCUMENT_SQL.lower()
    assert "on conflict (jurisdiction, source_ref) do update" in low
    assert "returning id" in low


def test_document_upsert_touches_loaded_at_on_conflict():
    low = db._UPSERT_DOCUMENT_SQL.lower()
    assert "loaded_at" in low and "now()" in low


def test_chunk_insert_conflicts_on_document_id_chunk_index():
    low = db._INSERT_CHUNK_SQL.lower()
    assert "on conflict (document_id, chunk_index) do update" in low


@pytest.mark.parametrize(
    "col",
    ["doc_type", "file_no", "title", "body_name", "status", "intro_date", "url", "raw"],
)
def test_document_upsert_refreshes_mutable_column(col):
    low = db._UPSERT_DOCUMENT_SQL.lower()
    assert f"excluded.{col}" in low


@pytest.mark.parametrize("col", ["text", "embedding"])
def test_chunk_upsert_refreshes_mutable_column(col):
    low = db._INSERT_CHUNK_SQL.lower()
    assert f"excluded.{col}" in low


def test_upsert_document_sql_placeholder_count_matches_columns():
    # 10 bound params: jurisdiction, source_ref..raw. A mismatch raises at execute.
    assert db._UPSERT_DOCUMENT_SQL.count("%s") == 10


def test_insert_chunk_sql_placeholder_count():
    # 4 bound params: document_id, chunk_index, text, embedding.
    assert db._INSERT_CHUNK_SQL.count("%s") == 4


# ===========================================================================
# upsert_document control flow (mock connection, no Postgres)
# ===========================================================================


def test_upsert_returns_document_id_from_returning_clause():
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (42,)
    assert db.upsert_document(conn, _make_doc(), _make_chunks(1)) == 42


def test_upsert_order_is_parent_delete_then_inserts():
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(), _make_chunks(2))
    assert _verbs(conn) == ["INSERT", "DELETE", "INSERT", "INSERT"]


def test_upsert_deletes_children_by_returned_document_id():
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (7,)
    db.upsert_document(conn, _make_doc(), _make_chunks(1))
    delete_call = next(
        c
        for c in conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("DELETE")
    )
    assert delete_call.args[1] == (7,)


def test_upsert_zero_chunks_deletes_then_inserts_nothing():
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(), [])
    assert _verbs(conn) == ["INSERT", "DELETE"]


def test_upsert_binds_raw_via_json_adapter():
    from psycopg.types.json import Json

    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(raw={"k": "v"}), [])
    bound_raw = conn._cur.execute.call_args_list[0].args[1][-1]
    assert isinstance(bound_raw, Json)


def test_upsert_json_adapter_wraps_the_actual_raw_dict():
    from psycopg.types.json import Json

    conn = _fresh_mock_conn()
    payload = {"MatterId": 99, "nested": {"a": [1, 2, 3]}}
    db.upsert_document(conn, _make_doc(raw=payload), [])
    bound = conn._cur.execute.call_args_list[0].args[1][-1]
    assert isinstance(bound, Json)
    assert bound.obj == payload  # the adapter carries the exact dict


def test_upsert_parent_binds_all_columns_in_order():
    conn = _fresh_mock_conn()
    doc = _make_doc(
        source_ref="S",
        doc_type="D",
        file_no="F",
        title="T",
        body_name="B",
        status="ST",
        intro_date=date(2026, 6, 11),
        url="U",
    )
    db.upsert_document(conn, doc, [])
    params = conn._cur.execute.call_args_list[0].args[1]
    # jurisdiction (default 'phila') is now bound first, then source_ref..url.
    assert params[:9] == ("phila", "S", "D", "F", "T", "B", "ST", date(2026, 6, 11), "U")


@pytest.mark.parametrize(
    "field,value",
    [
        ("doc_type", None),
        ("file_no", None),
        ("title", None),
        ("body_name", None),
        ("status", None),
        ("intro_date", None),
        ("url", None),
    ],
)
def test_upsert_passes_nullable_columns_through_as_none(field, value):
    # Every nullable Legistar field must be bound as-is (None), not coerced to "".
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(**{field: value}), [])
    params = conn._cur.execute.call_args_list[0].args[1]
    order = [
        "jurisdiction",
        "source_ref",
        "doc_type",
        "file_no",
        "title",
        "body_name",
        "status",
        "intro_date",
        "url",
    ]
    assert params[order.index(field)] is None


def test_upsert_inserts_each_chunk_with_index_text_embedding():
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (5,)
    chunks = _make_chunks(3)
    db.upsert_document(conn, _make_doc(), chunks)
    inserts = [
        c
        for c in conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("INSERT")
        and "civic_chunks" in c.args[0].lower()
    ]
    assert len(inserts) == 3
    for chunk, call in zip(chunks, inserts):
        assert call.args[1] == (5, chunk.chunk_index, chunk.text, chunk.embedding)


def test_upsert_preserves_chunk_order():
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (3,)
    chunks = _make_chunks(4)
    db.upsert_document(conn, _make_doc(), chunks)
    inserted_indexes = [
        c.args[1][1]
        for c in conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("INSERT")
        and "civic_chunks" in c.args[0].lower()
    ]
    assert inserted_indexes == [0, 1, 2, 3]


def test_upsert_binds_none_embedding_when_chunk_unembedded():
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (1,)
    chunk = CivicChunk(
        source_ref="27386", file_no="260633", chunk_index=0, text="x", embedding=None
    )
    db.upsert_document(conn, _make_doc(), [chunk])
    insert = next(
        c
        for c in conn._cur.execute.call_args_list
        if "civic_chunks" in c.args[0].lower()
        and c.args[0].strip().upper().startswith("INSERT")
    )
    assert insert.args[1][3] is None


@pytest.mark.parametrize("n_chunks", [0, 1, 2, 5, 25, 100])
def test_upsert_insert_count_matches_chunk_count(n_chunks):
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(), _make_chunks(n_chunks))
    chunk_inserts = [
        c
        for c in conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("INSERT")
        and "civic_chunks" in c.args[0].lower()
    ]
    assert len(chunk_inserts) == n_chunks


def test_upsert_does_not_commit_leaving_txn_to_caller():
    # upsert_document must NOT commit — the caller owns the transaction boundary
    # (register_vector + commit happen around it in the ingest write path).
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(), _make_chunks(2))
    conn.commit.assert_not_called()


def test_upsert_opens_a_cursor_context_manager():
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(), [])
    conn.cursor.assert_called()
    conn.cursor.return_value.__enter__.assert_called()


# ===========================================================================
# Property-based (Hypothesis): upsert control flow over the input space
# ===========================================================================


from hypothesis import given, settings as hyp_settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


@hyp_settings(max_examples=60, deadline=None)
@given(n=st.integers(min_value=0, max_value=60))
def test_property_verb_sequence_is_insert_delete_then_n_inserts(n):
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(), _make_chunks(n))
    verbs = _verbs(conn)
    assert verbs[0] == "INSERT"
    assert verbs[1] == "DELETE"
    assert verbs[2:] == ["INSERT"] * n
    assert len(verbs) == 2 + n


@hyp_settings(max_examples=50, deadline=None)
@given(doc_id=st.integers(min_value=1, max_value=10**9))
def test_property_returns_and_scopes_delete_to_any_document_id(doc_id):
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (doc_id,)
    returned = db.upsert_document(conn, _make_doc(), _make_chunks(2))
    assert returned == doc_id
    delete_call = next(
        c
        for c in conn._cur.execute.call_args_list
        if c.args[0].strip().upper().startswith("DELETE")
    )
    assert delete_call.args[1] == (doc_id,)
    # Every child insert is scoped to the same parent id.
    for c in conn._cur.execute.call_args_list:
        if c.args[0].strip().upper().startswith("INSERT") and "civic_chunks" in c.args[0].lower():
            assert c.args[1][0] == doc_id


@hyp_settings(max_examples=40, deadline=None)
@given(
    text_field=st.text(min_size=0, max_size=40),
    idx=st.integers(min_value=0, max_value=10_000),
)
def test_property_chunk_binding_is_faithful(text_field, idx):
    conn = _fresh_mock_conn()
    conn._cur.fetchone.return_value = (11,)
    chunk = CivicChunk(
        source_ref="s",
        file_no="f",
        chunk_index=idx,
        text=text_field,
        embedding=[0.1, 0.2, 0.3],
    )
    db.upsert_document(conn, _make_doc(), [chunk])
    insert = next(
        c
        for c in conn._cur.execute.call_args_list
        if "civic_chunks" in c.args[0].lower()
        and c.args[0].strip().upper().startswith("INSERT")
    )
    assert insert.args[1] == (11, idx, text_field, [0.1, 0.2, 0.3])


@hyp_settings(max_examples=40, deadline=None)
@given(
    source_ref=st.text(min_size=1, max_size=20),
    title=st.one_of(st.none(), st.text(max_size=40)),
)
def test_property_parent_source_ref_and_title_bound_verbatim(source_ref, title):
    conn = _fresh_mock_conn()
    db.upsert_document(conn, _make_doc(source_ref=source_ref, title=title), [])
    params = conn._cur.execute.call_args_list[0].args[1]
    assert params[1] == source_ref  # source_ref position (jurisdiction is [0])
    assert params[4] == title  # title position


# ===========================================================================
# CONFIG: civic-additive Settings fields
#
# Fresh Settings instances (not the shared singleton) so defaults / env overrides
# are asserted without leaking state.
# ===========================================================================


CIVIC_DEFAULTS = {
    "civic_database_url": "postgresql://tf:tf@localhost:5432/civicscope",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "llama3.1:8b",
    "llm_provider": "ollama",
    "anthropic_api_key": None,
    "anthropic_model": "claude-3-5-sonnet-latest",
    "legistar_client": "phila",
    "ingest_token": None,
}

_ALL_ENV_KEYS = [k.upper() for k in CIVIC_DEFAULTS] + ["DATABASE_PATH"]


def _fresh_settings(monkeypatch) -> Settings:
    for key in _ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return Settings()


# --- Defaults ---------------------------------------------------------------


def test_base_app_boots_with_zero_config(monkeypatch):
    assert _fresh_settings(monkeypatch).database_path == "tasks.db"


@pytest.mark.parametrize("field,expected", list(CIVIC_DEFAULTS.items()))
def test_civic_field_default(monkeypatch, field, expected):
    assert getattr(_fresh_settings(monkeypatch), field) == expected


def test_optional_secrets_default_to_none_not_empty(monkeypatch):
    s = _fresh_settings(monkeypatch)
    # None (not "") is the documented default the 503/refusal gates key off.
    assert s.ingest_token is None
    assert s.anthropic_api_key is None


def test_no_civic_field_is_required(monkeypatch):
    # Fail-loud is explicitly NOT wanted: an empty env must never raise.
    for key in _ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    Settings()  # must not raise


# --- Env overrides ----------------------------------------------------------


@pytest.mark.parametrize(
    "env_key,env_val,field",
    [
        ("CIVIC_DATABASE_URL", "postgresql://u:p@db:5432/other", "civic_database_url"),
        ("OLLAMA_HOST", "http://ollama:11434", "ollama_host"),
        ("OLLAMA_MODEL", "llama3.2:1b", "ollama_model"),
        ("LLM_PROVIDER", "anthropic", "llm_provider"),
        ("ANTHROPIC_API_KEY", "sk-ant-test", "anthropic_api_key"),
        ("ANTHROPIC_MODEL", "claude-3-5-haiku-latest", "anthropic_model"),
        ("LEGISTAR_CLIENT", "nyc", "legistar_client"),
        ("INGEST_TOKEN", "dev-secret", "ingest_token"),
    ],
)
def test_env_override_each_field(monkeypatch, env_key, env_val, field):
    _fresh_settings(monkeypatch)
    monkeypatch.setenv(env_key, env_val)
    assert getattr(Settings(), field) == env_val


@pytest.mark.parametrize("env_key", ["ingest_token", "INGEST_TOKEN", "Ingest_Token"])
def test_env_var_names_case_insensitive(monkeypatch, env_key):
    _fresh_settings(monkeypatch)
    monkeypatch.setenv(env_key, "from-env")
    assert Settings().ingest_token == "from-env"


def test_env_override_does_not_disturb_other_fields(monkeypatch):
    # Setting one env var must leave every OTHER field at its default.
    _fresh_settings(monkeypatch)
    monkeypatch.setenv("INGEST_TOKEN", "only-this")
    s = Settings()
    assert s.ingest_token == "only-this"
    assert s.llm_provider == "ollama"
    assert s.civic_database_url == CIVIC_DEFAULTS["civic_database_url"]


def test_empty_string_env_value_is_honored_not_defaulted(monkeypatch):
    # An explicitly-set empty INGEST_TOKEN is a *provided* value (falsy), distinct
    # from the None default. The router treats both as "disabled" but config must
    # faithfully carry what the operator set.
    _fresh_settings(monkeypatch)
    monkeypatch.setenv("INGEST_TOKEN", "")
    assert Settings().ingest_token == ""


@pytest.mark.parametrize(
    "provider", ["ollama", "anthropic", "OLLAMA", "AnThRoPiC", "unknown-backend"]
)
def test_llm_provider_is_free_text_not_enum(monkeypatch, provider):
    # llm_provider is a plain str: config does not validate the enum (answer.py
    # dispatches on it and degrades gracefully on an unknown value).
    _fresh_settings(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", provider)
    assert Settings().llm_provider == provider


# --- Type behavior ----------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "civic_database_url",
        "ollama_host",
        "ollama_model",
        "llm_provider",
        "anthropic_model",
        "legistar_client",
    ],
)
def test_non_optional_civic_fields_are_str(monkeypatch, field):
    s = _fresh_settings(monkeypatch)
    assert isinstance(getattr(s, field), str)


@pytest.mark.parametrize("field", ["anthropic_api_key", "ingest_token"])
def test_optional_secret_fields_are_none_or_str(monkeypatch, field):
    s = _fresh_settings(monkeypatch)
    val = getattr(s, field)
    assert val is None or isinstance(val, str)


# --- Shared singleton -------------------------------------------------------


def test_shared_singleton_is_settings_instance():
    assert isinstance(settings, Settings)


@pytest.mark.parametrize("field", list(CIVIC_DEFAULTS))
def test_singleton_exposes_every_civic_field(field):
    # db.py / answer.py / routers read these off the singleton; a missing
    # attribute would be an AttributeError at request time.
    assert hasattr(settings, field)


def test_db_module_reads_conninfo_off_the_singleton(no_real_pool, monkeypatch):
    # Ties config -> db together: get_pool must consult the *live* singleton value
    # so an env-driven override actually reaches the pool.
    monkeypatch.setattr(
        settings, "civic_database_url", "postgresql://x:y@z:5432/db", raising=False
    )
    db.get_pool()
    assert no_real_pool[0]._init_kwargs["conninfo"] == "postgresql://x:y@z:5432/db"


# --- Property-based config: any string round-trips through env --------------


@hyp_settings(max_examples=40, deadline=None)
@given(value=st.text(min_size=1, max_size=60).filter(lambda s: "\x00" not in s))
def test_property_ingest_token_env_roundtrips(monkeypatch, value):
    for key in _ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INGEST_TOKEN", value)
    assert Settings().ingest_token == value


@hyp_settings(max_examples=40, deadline=None)
@given(url=st.text(min_size=1, max_size=80).filter(lambda s: "\x00" not in s))
def test_property_civic_database_url_env_roundtrips(monkeypatch, url):
    for key in _ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CIVIC_DATABASE_URL", url)
    assert Settings().civic_database_url == url


# ===========================================================================
# Gated real-Postgres integration (SKIPS cleanly when no DB is reachable)
# ===========================================================================


def _postgres_available() -> bool:
    try:
        import psycopg
    except Exception:
        return False
    try:
        conn = psycopg.connect(settings.civic_database_url, connect_timeout=2)
    except Exception:
        return False
    conn.close()
    return True


postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason="civic Postgres not reachable — skipping real-DB integration tests",
)


@postgres
def test_init_is_idempotent_against_real_db():
    db.init()
    db.init()  # second call must not raise (IF NOT EXISTS everywhere)


@postgres
def test_upsert_roundtrip_and_shrinking_chunks_against_real_db():
    from pgvector.psycopg import register_vector

    doc = CivicDocument(
        source_ref="dbconfig-smoke-1",
        doc_type="BILL",
        file_no="990100",
        title="dbconfig exhaustive smoke",
        body_name="CITY COUNCIL",
        status="INTRODUCED",
        intro_date=None,
        url="https://example.test/990100",
        raw={"MatterId": "dbconfig-smoke-1"},
    )
    two = [
        CivicChunk(
            source_ref="dbconfig-smoke-1",
            file_no="990100",
            chunk_index=i,
            text=f"chunk {i}",
            embedding=[0.0] * db.EMBEDDING_DIM,
        )
        for i in range(2)
    ]
    one = two[:1]

    db.init()
    try:
        with db.get_conn() as conn:
            register_vector(conn)
            db.upsert_document(conn, doc, two)
            conn.commit()
            # Re-ingest with FEWER chunks: delete-then-insert must not orphan.
            db.upsert_document(conn, doc, one)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM civic_chunks c
                    JOIN civic_documents d ON d.id = c.document_id
                    WHERE d.source_ref = %s;
                    """,
                    ("dbconfig-smoke-1",),
                )
                assert cur.fetchone()[0] == 1  # shrank cleanly, no stale row
    finally:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM civic_documents WHERE source_ref = %s;",
                    ("dbconfig-smoke-1",),
                )
            conn.commit()
