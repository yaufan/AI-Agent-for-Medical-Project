"""Evaluation gate for CI: compare a fresh retrieval run with the committed baseline.

    python eval/run_retrieval.py --out /tmp/m1
    python eval/check_gate.py --baseline results/m1 --candidate /tmp/m1

Fails when
- any access-controlled mode (pre, post) returns a chunk the user may not read, or
- answerable Recall@10 or MRR drops by more than --tolerance against the baseline for the same config.
The gate guards against regressions; it does not encode a target score.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--tolerance", type=float, default=0.02)
    args = ap.parse_args()
    failures = []
    for cand_path in sorted(args.candidate.glob("*.json")):
        cand = json.loads(cand_path.read_text())
        for acl in ("pre", "post"):
            leaks = cand["acl"].get(acl, {}).get("leaks", {}).get("leaked_chunks", 0)
            if leaks:
                failures.append(f"{cand_path.stem}/{acl}: {leaks} leaked chunks")
        if not cand["revocation"]["effective_on_next_query"]:
            failures.append(f"{cand_path.stem}: revocation not effective on next query")
        base_path = args.baseline / cand_path.name
        if not base_path.exists():
            print(f"NEW  {cand_path.stem} (no baseline)")
            continue
        base = json.loads(base_path.read_text())
        for metric in ("recall@10", "mrr"):
            b, c = base["acl"]["pre"]["answerable"][metric], cand["acl"]["pre"]["answerable"][metric]
            status = "FAIL" if c < b - args.tolerance else "OK  "
            print(f"{status} {cand_path.stem:24s} {metric:9s} baseline {b:.3f} -> {c:.3f}")
            if status == "FAIL":
                failures.append(f"{cand_path.stem}: {metric} {b:.3f} -> {c:.3f}")
    if failures:
        print("\n".join(["", "Gate failed:"] + failures))
        sys.exit(1)
    print("Gate passed.")


if __name__ == "__main__":
    main()
