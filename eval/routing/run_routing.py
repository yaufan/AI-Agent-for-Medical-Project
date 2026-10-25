"""Gateway routing: does anything sensitive reach the cloud model, and how much stays local for nothing?

No model is called. Each case in cases.jsonl scripts the tool calls an agent would make; the two
backends are recorders that return the next scripted step. The gateway (agenttools.gateway)
decides per call where it goes, using the same labels as production. What each backend received
is then checked against an oracle that does not use those labels:

- confidential: any line of a confidential project document, or one of the code facts below;
- personal data: the values each case marks as sensitive (typed by the user or planted in data).

leak         = a cloud-bound call whose content the oracle marks sensitive
over_blocked = a local-bound call whose content the oracle finds nothing sensitive in

Two policies are compared: cloud allowed up to internal data (default) and public data only.

    python eval/routing/run_routing.py            # writes results/m3/routing.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/tools", "packages/rag", "packages/erpqms"):
    sys.path.insert(0, str(ROOT / p))

from agenttools import agent, sensitivity  # noqa: E402
from agenttools.agent import LLMReply  # noqa: E402
from agenttools.core import Session  # noqa: E402
from agenttools.drafts import DraftStore  # noqa: E402
from agenttools.gateway import RoutedLLM  # noqa: E402
from agenttools.guard import Guard  # noqa: E402
from agenttools.tools import Context, build_registry  # noqa: E402
from erpqms import generate  # noqa: E402
from rag.acl import GroupStore  # noqa: E402
from rag.chunking import chunk_corpus  # noqa: E402
from rag.documents import Document, Section, load_markdown  # noqa: E402
from rag.retriever import Retriever  # noqa: E402

# Facts from the confidential 2.0 documents, in the forms a person would type them.
FACTS = ["2027-01-29", "2026-10-30", "2026-12-18", "6,800 例", "端到端 3D 偵測網路", "12 位放射科醫師",
         "600 例，來自 4 家"]
POLICIES = {"cloud<=internal": sensitivity.INTERNAL, "cloud<=public": sensitivity.PUBLIC}


def confidential_lines(docs) -> list[str]:
    out = []
    for d in docs:
        if d.classification != "confidential":
            continue
        for line in d.text.splitlines():
            line = line.strip(" |>#-")
            if len(line) >= 12 and "機密" not in line and not set(line) <= set("|- "):
                out.append(line)
    return out


class Recorder:
    """A backend that records what it receives and returns the next scripted reply."""

    def __init__(self, name, script, log):
        self.name, self.script, self.log = name, script, log

    def chat(self, messages, tools):
        sent = "\n".join(str(m.get("content", "")) for m in messages if m["role"] != "system")
        self.log.append((self.name, sent))
        return next(self.script)


def script(case):
    for i, (tool, args) in enumerate(case["calls"]):
        yield LLMReply("", [{"id": f"c{i}", "name": tool, "arguments": json.dumps(args, ensure_ascii=False)}], 0.0)
    yield LLMReply("（回答）", [], 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "results/m3")
    args = ap.parse_args()

    cases = [json.loads(line) for line in open(ROOT / "eval/routing/cases.jsonl", encoding="utf-8")]
    store = GroupStore.from_json(ROOT / "eval/users.json")
    base_docs = [load_markdown(p) for p in sorted((ROOT / "data/corpus").glob("*/*.md"))]
    conf = confidential_lines(base_docs)
    public_internal = "\n".join(d.text for d in base_docs if d.classification != "confidential")
    clash = [f for f in FACTS if f in public_internal]
    assert not clash, f"oracle facts also appear in non-confidential documents: {clash}"

    def fda(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"k_number": "K250001", "decision_date": "2025-01-01",
                                                      "applicant": "Example Co.", "device_name": "Lung CAD",
                                                      "product_code": "OEB", "studies": []}],
                                         "studies": []})

    report = {"cases": len(cases), "policies": {}}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clean = tmp / "clean.sqlite"
        generate.write_sqlite(generate.build(), clean)
        for policy, max_level in POLICIES.items():
            rows = []
            for case in cases:
                plant = case.get("plant", {})
                db = tmp / f"{case['id']}.sqlite"
                with sqlite3.connect(clean) as src, sqlite3.connect(db) as dst:
                    src.backup(dst)
                    if "complaint" in plant:
                        dst.execute("UPDATE complaints SET description = description || ' ' || ? WHERE complaint_id ="
                                    " (SELECT complaint_id FROM complaints WHERE site_id='H-B' ORDER BY received_at"
                                    " DESC LIMIT 1)", (plant["complaint"],))
                docs = list(base_docs)
                if "kb" in plant:
                    docs.append(Document("WIKI-NEWS", "內部公告", "internal", "internal", "wiki", "zh",
                                         [Section("內部公告", plant["kb"])]))
                ctx = Context(db, DraftStore(), Retriever(chunk_corpus(docs, "structured")),
                              http_transport=httpx.MockTransport(fda))
                reg = build_registry(ctx)
                session = Session(case["user"], store.groups(case["user"]), request=case["request"])
                log: list[tuple[str, str]] = []
                steps = script(case)
                llm = RoutedLLM(Recorder("local", steps, log), Recorder("cloud", steps, log), session,
                                cloud_max_level=max_level)
                agent.run(llm, reg, Guard(reg), session)

                secrets = conf + FACTS + case.get("sensitive", [])
                calls = []
                for (backend, sent), d in zip(log, llm.decisions):
                    hits = sorted({s for s in secrets if s in sent})
                    calls.append({"backend": backend, "level": d["level"], "reasons": d["reasons"],
                                  "oracle_sensitive": bool(hits), "oracle_hits": [h[:40] for h in hits][:3]})
                leaks = sum(c["backend"] == "cloud" and c["oracle_sensitive"] for c in calls)
                over = sum(c["backend"] == "local" and not c["oracle_sensitive"] for c in calls)
                rows.append({"id": case["id"], "category": case["cat"], "calls": calls, "leaked_calls": leaks,
                             "over_blocked_calls": over, "cloud_calls": sum(c["backend"] == "cloud" for c in calls),
                             "local_calls": sum(c["backend"] == "local" for c in calls)})
            by_cat = defaultdict(Counter)
            for r in rows:
                by_cat[r["category"]].update(cases=1, leaked_cases=int(r["leaked_calls"] > 0),
                                             leaked_calls=r["leaked_calls"], over_blocked_calls=r["over_blocked_calls"],
                                             cloud_calls=r["cloud_calls"], local_calls=r["local_calls"])
            total = Counter()
            for c in by_cat.values():
                total.update(c)
            report["policies"][policy] = {"total": dict(total), "by_category": {k: dict(v) for k, v in by_cat.items()},
                                          "rows": rows}
            print(f"{policy:16s} {dict(total)}")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "routing.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
