"""Scenario tasks for the agent: does it call the right tools and reach the verifiable answer?

Each task in tasks.jsonl has a check: strings the answer must contain (any spelling in a group),
strings it must not contain (access control), tools it must call, or a draft it must create.
Needs a real model behind an OpenAI-compatible endpoint, for example Ollama on the local machine:

    python eval/agent/run_agent_eval.py --model qwen3:8b --base-url http://localhost:11434/v1
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/tools", "packages/rag", "packages/erpqms"):
    sys.path.insert(0, str(ROOT / p))

from agenttools import agent  # noqa: E402
from agenttools.core import Session  # noqa: E402
from agenttools.drafts import DraftStore  # noqa: E402
from agenttools.guard import Guard  # noqa: E402
from agenttools.tools import Context, build_registry  # noqa: E402
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
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "results/m2")
    args = ap.parse_args()
    tasks = [json.loads(line) for line in open(ROOT / "eval/agent/tasks.jsonl", encoding="utf-8")]
    store = GroupStore.from_json(ROOT / "eval/users.json")
    retriever = Retriever(chunk_corpus([load_markdown(p) for p in sorted((ROOT / "data/corpus").glob("*/*.md"))]))
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "erpqms.sqlite"
        generate.write_sqlite(generate.build(), db)
        for task in tasks:
            ctx = Context(db, DraftStore(), retriever)
            reg = build_registry(ctx)
            session = Session(task["user"], store.groups(task["user"]), request=task["request"])
            out = agent.run(agent.ChatLLM(args.base_url, args.model), reg, Guard(reg), session)
            res = check(task, out, ctx.drafts.pending())
            rows.append({"id": task["id"], **res, "steps": out["steps"], "stopped": out["stopped"],
                         "seconds": out["seconds"], "usage": out["usage"], "answer": out["answer"],
                         "tool_calls": [(e["tool"], e.get("ok"), e.get("error")) for e in out["trace"]]})
            print(f"{task['id']} {'PASS' if res['pass'] else 'FAIL'} {out['seconds']}s calls={len(out['trace'])}")
    summary = {"model": args.model, "tasks": len(rows), "passed": sum(r["pass"] for r in rows),
               "tool_calls": sum(len(r["tool_calls"]) for r in rows),
               "rejected_calls": sum(1 for r in rows for c in r["tool_calls"] if not c[1]),
               "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in rows),
               "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in rows),
               "seconds": round(sum(r["seconds"] for r in rows), 1), "rows": rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"agent-{args.model.replace(':', '-').replace('/', '-')}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"passed {summary['passed']}/{summary['tasks']}")


if __name__ == "__main__":
    main()
