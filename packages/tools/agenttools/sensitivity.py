"""How sensitive is what a model is about to read? Labels for tool results and for the user's words.

Levels follow the document classification already used by the knowledge base:
PUBLIC (FDA documents, openFDA, ClinicalTrials.gov), INTERNAL (ERP + QMS, internal SOPs),
CONFIDENTIAL (product-project documents marked confidential). Personal data in any text
(e-mail, phone, national ID, medical record number) is RESTRICTED regardless of its source.

Labels are deterministic and come from metadata plus a few patterns; they are what the gateway
routes on. They can be wrong (a confidential fact paraphrased in an internal document, a phone
number written in an unusual way) — the routing evaluation measures how often.
"""
from __future__ import annotations

import json
import re

PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED = 0, 1, 2, 3
NAMES = {PUBLIC: "public", INTERNAL: "internal", CONFIDENTIAL: "confidential", RESTRICTED: "restricted"}
CLASSIFICATION = {"public": PUBLIC, "internal": INTERNAL, "confidential": CONFIDENTIAL}

# Static level of each tool's output (the knowledge base is labelled per passage instead).
TOOL_LEVEL = {
    "list_complaints": INTERNAL, "get_capa": INTERNAL, "site_overview": INTERNAL,
    "sites_with_scanner_model": INTERNAL, "software_release": INTERNAL, "trace_part_lot": INTERNAL,
    "search_510k": PUBLIC, "device_recalls": PUBLIC, "search_clinical_trials": PUBLIC,
    "draft_capa": INTERNAL, "draft_ticket": INTERNAL, "draft_notification": INTERNAL,
}

PII_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)(?:\+?886[-\s]?|0)(?:9\d{2}[-\s]?\d{3}[-\s]?\d{3}|[2-8][-\s]?\d{3,4}[-\s]?\d{4})(?!\d)"),
    "national_id": re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?!\d)"),
    "mrn": re.compile(r"(?:病歷號|病歷號碼|MRN)[:：\s]*[A-Za-z0-9-]{4,}"),
}

# Words that only appear in confidential project material. A request that names them is treated as
# confidential even before any document is retrieved. Kept short on purpose: it is a list of
# project code names, not a classifier.
CONFIDENTIAL_TERMS = ("NoduleAssist 2.0", "NA2", "DP-NA2", "RM-NA2", "VP-NA2", "2.0 專案")


def pii_found(text: str) -> list[str]:
    return sorted(k for k, p in PII_PATTERNS.items() if p.search(text))


def label_text(text: str) -> tuple[int, list[str]]:
    """Level of free text written by a person (the user's request)."""
    reasons = [f"pii:{k}" for k in pii_found(text)]
    if reasons:
        return RESTRICTED, reasons
    hits = [t for t in CONFIDENTIAL_TERMS if t.lower() in text.lower()]
    if hits:
        return CONFIDENTIAL, [f"term:{t}" for t in hits]
    return INTERNAL, []   # anything a staff member types is at least internal


def label_result(tool: str, result) -> tuple[int, list[str]]:
    """Level of what a tool returned."""
    if not isinstance(result, dict) or "error" in result:
        return PUBLIC, []
    if tool == "search_knowledge_base":
        levels = [CLASSIFICATION.get(h.get("classification", "internal"), CONFIDENTIAL)
                  for h in result.get("untrusted", [])]
        level, reasons = (max(levels), [f"kb:{NAMES[max(levels)]}"]) if levels else (PUBLIC, [])
    else:
        level = TOOL_LEVEL.get(tool, CONFIDENTIAL)  # unknown tools: assume the worst
        reasons = [f"tool:{tool}"]
    pii = pii_found(json.dumps(result, ensure_ascii=False, default=str))
    if pii:
        return RESTRICTED, reasons + [f"pii:{k}" for k in pii]
    return level, reasons
