"""Local, $0 text embeddings via fastembed (BAAI/bge-small-en-v1.5).

Adapted essentially verbatim from AwardGuard's ``backend/app/core/embeddings.py``
— the embedding contract is domain-agnostic, so there is nothing civic-specific
here beyond reuse.

Why fastembed: it runs the model through ONNX Runtime, so there is NO torch
dependency, the model is ~130MB, and everything runs locally and free. The model
outputs 384-dimensional vectors, which is why the DB column is ``vector(384)``.

The model is loaded lazily and cached as a module-level singleton (``lru_cache``):
the first call downloads/initialises it (slow, once), subsequent calls reuse it.
The ``fastembed`` import stays INSIDE ``_get_model`` so merely importing this
module does not pull in fastembed/onnxruntime — that keeps the unit tests fast
and dependency-free.
"""

from __future__ import annotations

from functools import lru_cache

# Pin the model name in one place so ingest and retrieval can never drift apart.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model():
    """Load and cache the fastembed model (imported lazily so tests stay import-light)."""

    # Imported inside the function so that merely importing this module does not
    # pull in fastembed/onnxruntime — keeps the unit tests fast and dependency-free.
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns one 384-float vector per input text."""

    model = _get_model()
    # fastembed yields numpy arrays; convert to plain lists so psycopg/pgvector
    # and JSON serialisation are happy.
    return [vec.tolist() for vec in model.embed(texts)]


def embed_query(text: str) -> list[float]:
    """Embed a single query string into one 384-float vector."""

    return embed_texts([text])[0]
