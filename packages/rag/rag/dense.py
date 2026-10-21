"""Dense retrieval and reranking behind small interfaces, so the models can live anywhere.

- `OpenAIEmbedder` calls any OpenAI-compatible /embeddings endpoint (Ollama, vLLM, TEI, a cloud API).
  bge-m3 is the planned model: multilingual, so a Chinese question can find an English passage.
- `HTTPReranker` calls a /rerank endpoint in the shape vLLM and TEI expose (query + documents ->
  relevance scores); bge-reranker-v2-m3 is the planned model.
- `HashingEmbedder` exists only for tests. It has no notion of meaning.

The cloud development environment cannot download models, so real numbers come from the local machine.
"""
from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from .bm25 import tokenize


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class Reranker(Protocol):
    name: str

    def scores(self, query: str, documents: list[str]) -> list[float]: ...


def _normalise(m: np.ndarray) -> np.ndarray:
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)


class HashingEmbedder:
    """Deterministic bag-of-tokens hashed into a fixed number of dimensions. Test double only."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim))
        for i, t in enumerate(texts):
            for tok in tokenize(t):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                out[i, h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        return _normalise(out)


class OpenAIEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str = "none", batch: int = 32, timeout: float = 120.0,
                 transport=None):
        import httpx

        self.name, self.batch = model, batch
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                 headers={"Authorization": f"Bearer {api_key}"})

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for i in range(0, len(texts), self.batch):
            r = self.http.post("/embeddings", json={"model": self.name, "input": texts[i:i + self.batch]})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            vecs.extend(d["embedding"] for d in data)
        return _normalise(np.asarray(vecs, dtype=np.float64))


class HTTPReranker:
    def __init__(self, base_url: str, model: str, api_key: str = "none", timeout: float = 120.0, transport=None):
        import httpx

        self.name = model
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                 headers={"Authorization": f"Bearer {api_key}"})

    def scores(self, query: str, documents: list[str]) -> list[float]:
        r = self.http.post("/rerank", json={"model": self.name, "query": query, "documents": documents})
        r.raise_for_status()
        out = [0.0] * len(documents)
        for item in r.json()["results"]:
            out[item["index"]] = float(item["relevance_score"])
        return out


class DenseIndex:
    def __init__(self, embedder: Embedder, texts: list[str], vectors: np.ndarray | None = None):
        self.embedder = embedder
        self.vectors = vectors if vectors is not None else embedder.embed(texts)

    def scores(self, query: str) -> np.ndarray:
        q = self.embedder.embed([query])[0]
        return self.vectors @ q
