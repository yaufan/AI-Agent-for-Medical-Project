"""Text-to-SQL accuracy on the synthetic ERP + QMS: does the model's query return the gold rows?

19 manager questions (questions.jsonl): 8 from packages/erpqms/scenarios.sql, 11 written for the
dashboard. Each predicted query runs through the same checks as the UI (agenttools.text2sql) and
is compared with the gold query's result: same rows, ignoring row order, column order, column
names and extra columns. Queries the checks refuse count as wrong.

    # sanity check of the gold queries and the comparison (no model; CI runs this)
    python eval/text2sql/run_text2sql.py --model gold
    # a model behind an OpenAI-compatible endpoint
    python eval/text2sql/run_text2sql.py --model qwen3.8-27b-q8 --base-url http://127.0.0.1:8000/v1 --timeout 1800
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/tools", "packages/erpqms"):
    sys.path.insert(0, str(ROOT / p))

from agenttools import agent, text2sql  # noqa: E402
from erpqms import generate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="'gold' or a model name served at --base-url")
    ap.add_argument("--base-url")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--retries", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "results/m4")
    ap.add_argument("--fail-below", type=float, help="exit 1 if accuracy is below this (CI)")
    args = ap.parse_args()

    questions = [json.loads(line) for line in open(ROOT / "eval/text2sql/questions.jsonl", encoding="utf-8")]
    llm = None if args.model == "gold" else agent.ChatLLM(args.base_url, args.model, timeout=args.timeout,
                                                         retries=args.retries)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "erpqms.sqlite"
        generate.write_sqlite(generate.build(), db)
        con = text2sql.connect(db)
        for q in questions:
            gold = text2sql.run_sql(con, q["gold_sql"])
            row = {"id": q["id"], "question": q["question"]}
            try:
                if llm is None:
                    pred_sql, meta = q["gold_sql"], {"seconds": 0, "usage": {}}
                else:
                    meta = text2sql.ask(llm, q["question"])
                    pred_sql = meta["sql"]
                row.update(sql=pred_sql, seconds=meta["seconds"], usage=meta["usage"])
                pred = text2sql.run_sql(con, pred_sql)
                row.update(match=text2sql.results_match(gold, pred), rows=len(pred[1]), gold_rows=len(gold[1]))
            except text2sql.SQLRejected as e:
                row.update(match=False, rejected=str(e))
            except (httpx.HTTPError, KeyError, ValueError) as e:
                row.update(match=False, error=f"{type(e).__name__}: {e}"[:300])
            rows.append(row)
            print(f"{q['id']:24s} {'OK ' if row['match'] else 'NO '} {row.get('rejected') or row.get('error') or ''}",
                  flush=True)
    acc = sum(r["match"] for r in rows) / len(rows)
    summary = {"model": args.model, "questions": len(rows), "matched": sum(r["match"] for r in rows),
               "accuracy": round(acc, 3), "rejected": sum("rejected" in r for r in rows),
               "errors": sum("error" in r for r in rows),
               "seconds": round(sum(r.get("seconds", 0) for r in rows), 1), "rows": rows}
    if args.model != "gold":
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"text2sql-{args.model.replace(':', '-').replace('/', '-')}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"matched {summary['matched']}/{summary['questions']}")
    if args.fail_below is not None and acc < args.fail_below:
        sys.exit(f"accuracy {acc:.3f} below {args.fail_below}")


if __name__ == "__main__":
    main()
