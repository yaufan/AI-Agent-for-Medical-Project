"""A fixed workflow: the same tools and guard as the agent, but routing by rules instead of a model.

Used for two things: as the baseline the agent is compared against (same tasks, same checks), and
as the demo UI's backend when no model server is configured. It reads identifiers from the user's
request (site, scanner model, CAPA id, lot number, product code), calls a fixed sequence of tools
through the guard, and writes the answer from the tool results. Free text returned by tools is
quoted, never interpreted, so instructions planted in data cannot change what it does.

What it cannot do is anything outside its routes: a question it does not recognise falls back to a
knowledge-base search and returns the top passages as they are.
"""
from __future__ import annotations

import re
import time

from .core import Session
from .guard import WRITE_INTENT, Guard

AS_OF = "2026-09-30"  # the synthetic data's "today" (erpqms.generate.AS_OF)

SITE = re.compile(r"醫院([A-L])")
SCANNER = re.compile(r"\b([A-C]-\d{2,3})\b")
CAPA = re.compile(r"CAPA-\d{4}-\d{3}")
LOT = re.compile(r"[A-Z]{3}-[A-Z0-9]{2}-L\d{4}")
VERSION = re.compile(r"(?<![\d.])(\d\.\d)(?![\d.])")
PRODUCT_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")


def _site_name(site_id: str) -> str:
    return "醫院" + site_id[-1]


def _wants(request: str, tool: str) -> bool:
    return any(w in request.lower() for w in WRITE_INTENT[tool])


class Workflow:
    def __init__(self, guard: Guard):
        self.guard = guard

    def run(self, session: Session) -> dict:
        t0 = time.time()
        req = session.request
        self.sources: list[str] = []
        site = SITE.search(req)
        site_id = f"H-{site.group(1)}" if site else None
        scanner = SCANNER.search(req)
        if CAPA.search(req):
            answer = self.capa(session, CAPA.search(req).group(0))
        elif LOT.search(req):
            answer = self.lot(session, LOT.search(req).group(0))
        elif scanner and site_id and ("客訴" in req or _wants(req, "draft_capa")):
            answer = self.site_complaints(session, site_id, scanner.group(1))
        elif scanner and not site_id:
            answer = self.scanner_sites(session, scanner.group(1))
        elif site_id:
            answer = self.site(session, site_id, req)
        elif ("510" in req or "召回" in req or "recall" in req.lower()) and PRODUCT_CODE.search(req):
            answer = self.fda(session, PRODUCT_CODE.search(req).group(1), recalls="召回" in req or "recall" in req.lower())
        else:
            answer = self.knowledge(session, req)
        return {"answer": answer, "steps": len(session.trace), "trace": session.trace, "sources": self.sources,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "seconds": round(time.time() - t0, 2),
                "stopped": "answer"}

    def call(self, session: Session, name: str, **args) -> dict:
        return self.guard.call(session, name, args)

    # ---------------- routes ----------------
    def capa(self, session: Session, capa_id: str) -> str:
        r = self.call(session, "get_capa", capa_id=capa_id)
        if "error" in r:
            return f"查不到 {capa_id}：{r['error']['message']}"
        c = r["capa"]
        overdue = c["status"] != "closed" and c["due_date"] < AS_OF
        linked = "、".join(f"{x['complaint_id']}（{_site_name(x['site_id'])}）" for x in r["linked_complaints"]) or "無"
        self.sources.append(capa_id)
        return (f"{capa_id}「{c['title']}」狀態 {c['status']}，到期日 {c['due_date']}"
                f"{f'，以資料日期 {AS_OF} 計已逾期' if overdue else '，尚未逾期'}。\n關聯客訴：{linked}")

    def lot(self, session: Session, lot_no: str) -> str:
        r = self.call(session, "trace_part_lot", lot_no=lot_no)
        rows = r.get("appliances", [])
        if not rows:
            return f"查不到使用批號 {lot_no} 的主機。"
        failed = [a for a in rows if a["ssd_failures"]]
        ok = [a for a in rows if not a["ssd_failures"]]
        fmt = lambda xs: "、".join(f"{a['serial_no']}（{_site_name(a['site_id'])}）" for a in xs) or "無"
        self.sources.append(f"ERP：批號 {lot_no}")
        return (f"批號 {lot_no} 共裝在 {len(rows)} 台主機。\n已有 SSD 故障紀錄：{fmt(failed)}\n"
                f"尚未故障：{fmt(ok)}")

    def scanner_sites(self, session: Session, model: str) -> str:
        rows = self.call(session, "sites_with_scanner_model", model=model).get("sites", [])
        if not rows:
            return f"沒有站點使用 {model}。"
        self.sources.append(f"ERP：CT 機型 {model}")
        return f"使用 {model} 的站點：" + "、".join(
            f"{r['name']}（{r['site_id']}，{r['installed_at']} 安裝，預設切片 {r['default_slice_thickness_mm']} mm）"
            for r in rows)

    def site_complaints(self, session: Session, site_id: str, model: str) -> str:
        rows = self.call(session, "list_complaints", site_id=site_id, scanner_model=model, limit=50).get("complaints", [])
        if not rows:
            return f"{_site_name(site_id)} 沒有和 {model} 相關的客訴。"
        self.sources += [r["complaint_id"] for r in rows]
        unlinked = [r["complaint_id"] for r in rows if not r["capa_id"]]
        lines = [f"- {r['complaint_id']}（{r['received_at']}，{r['category']}，"
                 f"{'CAPA ' + r['capa_id'] if r['capa_id'] else '未連到 CAPA'}）" for r in rows]
        answer = f"{_site_name(site_id)} 和 {model} 相關的客訴共 {len(rows)} 筆：\n" + "\n".join(lines)
        if _wants(session.request, "draft_capa") and unlinked:
            d = self.call(session, "draft_capa", title=f"{_site_name(site_id)} {model} 相關客訴",
                          description=f"{_site_name(site_id)} 使用 {model} 後的客訴，尚未連到 CAPA：{'、'.join(unlinked)}。"
                                      "請品保主管確認是否併入既有 CAPA 或另開。",
                          related_complaints=unlinked)
            answer += (f"\n\n已起草 CAPA {d['draft_id']}，關聯 {'、'.join(unlinked)}，等待品保主管核准。"
                       if "draft_id" in d else f"\n\n無法起草 CAPA：{d['error']['message']}")
        return answer

    def site(self, session: Session, site_id: str, req: str) -> str:
        r = self.call(session, "site_overview", site_id=site_id)
        if "error" in r:
            return f"查不到{_site_name(site_id)}：{r['error']['message']}"
        self.sources.append(f"ERP：{site_id}")
        cts = "；".join(f"{s['vendor']} {s['model']}（預設切片 {s['default_slice_thickness_mm']} mm，{s['installed_at']} 安裝）"
                       for s in r["ct_scanners"])
        apps = "；".join(f"{a['serial_no']} 版本 {a['version']}" for a in r["appliances"])
        answer = f"{r['site']['name']}（{site_id}）\nCT：{cts}\n推論主機：{apps}"
        v = VERSION.search(req)
        if v:
            rel = self.call(session, "software_release", version=v.group(1))
            if "error" not in rel:
                self.sources.append(f"ERP：軟體版本 {v.group(1)}")
                spec = {k: val for k, val in rel.items() if k not in ("version",)}
                answer += f"\n{v.group(1)} 版規格：" + "，".join(f"{k}={val}" for k, val in spec.items())
        return answer

    def fda(self, session: Session, code: str, recalls: bool) -> str:
        name = "device_recalls" if recalls else "search_510k"
        r = self.call(session, name, product_code=code, limit=10)
        if "error" in r:
            return f"openFDA 查詢失敗：{r['error']['message']}"
        rows = r["untrusted"]
        self.sources.append(f"openFDA {name}（{code}）")
        if recalls:
            return f"{code} 的回收紀錄 {len(rows)} 筆：\n" + "\n".join(
                f"- {x['res_event_number']} {x['event_date_initiated']} {x['recalling_firm']}" for x in rows)
        return f"{code} 的 510(k) 最近 {len(rows)} 筆：\n" + "\n".join(
            f"- {x['k_number']} {x['decision_date']} {x['applicant']}：{x['device_name']}" for x in rows)

    def knowledge(self, session: Session, req: str) -> str:
        r = self.call(session, "search_knowledge_base", query=req, k=3)
        if "error" in r or not r["untrusted"]:
            return "知識庫裡找不到你有權限閱讀的相關內容。"
        hits = r["untrusted"]
        self.sources += [f"{h['doc_id']} §{h['heading']}" for h in hits]
        return "知識庫中最相關的段落（原文摘錄，未經改寫）：\n\n" + "\n\n".join(
            f"[{i}] {h['doc_id']}「{h['heading']}」\n{h['text'][:600]}" for i, h in enumerate(hits, 1))
