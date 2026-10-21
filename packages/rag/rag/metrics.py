"""Retrieval metrics against evidence quotes rather than fixed chunk ids.

A question's gold answer is a list of evidence items: (doc_id, quote). A chunk is relevant to an
item when it comes from that document and contains the quote (whitespace and case normalised).
Because relevance is defined by text, the same question bank works for any chunking strategy.

- Recall@k : share of evidence items with at least one relevant chunk in the top k.
- MRR      : 1 / rank of the first relevant chunk (0 if none in the list).
- nDCG@k   : binary gain for relevant chunks, ideal = all relevant chunks ranked first.
- coverage : share of evidence items that exist inside a single chunk at all. A quote cut in
             two by the chunker can never be retrieved, so coverage bounds every other number.
"""
from __future__ import annotations

import math
import re

import numpy as np

from .chunking import Chunk


def norm(text: str) -> str:
    """Lowercase, drop Markdown emphasis, collapse whitespace."""
    return re.sub(r"\s+", " ", text.replace("**", "")).strip().lower()


def evidence_sets(chunks: list[Chunk], evidence: list[dict], normed: list[str] | None = None) -> list[set[int]]:
    normed = normed or [norm(c.text) for c in chunks]
    out = []
    for ev in evidence:
        q = norm(ev["quote"])
        out.append({i for i, c in enumerate(chunks) if c.doc_id == ev["doc_id"] and q in normed[i]})
    return out


def score_ranking(ranking: list[int], ev_sets: list[set[int]], ks=(1, 5, 10)) -> dict[str, float]:
    union = set().union(*ev_sets) if ev_sets else set()
    out = {}
    for k in ks:
        top = set(ranking[:k])
        out[f"recall@{k}"] = sum(bool(s & top) for s in ev_sets) / len(ev_sets)
    first = next((r for r, i in enumerate(ranking, 1) if i in union), None)
    out["mrr"] = 1.0 / first if first else 0.0
    k = max(ks)
    dcg = sum(1 / math.log2(r + 1) for r, i in enumerate(ranking[:k], 1) if i in union)
    idcg = sum(1 / math.log2(r + 1) for r in range(1, min(len(union), k) + 1))
    out[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0
    return out


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(values, p)) if values else float("nan")
