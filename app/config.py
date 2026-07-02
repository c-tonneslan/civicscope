from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_path: str = "tasks.db"

    # ------------------------------------------------------------------
    # Civic-intelligence slice (feat/civic-intel-slice).
    #
    # These are ADDITIVE to the existing tasks/auth config. They all carry
    # safe local defaults so the app still boots with zero configuration for
    # local development — the only fail-loud case is a true secret, and the
    # sole optional secret here (ingest_token) is handled by disabling the
    # /civic/ingest route (503) when unset rather than crashing at boot.
    # ------------------------------------------------------------------

    # Postgres + pgvector connection string for the civic corpus. Default
    # matches the pgvector service credentials in docker-compose.yml.
    civic_database_url: str = "postgresql://tf:tf@localhost:5432/taskforge_civic"

    # Local Ollama server + model for the cite-or-refuse synthesis step.
    # Runs fully local at $0 with no API key.
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Which LLM backend writes the grounded answer: "ollama" (default, local,
    # $0) or "anthropic" (Claude API; would require an anthropic key).
    llm_provider: str = "ollama"

    # Optional Anthropic backend config, read by answer.py when
    # llm_provider="anthropic". Left None by default so the default local Ollama
    # path needs no key; when unset the anthropic branch degrades to a refusal
    # explaining the key is missing rather than crashing.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-latest"

    # Legistar Web API client slug for the scoped jurisdiction. This slice is
    # hardcoded to Philadelphia ("phila"), verified against the live API.
    legistar_client: str = "phila"

    # Shared secret gating POST /civic/ingest. OPTIONAL: when unset the ingest
    # route is disabled (503) so the expensive fetch/embed/upsert pipeline is
    # never exposed unauthenticated. When set, callers must send a matching
    # X-Ingest-Token header.
    ingest_token: str | None = None

settings = Settings()
