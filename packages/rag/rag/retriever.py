"""Hybrid retrieval with access control applied inside the search, not after it.

Three access-control modes exist so their difference can be measured:
- `pre`  : forbidden chunks are removed before ranking (the intended design).
- `post` : rank everything, take the top k, then drop forbidden chunks (a common shortcut: no
           leaks, but users silently get fewer results).
- `none` : no filtering (baseline that shows what would leak).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .acl import allowed_mask
from .bm25 import BM25, tokenize
from .chunking import Chunk
from .dense import DenseIndex, Reranker


@dataclass
class Hit:
    index: int
    chunk: Chunk
    score: float


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank of d), rank starting at 1."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, 1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


def _rank(scores: np.ndarray, mask: np.ndarray | None, limit: int, positive_only: bool) -> list[int]:
    s = scores.astype(np.float64).copy()
    if mask is not None:
        s[~mask] = -np.inf
    order = np.argsort(-s, kind="stable")[:limit]
    return [int(i) for i in order if np.isfinite(s[i]) and (s[i] > 0 or not positive_only)]


class Retriever:
    def __init__(self, chunks: list[Chunk], dense: DenseIndex | None = None, reranker: Reranker | None = None):
        self.chunks = chunks
        self.chunk_groups = np.array([c.group for c in chunks])
        self.bm25 = BM25([tokenize(c.text) for c in chunks])
        self.dense = dense
        self.reranker = reranker

    def search(self, query: str, groups: set[str] | None, k: int = 10, method: str = "bm25", acl: str = "pre",
               candidates: int = 50, rerank: bool = False) -> tuple[list[Hit], dict[str, float]]:
        timings: dict[str, float] = {}
        t_all = time.perf_counter()

        t = time.perf_counter()
        mask = allowed_mask(self.chunk_groups, groups) if groups is not None and acl != "none" else None
        timings["acl_ms"] = (time.perf_counter() - t) * 1000
        pre_mask = mask if acl == "pre" else None

        rankings, scores_by_method = [], {}
        if method in ("bm25", "hybrid"):
            t = time.perf_counter()
            s = self.bm25.scores(tokenize(query))
            rankings.append(_rank(s, pre_mask, candidates, positive_only=True))
            scores_by_method["bm25"] = s
            timings["bm25_ms"] = (time.perf_counter() - t) * 1000
        if method in ("dense", "hybrid"):
            if self.dense is None:
                raise ValueError("dense index not configured")
            t = time.perf_counter()
            s = self.dense.scores(query)
            rankings.append(_rank(s, pre_mask, candidates, positive_only=False))
            scores_by_method["dense"] = s
            timings["dense_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        if len(rankings) == 1:
            only = next(iter(scores_by_method.values()))
            fused = [(i, float(only[i])) for i in rankings[0]]
        else:
            fused = rrf(rankings)[:candidates]
        timings["fusion_ms"] = (time.perf_counter() - t) * 1000

        if rerank:
            if self.reranker is None:
                raise ValueError("reranker not configured")
            t = time.perf_counter()
            ids = [i for i, _ in fused]
            new = self.reranker.scores(query, [self.chunks[i].text for i in ids])
            fused = sorted(zip(ids, new), key=lambda x: (-x[1], x[0]))
            timings["rerank_ms"] = (time.perf_counter() - t) * 1000

        top = fused[:k]
        if acl == "post" and mask is not None:
            top = [(i, s) for i, s in top if mask[i]]
        timings["total_ms"] = (time.perf_counter() - t_all) * 1000
        return [Hit(i, self.chunks[i], s) for i, s in top], timings
