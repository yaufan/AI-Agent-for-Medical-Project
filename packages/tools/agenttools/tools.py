"""The tools Company M's assistant can call.

Read tools: fixed, parameterised queries on the ERP + QMS database (opened read-only), knowledge-base
search bound to the session's access groups, and public regulatory APIs (openFDA, ClinicalTrials.gov).
Write tools: create drafts only (see drafts.py).

Results that contain text written by people outside the company (complaint descriptions, document
passages, API records) are returned under an `untrusted` key so the host can mark them as data.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx

from .core import CAPA_ID, DATE, LOT_NO, SITE_ID, TEXT, Registry, Session, ToolError
from .drafts import DraftStore

CATEGORIES = ["missed_nodule", "false_positive_increase", "qc_reject", "slow_inference", "hardware_failure",
              "ui_usability"]
OPENFDA = "https://api.fda.gov"
CTGOV = "https://clinicaltrials.gov/api/v2"


def _rows(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


class Context:
    """Everything the tools need, created once per host process."""

    def __init__(self, erpqms_path: Path | str, drafts: DraftStore, retriever=None,
                 http_transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        # read-only at the driver level: a write through this connection fails even if a query tried
        self.db = sqlite3.connect(f"file:{Path(erpqms_path)}?mode=ro", uri=True, check_same_thread=False)
        self.drafts = drafts
        self.retriever = retriever
        self.http = httpx.Client(timeout=timeout, transport=http_transport,
                                 headers={"User-Agent": "company-m-assistant-demo"})
        self.cache: dict[str, Any] = {}

    def get_json(self, url: str, params: dict) -> dict:
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if key not in self.cache:
            r = self.http.get(url, params=params)
            if r.status_code == 404:  # openFDA answers 404 for "no matches"
                self.cache[key] = {"results": []}
            else:
                if r.status_code >= 400:
                    raise ToolError("upstream_error", f"{url} answered {r.status_code}")
                self.cache[key] = r.json()
        return self.cache[key]


def build_registry(ctx: Context) -> Registry:
    reg = Registry()

    # ---------------- ERP / QMS (read) ----------------
    @reg.register("list_complaints", "List complaints, newest first. Filters are optional. Descriptions are "
                  "customer-written text.", "read",
                  {"type": "object", "properties": {
                      "site_id": SITE_ID, "category": {"type": "string", "enum": CATEGORIES},
                      "scanner_model": {"type": "string", "pattern": r"^[A-C]-\d{2,3}$", "maxLength": 6},
                      "since": DATE, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}})
    def list_complaints(session: Session, site_id=None, category=None, scanner_model=None, since=None, limit=20):
        sql = ["SELECT c.complaint_id, c.site_id, c.received_at, c.category, c.severity, ct.model AS scanner_model,",
               "c.serial_no, c.software_version, c.suspected_component, c.status, c.capa_id, c.description",
               "FROM complaints c LEFT JOIN ct_scanners ct ON ct.scanner_id = c.scanner_id WHERE 1=1"]
        params: list = []
        for cond, val in [("c.site_id = ?", site_id), ("c.category = ?", category), ("ct.model = ?", scanner_model),
                          ("c.received_at >= ?", since)]:
            if val is not None:
                sql.append("AND " + cond)
                params.append(val)
        sql.append("ORDER BY c.received_at DESC LIMIT ?")
        params.append(limit)
        rows = _rows(ctx.db.execute(" ".join(sql), params))
        texts = [{"complaint_id": r["complaint_id"], "description": r.pop("description")} for r in rows]
        return {"complaints": rows, "untrusted": texts}

    @reg.register("get_capa", "Read one CAPA record and the complaints linked to it.", "read",
                  {"type": "object", "properties": {"capa_id": CAPA_ID}, "required": ["capa_id"]})
    def get_capa(session: Session, capa_id):
        capa = _rows(ctx.db.execute("SELECT * FROM capas WHERE capa_id = ?", (capa_id,)))
        if not capa:
            raise ToolError("not_found", f"no such CAPA: {capa_id}")
        linked = _rows(ctx.db.execute("SELECT complaint_id, site_id, received_at, category FROM complaints "
                                      "WHERE capa_id = ? ORDER BY received_at", (capa_id,)))
        return {"capa": capa[0], "linked_complaints": linked}

    @reg.register("site_overview", "One site: its CT scanners (with default slice thickness), appliances with "
                  "current software version, and the last six months of usage.", "read",
                  {"type": "object", "properties": {"site_id": SITE_ID}, "required": ["site_id"]})
    def site_overview(session: Session, site_id):
        site = _rows(ctx.db.execute("SELECT * FROM sites WHERE site_id = ?", (site_id,)))
        if not site:
            raise ToolError("not_found", f"no such site: {site_id}")
        scanners = _rows(ctx.db.execute("SELECT scanner_id, vendor, model, default_slice_thickness_mm, installed_at "
                                        "FROM ct_scanners WHERE site_id = ? ORDER BY installed_at", (site_id,)))
        appliances = _rows(ctx.db.execute(
            "SELECT a.serial_no, a.sku, a.install_date, d.version FROM appliances a JOIN deployments d "
            "ON d.serial_no = a.serial_no WHERE a.site_id = ? AND d.deployed_at = "
            "(SELECT MAX(d2.deployed_at) FROM deployments d2 WHERE d2.serial_no = a.serial_no) ORDER BY a.serial_no",
            (site_id,)))
        usage = _rows(ctx.db.execute("SELECT month, studies_processed, qc_reject_rate, marks_per_study "
                                     "FROM monthly_usage WHERE site_id = ? ORDER BY month DESC LIMIT 6", (site_id,)))
        return {"site": site[0], "ct_scanners": scanners, "appliances": appliances, "recent_usage": usage}

    @reg.register("sites_with_scanner_model", "Which sites have a given CT scanner model, and when it was installed.",
                  "read", {"type": "object", "properties": {
                      "model": {"type": "string", "pattern": r"^[A-C]-\d{2,3}$", "maxLength": 6}}, "required": ["model"]})
    def sites_with_scanner_model(session: Session, model):
        return {"sites": _rows(ctx.db.execute(
            "SELECT s.site_id, s.name, ct.scanner_id, ct.installed_at, ct.default_slice_thickness_mm "
            "FROM ct_scanners ct JOIN sites s ON s.site_id = ct.site_id WHERE ct.model = ? ORDER BY ct.installed_at",
            (model,)))}

    @reg.register("software_release", "Input specification and status of a NoduleAssist software version.", "read",
                  {"type": "object", "properties": {"version": {"type": "string", "pattern": r"^\d\.\d$", "maxLength": 3}},
                   "required": ["version"]})
    def software_release(session: Session, version):
        r = _rows(ctx.db.execute("SELECT * FROM software_releases WHERE version = ?", (version,)))
        if not r:
            raise ToolError("not_found", f"no such version: {version}")
        return r[0]

    @reg.register("trace_part_lot", "Every appliance built with a part lot, its site, and SSD failures so far.",
                  "read", {"type": "object", "properties": {"lot_no": LOT_NO}, "required": ["lot_no"]})
    def trace_part_lot(session: Session, lot_no):
        return {"appliances": _rows(ctx.db.execute(
            "SELECT a.serial_no, a.site_id, a.build_date, a.status, "
            "(SELECT COUNT(*) FROM complaints c WHERE c.serial_no = a.serial_no AND c.suspected_component = 'SSD') "
            "AS ssd_failures FROM appliance_parts ap JOIN appliances a ON a.serial_no = ap.serial_no "
            "WHERE ap.lot_no = ? ORDER BY a.serial_no", (lot_no,)))}

    # ---------------- knowledge base (read, access-controlled) ----------------
    @reg.register("search_knowledge_base", "Search company documents and public regulatory documents the current "
                  "user may read. Returns passages with their source.", "read",
                  {"type": "object", "properties": {"query": {"type": "string", "maxLength": 500},
                                                    "k": {"type": "integer", "minimum": 1, "maximum": 10}},
                   "required": ["query"]})
    def search_knowledge_base(session: Session, query, k=5):
        if ctx.retriever is None:
            raise ToolError("unavailable", "knowledge base is not configured")
        hits, _ = ctx.retriever.search(query, session.groups, k=k, acl="pre")  # groups come from the session
        return {"untrusted": [{"chunk_id": h.chunk.chunk_id, "doc_id": h.chunk.doc_id, "heading": h.chunk.heading,
                               "page": h.chunk.page, "text": h.chunk.text[:1500]} for h in hits]}

    # ---------------- public regulatory APIs (read) ----------------
    @reg.register("search_510k", "Search FDA 510(k) clearances by product code (e.g. OEB) or device name.", "read",
                  {"type": "object", "properties": {
                      "product_code": {"type": "string", "pattern": r"^[A-Z]{3}$", "maxLength": 3},
                      "device_name": {"type": "string", "pattern": r"^[A-Za-z0-9 .\-]{2,60}$", "maxLength": 60},
                      "limit": {"type": "integer", "minimum": 1, "maximum": 20}}})
    def search_510k(session: Session, product_code=None, device_name=None, limit=10):
        if not product_code and not device_name:
            raise ToolError("invalid_argument", "give product_code or device_name")
        q = f"product_code:{product_code}" if product_code else f'device_name:"{device_name}"'
        data = ctx.get_json(f"{OPENFDA}/device/510k.json", {"search": q, "limit": limit, "sort": "decision_date:desc"})
        keep = ("k_number", "decision_date", "applicant", "device_name", "product_code", "decision_description")
        return {"untrusted": [{k: r.get(k) for k in keep} for r in data.get("results", [])]}

    @reg.register("device_recalls", "FDA device recalls for a product code.", "read",
                  {"type": "object", "properties": {"product_code": {"type": "string", "pattern": r"^[A-Z]{3}$",
                                                                     "maxLength": 3},
                                                    "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                   "required": ["product_code"]})
    def device_recalls(session: Session, product_code, limit=10):
        data = ctx.get_json(f"{OPENFDA}/device/recall.json", {"search": f"product_code:{product_code}", "limit": limit})
        keep = ("res_event_number", "event_date_initiated", "recalling_firm", "product_description", "reason_for_recall")
        return {"untrusted": [{k: r.get(k) for k in keep} for r in data.get("results", [])]}

    @reg.register("search_clinical_trials", "Search ClinicalTrials.gov studies by free-text term.", "read",
                  {"type": "object", "properties": {"term": {"type": "string", "pattern": r"^[A-Za-z0-9 .,\-]{2,100}$",
                                                             "maxLength": 100},
                                                    "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                   "required": ["term"]})
    def search_clinical_trials(session: Session, term, limit=10):
        data = ctx.get_json(f"{CTGOV}/studies", {"query.term": term, "pageSize": limit,
                                                 "fields": "NCTId,BriefTitle,OverallStatus,EnrollmentCount,StudyType"})
        out = []
        for s in data.get("studies", []):
            p = s.get("protocolSection", {})
            out.append({"nct_id": p.get("identificationModule", {}).get("nctId"),
                        "title": p.get("identificationModule", {}).get("briefTitle"),
                        "status": p.get("statusModule", {}).get("overallStatus"),
                        "enrollment": p.get("designModule", {}).get("enrollmentInfo", {}).get("count"),
                        "study_type": p.get("designModule", {}).get("studyType")})
        return {"untrusted": out}

    # ---------------- write (drafts only) ----------------
    @reg.register("draft_capa", "Draft a CAPA for a quality manager to review. Creates a pending draft only.", "write",
                  {"type": "object", "properties": {
                      "title": {"type": "string", "maxLength": 120}, "description": TEXT,
                      "related_complaints": {"type": "array", "maxItems": 20,
                                             "items": {"type": "string", "pattern": r"^CMP-\d{4}-\d{4}$", "maxLength": 13}},
                      "related_capa": CAPA_ID},
                   "required": ["title", "description"]})
    def draft_capa(session: Session, title, description, related_complaints=(), related_capa=None, _provenance=None):
        known = {r[0] for r in ctx.db.execute(
            f"SELECT complaint_id FROM complaints WHERE complaint_id IN ({','.join('?' * len(related_complaints))})",
            list(related_complaints))} if related_complaints else set()
        missing = sorted(set(related_complaints) - known)
        if missing:
            raise ToolError("not_found", f"unknown complaint id(s): {', '.join(missing)}")
        draft_id = ctx.drafts.create("capa", {"title": title, "description": description,
                                              "related_complaints": list(related_complaints),
                                              "related_capa": related_capa, "_provenance": _provenance},
                                     session.user)
        return {"draft_id": draft_id, "status": "pending approval by a quality manager"}

    @reg.register("draft_ticket", "Draft a service ticket for one site. Creates a pending draft only.", "write",
                  {"type": "object", "properties": {"site_id": SITE_ID, "summary": {"type": "string", "maxLength": 120},
                                                    "details": TEXT}, "required": ["site_id", "summary"]})
    def draft_ticket(session: Session, site_id, summary, details="", _provenance=None):
        if not ctx.db.execute("SELECT 1 FROM sites WHERE site_id = ?", (site_id,)).fetchone():
            raise ToolError("not_found", f"no such site: {site_id}")
        draft_id = ctx.drafts.create("ticket", {"site_id": site_id, "summary": summary, "details": details,
                                                "_provenance": _provenance}, session.user)
        return {"draft_id": draft_id, "status": "pending approval"}

    @reg.register("draft_notification", "Draft a notice to customer sites (at most 5). Creates a pending draft only; "
                  "nothing is sent until a quality manager approves it.", "write",
                  {"type": "object", "properties": {"site_ids": {"type": "array", "maxItems": 5, "items": SITE_ID},
                                                    "subject": {"type": "string", "maxLength": 120}, "body": TEXT},
                   "required": ["site_ids", "subject", "body"]})
    def draft_notification(session: Session, site_ids, subject, body, _provenance=None):
        if not site_ids:
            raise ToolError("invalid_argument", "site_ids must not be empty")
        known = {r[0] for r in ctx.db.execute(
            f"SELECT site_id FROM sites WHERE site_id IN ({','.join('?' * len(site_ids))})", site_ids)}
        if set(site_ids) - known:
            raise ToolError("not_found", f"unknown site(s): {', '.join(sorted(set(site_ids) - known))}")
        draft_id = ctx.drafts.create("notification", {"site_ids": site_ids, "subject": subject, "body": body,
                                                      "_provenance": _provenance}, session.user)
        return {"draft_id": draft_id, "status": "pending approval by a quality manager"}

    return reg
