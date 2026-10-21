"""Run the question bank through a retriever and summarise the results by question type.

Answerable types (fact, table, cross_lingual, code) are scored with Recall@k, MRR and nDCG@10.
`unauthorized` questions are scored by leakage: any retrieved chunk from a group the user does
not belong to counts as a leak. `unanswerable` questions have no gold; their top-1 scores are
kept so a refusal threshold can be chosen later.
"""
from __future__ import annotations

import copy
import time
from collections import defaultdict

import numpy as np

from .acl import GroupStore
from .metrics import evidence_sets, norm, percentile, score_ranking
from .retriever import Retriever

ANSWERABLE = ("fact", "table", "cross_lingual", "code")


def run(retriever: Retriever, questions: list[dict], store: GroupStore, method: str, acl: str, k: int = 10,
        candidates: int = 50, rerank: bool = False) -> list[dict]:
    normed = [norm(c.text) for c in retriever.chunks]
    rows = []
    for q in questions:
        groups = store.groups(q["user"])
        hits, timings = retriever.search(q["question"], groups, k=k, method=method, acl=acl,
                                         candidates=candidates, rerank=rerank)
        ranking = [h.index for h in hits]
        ev = evidence_sets(retriever.chunks, q["evidence"], normed)
        leaked = [h.chunk.chunk_id for h in hits if h.chunk.group not in groups]
        row = {"id": q["id"], "type": q["type"], "user": q["user"], "returned": len(hits),
               "ranking": [h.chunk.chunk_id for h in hits], "leaked": leaked,
               "answer_leaked": bool(ev and any(set(ranking) & s for s in ev) and q["type"] == "unauthorized"),
               "top1_score": hits[0].score if hits else None, "timings": timings}
        if q["type"] in ANSWERABLE:
            row.update(score_ranking(ranking, ev))
        rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict:
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    out: dict = {"by_type": {}}
    metric_keys = ["recall@1", "recall@5", "recall@10", "mrr", "ndcg@10"]
    answerable = [r for r in rows if r["type"] in ANSWERABLE]
    for t, rs in sorted(by_type.items()):
        entry = {"n": len(rs), "mean_returned": round(float(np.mean([r["returned"] for r in rs])), 2)}
        if t in ANSWERABLE:
            entry.update({m: round(float(np.mean([r[m] for r in rs])), 3) for m in metric_keys})
        entry["questions_with_leak"] = sum(bool(r["leaked"]) for r in rs)
        entry["leaked_chunks"] = sum(len(r["leaked"]) for r in rs)
        if t == "unauthorized":
            entry["answer_chunk_leaked"] = sum(r["answer_leaked"] for r in rs)
        out["by_type"][t] = entry
    out["answerable"] = {"n": len(answerable), **{m: round(float(np.mean([r[m] for r in answerable])), 3)
                                                   for m in metric_keys}}
    out["leaks"] = {"questions_with_leak": sum(bool(r["leaked"]) for r in rows),
                    "leaked_chunks": sum(len(r["leaked"]) for r in rows)}
    stages = sorted({s for r in rows for s in r["timings"]})
    out["latency_ms"] = {s: {"p50": round(percentile([r["timings"][s] for r in rows if s in r["timings"]], 50), 3),
                             "p95": round(percentile([r["timings"][s] for r in rows if s in r["timings"]], 95), 3)}
                         for s in stages}
    top1 = {t: [r["top1_score"] for r in rows if r["type"] == t and r["top1_score"] is not None]
            for t in ("unanswerable",) + ANSWERABLE}
    out["top1_score_median"] = {t: round(float(np.median(v)), 4) if v else None for t, v in top1.items()}
    return out


def revocation_check(retriever: Retriever, questions: list[dict], store: GroupStore, user: str, group: str,
                     method: str = "bm25") -> dict:
    """Revoke a membership and confirm the very next query no longer returns that group's chunks."""
    store = copy.deepcopy(store)
    targets = [q for q in questions if any(e for e in q["evidence"])
               and q["user"] == user and q["type"] in ANSWERABLE]
    before = run(retriever, targets, store, method, "pre")
    t0 = time.perf_counter()
    store.revoke(user, group)
    after = run(retriever, targets, store, method, "pre")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    group_of = {c.chunk_id: c.group for c in retriever.chunks}
    count = lambda rows: sum(group_of[cid] == group for r in rows for cid in r["ranking"])  # noqa: E731
    return {"user": user, "revoked_group": group, "questions": len(targets),
            "chunks_from_group_before": count(before), "chunks_from_group_after": count(after),
            "effective_on_next_query": count(after) == 0,
            "revoke_plus_rerun_ms": round(elapsed_ms, 2), "reindex_needed": False}
