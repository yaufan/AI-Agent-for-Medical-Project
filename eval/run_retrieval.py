"""M1 retrieval experiment: chunking strategy x retrieval method x access-control mode.

BM25 runs anywhere. Dense retrieval and reranking need model endpoints, which the cloud
development environment cannot reach; run those on the local machine, for example with Ollama:

    ollama pull bge-m3
    python eval/run_retrieval.py --methods bm25 dense hybrid \
        --embed-url http://localhost:11434/v1 --embed-model bge-m3

    # reranker served by vLLM or TEI at /rerank:
    python eval/run_retrieval.py --methods hybrid --rerank-url http://localhost:8001 --rerank-model BAAI/bge-reranker-v2-m3

`--corpus internal` uses only the synthetic Markdown documents and the questions answerable from
them (plus all unauthorized and unanswerable questions). CI always runs it, because it does not
depend on downloading anything from FDA.

Writes results/m1/<chunking>-<method>[-rerank].json (summaries) and results/m1/runs/*.jsonl
(per-question rankings as chunk ids only — no document text, so nothing from the corpus is copied
into the results).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/rag"))
from rag import evaluate  # noqa: E402
from rag.acl import GroupStore  # noqa: E402
from rag.chunking import chunk_corpus  # noqa: E402
from rag.dense import DenseIndex, HTTPReranker, OpenAIEmbedder  # noqa: E402
from rag.documents import load_corpus  # noqa: E402
from rag.retriever import Retriever  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunking", nargs="+", default=["structured", "fixed"])
    ap.add_argument("--methods", nargs="+", default=["bm25"])
    ap.add_argument("--acl", nargs="+", default=["pre", "post", "none"])
    ap.add_argument("--embed-url"), ap.add_argument("--embed-model")
    ap.add_argument("--rerank-url"), ap.add_argument("--rerank-model")
    ap.add_argument("--corpus", choices=["all", "internal"], default="all")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    args.out = args.out or ROOT / ("results/m1" if args.corpus == "all" else "results/m1/internal")

    docs, stats = load_corpus(ROOT / "data/corpus", ROOT / "data/raw/public", include_public=args.corpus == "all")
    if stats["pdf_missing"]:
        sys.exit(f"missing PDFs {stats['pdf_missing']}: run scripts/fetch_public_corpus.py first")
    questions = [json.loads(line) for line in open(ROOT / "eval/questions.jsonl", encoding="utf-8")]
    if args.corpus == "internal":
        internal = {d.doc_id for d in docs}
        questions = [q for q in questions
                     if all(e["doc_id"] in internal for e in q["evidence"]) or q["type"] == "unanswerable"]
    store = GroupStore.from_json(ROOT / "eval/users.json")
    (args.out / "runs").mkdir(parents=True, exist_ok=True)

    embedder = OpenAIEmbedder(args.embed_url, args.embed_model) if args.embed_url else None
    reranker = HTTPReranker(args.rerank_url, args.rerank_model) if args.rerank_url else None

    for strategy in args.chunking:
        chunks = chunk_corpus(docs, strategy)
        dense = None
        if embedder and any(m in ("dense", "hybrid") for m in args.methods):
            t = time.perf_counter()
            dense = DenseIndex(embedder, [c.text for c in chunks])
            print(f"[{strategy}] embedded {len(chunks)} chunks in {time.perf_counter() - t:.1f}s")
        retriever = Retriever(chunks, dense=dense, reranker=reranker)
        for method in args.methods:
            for rerank in ([False, True] if reranker else [False]):
                name = f"{strategy}-{method}" + ("-rerank" if rerank else "")
                result = {"config": {"chunking": strategy, "method": method, "rerank": rerank, "k": 10,
                                     "candidates": 50, "chunks": len(chunks),
                                     "embed_model": args.embed_model if method != "bm25" else None,
                                     "rerank_model": args.rerank_model if rerank else None},
                          "corpus": stats, "acl": {}}
                for acl in args.acl:
                    rows = evaluate.run(retriever, questions, store, method, acl, rerank=rerank)
                    result["acl"][acl] = evaluate.summarise(rows)
                    with open(args.out / "runs" / f"{name}-{acl}.jsonl", "w", encoding="utf-8") as f:
                        for r in rows:
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
                result["revocation"] = evaluate.revocation_check(retriever, questions, store, "ra_huang",
                                                                 "proj-b", method)
                (args.out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
                a = result["acl"]["pre"]["answerable"]
                print(f"{name:28s} R@1 {a['recall@1']:.3f}  R@5 {a['recall@5']:.3f}  R@10 {a['recall@10']:.3f}  "
                      f"MRR {a['mrr']:.3f}  leaks(none) {result['acl'].get('none', {}).get('leaks')}")


if __name__ == "__main__":
    main()
