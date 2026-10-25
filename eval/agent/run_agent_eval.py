"""Scenario tasks for the agent: does it call the right tools and reach the verifiable answer?

Each task in tasks.jsonl has a check: strings the answer must contain (any spelling in a group),
strings it must not contain (access control), tools it must call, or a draft it must create.
Needs a real model behind an OpenAI-compatible endpoint, for example Ollama on the local machine:

    python eval/agent/run_agent_eval.py --model qwen3:8b --base-url http://localhost:11434/v1
    # the fixed workflow (rules instead of a model) on the same tasks, as the baseline
    python eval/agent/run_agent_eval.py --model workflow
    # slow or shared server
    python eval/agent/run_agent_eval.py --model M --base-url URL --timeout 1800 --retries 12 --ids A01 A02

Saves after every task and skips tasks already in the output file; failed model calls are recorded
as errors and retried on the next run.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/tools", "packages/rag", "packages/erpqms"):
    sys.path.insert(0, str(ROOT / p))

from agenttools import agent, backends  # noqa: E402
from agenttools.core import Session  # noqa: E402
from agenttools.drafts import DraftStore  # noqa: E402
from agenttools.guard import Guard  # noqa: E402
from agenttools.tools import Context, build_registry  # noqa: E402
from agenttools.workflow import Workflow  # noqa: E402
from erpqms import generate  # noqa: E402
from rag.acl import GroupStore  # noqa: E402
from rag.chunking import chunk_corpus  # noqa: E402
from rag.documents import load_markdown  # noqa: E402
from rag.retriever import Retriever  # noqa: E402


def check(task: dict, out: dict, drafts: list[dict]) -> dict:
    c, answer = task["check"], out["answer"]
    called = {e["tool"] for e in out["trace"] if e.get("ok")}
    result = {"called": sorted(called)}
    ok = True
    if "include" in c:
        missing = [g for g in c["include"] if not any(s in answer for s in g)]
        result["missing"] = missing
        ok &= not missing
    if "exclude" in c:
        leaked = [s for s in c["exclude"] if s in answer]
        result["leaked"] = leaked
        ok &= not leaked
    if c.get("must_call"):
        absent = [t for t in c["must_call"] if t not in called]
        result["tools_not_called"] = absent
        ok &= not absent
    if "draft" in c:
        want = c["draft"]
        match = [d for d in drafts if d["kind"] == want["kind"] and
                 set(want.get("related_complaints", [])) <= set(d["payload"].get("related_complaints", []))]
        result["draft_ok"] = bool(match)
        ok &= bool(match)
    result["pass"] = bool(ok)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="a model served at --base-url, or 'workflow'")
    ap.add_argument("--base-url")
    ap.add_argument("--provider", choices=["openai", "anthropic"], default="openai",
                    help="openai: OpenAI-compatible server at --base-url; anthropic: Claude via the Anthropic SDK")
    ap.add_argument("--out", type=Path, default=ROOT / "results/m2")
    ap.add_argument("--ids", nargs="+", help="only these task ids")
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds per model request")
    ap.add_argument("--retries", type=int, default=0, help="retries when the model server is down (5 min apart)")
    args = ap.parse_args()
    tasks = [json.loads(line) for line in open(ROOT / "eval/agent/tasks.jsonl", encoding="utf-8")]
    if args.ids:
        tasks = [t for t in tasks if t["id"] in args.ids]
    order = {t["id"]: i for i, t in enumerate(tasks)}
    store = GroupStore.from_json(ROOT / "eval/users.json")
    retriever = Retriever(chunk_corpus([load_markdown(p) for p in sorted((ROOT / "data/corpus").glob("*/*.md"))]))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"agent-{args.model.replace(':', '-').replace('/', '-')}.json"
    rows = json.loads(path.read_text())["rows"] if path.exists() else []

    def save():
        rows.sort(key=lambda r: order.get(r["id"], 999))
        ok = [r for r in rows if "error" not in r]
        summary = {"model": args.model, "tasks": len(rows), "errors": len(rows) - len(ok),
                   "passed": sum(r["pass"] for r in ok),
                   "tool_calls": sum(len(r["tool_calls"]) for r in ok),
                   "rejected_calls": sum(1 for r in ok for c in r["tool_calls"] if not c[1]),
                   "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in ok),
                   "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in ok),
                   "seconds": round(sum(r["seconds"] for r in ok), 1), "rows": rows}
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    done = {r["id"] for r in rows if "error" not in r}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "erpqms.sqlite"
        generate.write_sqlite(generate.build(), db)
        for task in tasks:
            if task["id"] in done:
                continue
            ctx = Context(db, DraftStore(), retriever)
            reg = build_registry(ctx)
            session = Session(task["user"], store.groups(task["user"]), request=task["request"])
            try:
                if args.model == "workflow":
                    out = Workflow(Guard(reg)).run(session)
                else:
                    llm = backends.make_llm(args.provider, args.model, args.base_url, args.timeout, args.retries,
                                            session=session)
                    out = agent.run(llm, reg, Guard(reg), session)
                    if hasattr(llm, "decisions"):
                        out["routes"] = llm.decisions
                res = check(task, out, ctx.drafts.pending())
                row = {"id": task["id"], **res, "steps": out["steps"], "stopped": out["stopped"],
                       "seconds": out["seconds"], "usage": out["usage"], "answer": out["answer"],
                       **({"routes": out["routes"]} if "routes" in out else {})}
                status = "PASS" if res["pass"] else "FAIL"
            except backends.ERRORS as e:
                row = {"id": task["id"], "error": f"{type(e).__name__}: {e}"[:500]}
                status = "ERROR"
            row["tool_calls"] = [(e["tool"], e.get("ok"), e.get("error")) for e in session.trace]
            rows[:] = [r for r in rows if r["id"] != task["id"]] + [row]
            save()
            print(f"{task['id']} {status} {row.get('seconds', '-')}s calls={len(row['tool_calls'])}", flush=True)
    summary = save()
    print(f"passed {summary['passed']}/{summary['tasks']} (errors {summary['errors']})")

if __name__ == "__main__":
    main()
