"""Write actions become drafts; only a person can approve them.

The agent's write tools call `DraftStore.create`, which records a pending draft and returns its id.
Nothing leaves the system at that point. `approve` and `reject` are not tools: they are called by
the approval UI or CLI on behalf of a named person whose role may approve that kind of draft, and
every decision is appended to the audit log (append-only; there is no update or delete API).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

APPROVER_ROLES = {"capa": {"品保主管"}, "ticket": {"品保主管", "服務主管"}, "notification": {"品保主管"}}

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, requested_by TEXT NOT NULL,
  created_at TEXT NOT NULL, status TEXT NOT NULL, decided_by TEXT, decided_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApprovalError(Exception):
    pass


class DraftStore:
    def __init__(self, path: Path | str = ":memory:"):
        self.con = sqlite3.connect(str(path))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def log(self, actor: str, action: str, detail: dict) -> None:
        self.con.execute("INSERT INTO audit (ts, actor, action, detail) VALUES (?,?,?,?)",
                         (_now(), actor, action, json.dumps(detail, ensure_ascii=False)))
        self.con.commit()

    def create(self, kind: str, payload: dict, requested_by: str) -> str:
        n = self.con.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] + 1
        draft_id = f"DRAFT-{n:05d}"
        self.con.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?,?)",
                         (draft_id, kind, json.dumps(payload, ensure_ascii=False), requested_by, _now(),
                          "pending", None, None, None))
        self.log(requested_by, "draft_created", {"draft_id": draft_id, "kind": kind})
        return draft_id

    def get(self, draft_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        return dict(row) | {"payload": json.loads(row["payload"])} if row else None

    def pending(self) -> list[dict]:
        return [self.get(r[0]) for r in self.con.execute("SELECT draft_id FROM drafts WHERE status='pending'")]

    def decide(self, draft_id: str, approver: str, approver_role: str, approve: bool, note: str = "",
               acknowledge_third_party_text: bool = False) -> dict:
        d = self.get(draft_id)
        if d is None:
            raise ApprovalError(f"no such draft: {draft_id}")
        if d["status"] != "pending":
            raise ApprovalError(f"{draft_id} is already {d['status']}")
        if approver_role not in APPROVER_ROLES.get(d["kind"], set()):
            raise ApprovalError(f"role {approver_role} may not decide {d['kind']} drafts")
        if approver == d["requested_by"]:
            raise ApprovalError("the requester cannot approve their own draft")
        if approve and (d["payload"].get("_provenance") or {}).get("copied_from_third_party_text") \
                and not acknowledge_third_party_text:
            raise ApprovalError("this draft contains text copied from third-party data; review it and approve "
                                "with acknowledge_third_party_text=True")
        status = "approved" if approve else "rejected"
        self.con.execute("UPDATE drafts SET status=?, decided_by=?, decided_at=?, note=? WHERE draft_id=?",
                         (status, approver, _now(), note, draft_id))
        self.log(approver, f"draft_{status}", {"draft_id": draft_id, "note": note})
        return self.get(draft_id)

    def audit(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM audit ORDER BY seq")]
