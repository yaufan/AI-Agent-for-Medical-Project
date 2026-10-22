"""Everything the demo UI does except drawing it, so it can be tested without Chainlit.

One `Backend` per process: the synthetic ERP + QMS database (generated on first start), the
knowledge base, the tool registry and a draft store shared by all users. Each chat turn builds a
fresh `Session` from the signed-in user and runs either the fixed workflow (no model configured)
or the agent loop against an OpenAI-compatible server. Every tool call goes through the guard and
is recorded, so the UI can show what was called, with which arguments, and what came back.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/tools", "packages/rag", "packages/erpqms"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from agenttools import agent  # noqa: E402
from agenttools.core import Session  # noqa: E402
from agenttools.drafts import APPROVER_ROLES, ApprovalError, DraftStore  # noqa: E402
from agenttools.guard import Guard  # noqa: E402
from agenttools.tools import Context, build_registry  # noqa: E402
from agenttools.workflow import Workflow  # noqa: E402
from erpqms import generate  # noqa: E402
from rag.acl import GroupStore  # noqa: E402
from rag.chunking import chunk_corpus  # noqa: E402
from rag.documents import load_corpus  # noqa: E402
from rag.retriever import Retriever  # noqa: E402

KIND_LABEL = {"capa": "CAPA", "ticket": "服務工單", "notification": "客戶通知"}


class RecordingGuard(Guard):
    """The normal guard, plus a copy of every call and its result for display."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls: list[dict] = []

    def call(self, session, name, args):
        result = super().call(session, name, args)
        entry = session.trace[-1]
        self.calls.append({"tool": name, "args": args, "ok": entry.get("ok"), "kind": entry.get("kind"),
                           "error": entry.get("error"), "ms": entry.get("ms"),
                           "tainted_fields": entry.get("tainted_fields"), "result": result})
        return result


@dataclass
class Turn:
    answer: str
    calls: list[dict]
    sources: list[str]
    drafts: list[dict]
    seconds: float
    mode: str


class Backend:
    def __init__(self, data_dir: Path | None = None, llm_base_url: str | None = None, llm_model: str | None = None,
                 llm_api_key: str = "none", http_transport=None, include_public_pdfs: bool = True):
        data_dir = Path(data_dir or ROOT / "data/synthetic")
        db = data_dir / "erpqms" / "erpqms.sqlite"
        if not db.exists():
            db.parent.mkdir(parents=True, exist_ok=True)
            generate.write_sqlite(generate.build(), db)
        users = json.loads((ROOT / "eval/users.json").read_text(encoding="utf-8"))["users"]
        self.users = {u: v["role"] for u, v in users.items()}
        self.groups = GroupStore.from_json(ROOT / "eval/users.json")
        docs, self.corpus_stats = load_corpus(ROOT / "data/corpus", ROOT / "data/raw/public",
                                              include_public=include_public_pdfs)
        self.drafts = DraftStore(data_dir / "drafts.sqlite")
        self.ctx = Context(db, self.drafts, Retriever(chunk_corpus(docs, "structured")), http_transport=http_transport)
        self.registry = build_registry(self.ctx)
        self.llm_base_url, self.llm_model, self.llm_api_key = llm_base_url, llm_model, llm_api_key

    @classmethod
    def from_env(cls) -> "Backend":
        return cls(llm_base_url=os.environ.get("ASSISTANT_LLM_BASE_URL") or None,
                   llm_model=os.environ.get("ASSISTANT_LLM_MODEL") or None,
                   llm_api_key=os.environ.get("ASSISTANT_LLM_API_KEY", "none"))

    @property
    def mode(self) -> str:
        return f"模型 {self.llm_model}" if self.llm_base_url and self.llm_model else "固定流程（未設定模型）"

    def session(self, user: str, request: str = "") -> Session:
        return Session(user, self.groups.groups(user), role=self.users[user], request=request)

    def ask(self, user: str, request: str) -> Turn:
        session = self.session(user, request)
        guard = RecordingGuard(self.registry)
        before = {d["draft_id"] for d in self.drafts.pending()}
        if self.llm_base_url and self.llm_model:
            llm = agent.ChatLLM(self.llm_base_url, self.llm_model, api_key=self.llm_api_key, timeout=1800)
            out = agent.run(llm, self.registry, guard, session)
            sources = sources_from_calls(guard.calls)
        else:
            out = Workflow(guard).run(session)
            sources = out["sources"]
        created = [d for d in self.drafts.pending() if d["draft_id"] not in before and d["requested_by"] == user]
        return Turn(out["answer"] or "（模型沒有產生回答）", guard.calls, sources, created, out["seconds"], self.mode)

    def can_approve(self, user: str, kind: str) -> bool:
        return self.users.get(user) in APPROVER_ROLES.get(kind, set())

    def pending_for(self, user: str) -> list[dict]:
        return [d for d in self.drafts.pending() if self.can_approve(user, d["kind"])]

    def decide(self, user: str, draft_id: str, approve: bool, acknowledge: bool = False) -> tuple[bool, str]:
        try:
            d = self.drafts.decide(draft_id, approver=user, approver_role=self.users.get(user, ""), approve=approve,
                                   note="demo UI", acknowledge_third_party_text=acknowledge)
        except ApprovalError as e:
            return False, str(e)
        return True, f"{draft_id} 已{'核准' if d['status'] == 'approved' else '退回'}（{user}）"


def sources_from_calls(calls: list[dict]) -> list[str]:
    """Citations for the agent mode: what the successful read calls actually returned."""
    out: list[str] = []
    for c in calls:
        if not c["ok"]:
            continue
        r = c["result"]
        if c["tool"] == "search_knowledge_base":
            out += [f"{h['doc_id']} §{h['heading']}" for h in r.get("untrusted", [])]
        elif c["tool"] == "list_complaints":
            out += [x["complaint_id"] for x in r.get("complaints", [])]
        elif c["tool"] == "get_capa":
            out.append(r["capa"]["capa_id"])
        elif c["kind"] == "read":
            out.append(f"{c['tool']}({', '.join(f'{k}={v}' for k, v in c['args'].items())})")
    return list(dict.fromkeys(out))


def describe_draft(d: dict) -> str:
    p = {k: v for k, v in d["payload"].items() if k != "_provenance" and v not in (None, "", [])}
    lines = [f"**{d['draft_id']}**　{KIND_LABEL.get(d['kind'], d['kind'])}　申請人 {d['requested_by']}　{d['created_at']}"]
    lines += [f"- {k}：{', '.join(v) if isinstance(v, list) else v}" for k, v in p.items()]
    tainted = (d["payload"].get("_provenance") or {}).get("copied_from_third_party_text")
    if tainted:
        lines.append(f"\n⚠️ 欄位 {', '.join(tainted)} 的文字和客戶或外部資料相同，不是申請人自己寫的。核准前請確認內容。")
    return "\n".join(lines)


def is_tainted(d: dict) -> bool:
    return bool((d["payload"].get("_provenance") or {}).get("copied_from_third_party_text"))


def short_json(value, limit: int = 3000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + f"\n…（共 {len(text)} 字，已截斷）"
