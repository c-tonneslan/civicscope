"""Tests for the local embeddings layer (app.civic.embeddings).

These exercise the REAL vector-conversion contract without downloading the ONNX
model: a fake ``fastembed`` module is injected into ``sys.modules`` so
``_get_model`` constructs a stub whose ``embed`` yields numpy-like objects with
``.tolist()``. That lets us assert the two things every other test patches away:

  * ``embed_texts`` converts each yielded vector to a PLAIN list (not ndarray),
    so psycopg/pgvector and JSON serialisation stay happy.
  * ``embed_query`` unwraps the single-element batch with ``[0]`` and returns a
    FLAT vector, not a list-of-list.
  * ``_get_model`` is a maxsize=1 singleton: the model is constructed exactly
    once across many embed calls, and ``MODEL_NAME`` is passed through.
  * ``EMBEDDING_DIM`` stays pinned at 384 (the DB ``vector(384)`` column).
"""

from __future__ import annotations

import sys
import types

import pytest

embeddings = pytest.importorskip("app.civic.embeddings")


class _FakeVec:
    """A stand-in for a fastembed numpy vector: only ``.tolist()`` is needed."""

    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


def _install_fake_fastembed(monkeypatch, *, vector=(0.1, 0.2)):
    """Inject a fake ``fastembed`` and count TextEmbedding constructions.

    Returns the ``constructions`` list; each element is the ``model_name`` a
    ``TextEmbedding`` was built with. ``embed(texts)`` yields one ``_FakeVec``
    per input text so the batch length matches the input.
    """

    constructions: list[str] = []

    class _TextEmbedding:
        def __init__(self, *, model_name):
            constructions.append(model_name)

        def embed(self, texts):
            for _ in texts:
                yield _FakeVec(vector)

    mod = types.ModuleType("fastembed")
    mod.TextEmbedding = _TextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", mod)
    embeddings._get_model.cache_clear()
    return constructions


@pytest.fixture(autouse=True)
def _clear_model_cache():
    # Never let a real (or fake) model leak between tests via the lru_cache.
    embeddings._get_model.cache_clear()
    yield
    embeddings._get_model.cache_clear()


class TestVectorConversionContract:
    def test_embed_texts_returns_plain_lists(self, monkeypatch):
        _install_fake_fastembed(monkeypatch, vector=(0.1, 0.2))
        out = embeddings.embed_texts(["a", "b"])
        assert out == [[0.1, 0.2], [0.1, 0.2]]
        # Every element must be a plain list, not an ndarray-like: locks the
        # ``vec.tolist()`` conversion so a regression returning raw numpy fails.
        assert all(type(v) is list for v in out)
        assert all(type(x) is float for v in out for x in v)

    def test_embed_query_unwraps_to_flat_vector(self, monkeypatch):
        _install_fake_fastembed(monkeypatch, vector=(0.1, 0.2))
        out = embeddings.embed_query("a")
        # FLAT vector, length 2 — NOT nested [[...]]. Locks the ``[0]`` unwrap.
        assert out == [0.1, 0.2]
        assert len(out) == 2
        assert all(type(x) is float for x in out)
        assert not any(isinstance(x, list) for x in out)

    def test_embed_texts_empty_batch(self, monkeypatch):
        _install_fake_fastembed(monkeypatch)
        assert embeddings.embed_texts([]) == []


class TestModelSingleton:
    def test_model_constructed_once_across_calls(self, monkeypatch):
        constructions = _install_fake_fastembed(monkeypatch)
        embeddings.embed_texts(["a", "b"])
        embeddings.embed_texts(["c"])
        embeddings.embed_query("d")
        # The whole point of the lru_cache(maxsize=1) singleton: one construction.
        assert len(constructions) == 1

    def test_model_name_passed_through(self, monkeypatch):
        constructions = _install_fake_fastembed(monkeypatch)
        embeddings.embed_query("a")
        assert constructions == [embeddings.MODEL_NAME]


def test_embedding_dim_pinned_to_384():
    # Guards the DB ``vector(384)`` column contract: EMBEDDING_DIM must not drift.
    assert embeddings.EMBEDDING_DIM == 384
