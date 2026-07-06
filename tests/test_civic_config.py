"""Config tests for the civic slice's additive Settings fields.

The civic slice EXTENDS ``app.config.Settings`` with fields that all carry safe
local defaults, so the app boots with zero configuration. The one optional
secret (``ingest_token``) is handled by disabling the ingest route (503) when
unset rather than crashing at boot — verified here at the Settings level and in
tests/test_civic_api.py at the endpoint level.

These tests construct FRESH ``Settings`` instances (not the shared singleton) so
they can assert defaults and env-override behavior without leaking state. Env
vars are applied via ``monkeypatch.setenv`` and cleared per test.

No network / no DB / no LLM — pure config.
"""

from __future__ import annotations

import pytest

from app.config import Settings, settings

# The full set of civic-additive fields and their documented defaults. Kept as a
# single source of truth so the default-value and presence tests can't drift.
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


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def _fresh_settings(monkeypatch) -> Settings:
    """A Settings built with every civic env var cleared, so defaults show through."""

    for key in CIVIC_DEFAULTS:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    return Settings()


def test_base_app_still_boots_with_zero_config(monkeypatch):
    # The whole point of the safe-defaults design: no env, no crash.
    s = _fresh_settings(monkeypatch)
    assert s.database_path == "tasks.db"


@pytest.mark.parametrize("field,expected", list(CIVIC_DEFAULTS.items()))
def test_civic_field_defaults(monkeypatch, field, expected):
    s = _fresh_settings(monkeypatch)
    assert getattr(s, field) == expected


def test_ingest_token_defaults_to_none_not_empty_string(monkeypatch):
    # A subtle but load-bearing distinction: the ingest router treats a falsy
    # token as "disabled". None and "" are both falsy, but None is the documented
    # default and what the 503-when-unset contract keys off.
    s = _fresh_settings(monkeypatch)
    assert s.ingest_token is None


def test_anthropic_key_defaults_to_none(monkeypatch):
    # The default local-Ollama path needs no key; the anthropic branch degrades
    # to a refusal when this is None rather than crashing.
    s = _fresh_settings(monkeypatch)
    assert s.anthropic_api_key is None


# ---------------------------------------------------------------------------
# Env overrides
# ---------------------------------------------------------------------------


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
    s = _fresh_settings(monkeypatch)  # clear all first
    monkeypatch.setenv(env_key, env_val)
    assert getattr(Settings(), field) == env_val


@pytest.mark.parametrize("env_key", ["ingest_token", "INGEST_TOKEN", "Ingest_Token"])
def test_env_var_names_are_case_insensitive(monkeypatch, env_key):
    # pydantic-settings matches env vars case-insensitively; a lower/mixed-case
    # INGEST_TOKEN must still populate the field so deploy configs aren't brittle.
    _fresh_settings(monkeypatch)
    monkeypatch.setenv(env_key, "from-env")
    assert Settings().ingest_token == "from-env"


def test_setting_ingest_token_enables_gate(monkeypatch):
    # Presence of the token is what flips ingest from 503-disabled to auth-gated.
    _fresh_settings(monkeypatch)
    monkeypatch.setenv("INGEST_TOKEN", "s3cret")
    assert Settings().ingest_token == "s3cret"


# ---------------------------------------------------------------------------
# The shared singleton (what the app actually imports)
# ---------------------------------------------------------------------------


def test_shared_singleton_is_a_settings_instance():
    assert isinstance(settings, Settings)


@pytest.mark.parametrize("field", list(CIVIC_DEFAULTS))
def test_singleton_exposes_every_civic_field(field):
    # answer.py / ingest router / db.py all read these off the singleton; a
    # missing attribute would be an AttributeError at request time.
    assert hasattr(settings, field)


def test_no_field_is_required_no_validation_error(monkeypatch):
    # Fail-loud is explicitly NOT wanted here: no civic field is required, so
    # constructing Settings with a totally empty env must never raise.
    for key in list(CIVIC_DEFAULTS) + ["DATABASE_PATH"]:
        monkeypatch.delenv(key.upper(), raising=False)
    Settings()  # must not raise
