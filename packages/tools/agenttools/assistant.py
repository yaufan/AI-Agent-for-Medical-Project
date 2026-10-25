"""The assistant behind the demo UI and the API service: one turn, its tool calls, drafts, approvals.

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

# repo layout (also kept inside the service image): data/corpus, eval/users.json, packages/*
ROOT = Path(os.environ.get("ASSISTANT_ROOT") or Path(__file__).resolve().parents[3])
for p in ("packages/rag", "packages/erpqms"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from . import agent, text2sql  # noqa: E402
from .core import Session  # noqa: E402
from .drafts import APPROVER_ROLES, ApprovalError, DraftStore  # noqa: E402
from .guard import Guard  # noqa: E402
from .tools import Context, build_registry  # noqa: E402
from .workflow import Workflow  # noqa: E402
from erpqms import generate  # noqa: E402
from rag.acl import GroupStore  # noqa: E402
from rag.chunking import chunk_corpus  # noqa: E402
from rag.documents import load_corpus  # noqa: E402
from rag.retriever import Retriever  # noqa: E402

KIND_LABEL = {"capa": "CAPA", "ticket": "服務工單", "notification": "客戶通知"}

# Who may query the ERP + QMS with free-form questions (Text-to-SQL) and see the dashboard.
DASHBOARD_ROLES = {"營運主管"}

# Fixed dashboard panels: (title, chart, sql). Same read-only path as Text-to-SQL.
PANELS = [
    ("各站點每月 QC 拒收率（2026）", "line",
     "SELECT month, site_id, qc_reject_rate FROM monthly_usage WHERE month >= '2026-01' ORDER BY month, site_id"),
    ("未結案客訴：各類別件數", "bar",
     "SELECT category, COUNT(*) AS n FROM complaints WHERE status <> 'closed' GROUP BY category ORDER BY n DESC"),
    ("各軟體版本的主機數（目前版本）", "bar",
     "SELECT dep.version, COUNT(*) AS appliances FROM appliances a JOIN deployments dep ON dep.serial_no = a.serial_no "
     "WHERE dep.deployed_at = (SELECT MAX(d2.deployed_at) FROM deployments d2 WHERE d2.serial_no = a.serial_no) "
     "GROUP BY dep.version ORDER BY dep.version"),
    ("逾期未結案的 CAPA", "table",
     f"SELECT capa_id, title, due_date, status, owner_role FROM capas WHERE status <> 'closed' "
     f"AND due_date < '{text2sql.AS_OF}' ORDER BY due_date"),
    ("停產零件：各站點服役中主機數", "bar",
     "SELECT a.site_id, COUNT(*) AS appliances FROM parts p JOIN appliance_parts ap ON ap.part_no = p.part_no "
     "JOIN appliances a ON a.serial_no = ap.serial_no WHERE p.lifecycle_status = 'eol_announced' "
     "AND a.status = 'in_service' GROUP BY a.site_id ORDER BY a.site_id"),
    ("2026 年底前到期的授權", "table",
     f"SELECT license_id, site_id, end_date, annual_fee_twd FROM licenses WHERE end_date > '{text2sql.AS_OF}' "
     "AND end_date <= '2026-12-31' ORDER BY end_date"),
]


@dataclass
class Table:
    title: str
    sql: str
    columns: list[str]
    rows: list[tuple]
    chart: str = "table"      # table / bar / line
    error: str = ""
    seconds: float = 0.0
    usage: dict | None = None


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
        self.sql = text2sql.connect(db)
        self.llm_base_url, self.llm_model, self.llm_api_key = llm_base_url, llm_model, llm_api_key

    @classmethod
    def from_env(cls) -> "Backend":
        return cls(data_dir=os.environ.get("ASSISTANT_DATA_DIR") or None,
                   llm_base_url=os.environ.get("ASSISTANT_LLM_BASE_URL") or None,
                   llm_model=os.environ.get("ASSISTANT_LLM_MODEL") or None,
                   llm_api_key=os.environ.get("ASSISTANT_LLM_API_KEY", "none"),
                   include_public_pdfs=os.environ.get("ASSISTANT_PUBLIC_PDFS", "1") != "0")

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

    def can_query(self, user: str) -> bool:
        return self.users.get(user) in DASHBOARD_ROLES

    def dashboard(self, user: str) -> list[Table]:
        if not self.can_query(user):
            raise PermissionError("dashboard is for operations managers")
        out = []
        for title, chart, sql in PANELS:
            cols, rows = text2sql.run_sql(self.sql, sql)
            out.append(Table(title, sql, cols, rows, chart))
        return out

    def ask_sql(self, user: str, question: str) -> Table:
        """Text-to-SQL. The model sees the schema and the question only; rows are shown, never sent back."""
        if not self.can_query(user):
            raise PermissionError("free-form database questions are for operations managers")
        if not (self.llm_base_url and self.llm_model):
            return Table(question, "", [], [], error="自由提問要先設定模型（ASSISTANT_LLM_BASE_URL、ASSISTANT_LLM_MODEL）；"
                                                     "沒有模型時請用「營運總覽」看固定報表。")
        llm = agent.ChatLLM(self.llm_base_url, self.llm_model, api_key=self.llm_api_key, timeout=1800)
        meta = text2sql.ask(llm, question)
        try:
            cols, rows = text2sql.run_sql(self.sql, meta["sql"])
        except text2sql.SQLRejected as e:
            return Table(question, meta["sql"], [], [], error=f"查詢被拒絕：{e}", seconds=meta["seconds"],
                         usage=meta["usage"])
        return Table(question, meta["sql"], cols, rows, guess_chart(cols, rows), seconds=meta["seconds"],
                     usage=meta["usage"])

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


def guess_chart(columns: list[str], rows: list[tuple]) -> str:
    """A chart only when the shape is obvious: one label column and one number (bar), or a month axis."""
    if not rows or len(rows) > 60:
        return "table"
    numeric = [i for i in range(len(columns)) if all(isinstance(r[i], (int, float)) for r in rows)]
    if "month" in columns and numeric:
        return "line"
    if len(columns) == 2 and numeric == [1]:
        return "bar"
    return "table"


def markdown_table(columns: list[str], rows: list[tuple], limit: int = 30) -> str:
    if not columns:
        return ""
    head = "| " + " | ".join(columns) + " |\n|" + "---|" * len(columns) + "\n"
    body = "\n".join("| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:limit])
    more = f"\n\n（共 {len(rows)} 列，只顯示前 {limit} 列）" if len(rows) > limit else ""
    return head + body + more


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
