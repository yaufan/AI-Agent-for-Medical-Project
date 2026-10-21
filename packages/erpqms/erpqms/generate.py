"""Generate the synthetic ERP + QMS database for Company M.

Everything here is invented. Hospitals, CT vendors, suppliers and parts use neutral
names (醫院A, CT廠牌A, 供應商甲, GPU G1) so nothing can be mistaken for a real
organisation. The data is deterministic: the same seed always gives the same rows.

Background noise is random; three storylines are planted on purpose so that the
agent scenarios have a verifiable answer (see ../README.md and ../scenarios.sql):

  S1  醫院B installs a new CT model (C-320) whose default reconstruction is 3.0 mm,
      above the 2.5 mm input spec. QC rejects and CAD marks jump; CAPA-2026-007 is
      open and overdue. 醫院F installs the same model later and starts to complain,
      but nobody has linked it to the CAPA yet.
  S2  SSD lot SSD-S1-L2508 fails early. Four appliances with that lot have complained;
      two more carry the same lot and have not failed yet.
  S3  GPU G1 is end-of-life; an engineering change request to move to G2 is a draft.

Usage:
    python -m erpqms.generate --out data/synthetic/erpqms
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
AS_OF = date(2026, 9, 30)
SEED = 20261021

SITES = [  # site_id, name, region, type, go-live
    ("H-A", "醫院A", "北區", "醫學中心", "2024-01-15"),
    ("H-B", "醫院B", "北區", "醫學中心", "2024-02-01"),
    ("H-C", "醫院C", "中區", "醫學中心", "2024-03-11"),
    ("H-D", "醫院D", "南區", "醫學中心", "2024-05-06"),
    ("H-E", "醫院E", "北區", "區域醫院", "2024-07-01"),
    ("H-F", "醫院F", "中區", "區域醫院", "2024-10-14"),
    ("H-G", "醫院G", "南區", "區域醫院", "2025-01-06"),
    ("H-H", "醫院H", "東區", "區域醫院", "2025-04-07"),
    ("H-I", "醫院I", "北區", "地區醫院", "2025-08-18"),
    ("H-J", "醫院J", "中區", "地區醫院", "2025-09-15"),
    ("H-K", "醫院K", "南區", "地區醫院", "2025-10-20"),
    ("H-L", "醫院L", "東區", "地區醫院", "2026-03-02"),
]
EXTRA_APPLIANCES = [  # capacity expansions: site_id, install date
    ("H-A", "2025-09-01"), ("H-C", "2025-10-06"), ("H-D", "2025-11-03"),
    ("H-B", "2026-04-13"), ("H-A", "2026-05-11"),
]
SITE_SCALE = {"醫學中心": 1.0, "區域醫院": 0.45, "地區醫院": 0.18}

SCANNER_MODELS = [  # vendor, model, default reconstruction thickness (mm)
    ("CT廠牌A", "A-64", 1.25), ("CT廠牌A", "A-128", 1.0),
    ("CT廠牌B", "B-80", 1.25), ("CT廠牌B", "B-256", 1.0), ("CT廠牌C", "C-64", 2.0),
]
NEW_SCANNER = ("CT廠牌C", "C-320", 3.0)
NEW_SCANNER_INSTALLS = [("H-B", "2026-06-01"), ("H-F", "2026-08-05")]

RELEASES = [
    ("1.0", "2024-01-08", "m1.0", 2.5, 60, "cleared", "首版上市"),
    ("1.1", "2024-09-16", "m1.1", 2.5, 60, "cleared", "降低血管分岔處誤報"),
    ("1.2", "2025-06-23", "m1.2", 2.5, 60, "cleared", "推論加速、加入輸入 QC 拒收原因"),
    ("2.0", "2026-09-01", "m2.0", 2.5, 60, "under_review", "新模型架構，變更評估與送審中，尚未部署"),
]
UPGRADES = {"1.1": ("2024-10-07", "2024-12-16"), "1.2": ("2025-07-14", "2025-09-29")}
LAGGING_SITES = {"H-E", "H-G"}  # never upgraded past 1.1

SUPPLIERS = [("S-1", "供應商甲"), ("S-2", "供應商乙"), ("S-3", "供應商丙")]
PARTS = [  # part_no, category, description, supplier, lifecycle, eol notice, last-time buy
    ("GPU-G1", "GPU", "GPU G1, 24 GB", "S-1", "eol_announced", "2026-08-20", "2027-02-26"),
    ("GPU-G2", "GPU", "GPU G2, 48 GB", "S-1", "active", None, None),
    ("SSD-S1", "SSD", "NVMe SSD S1, 1 TB", "S-2", "active", None, None),
    ("SSD-S2", "SSD", "NVMe SSD S2, 2 TB", "S-3", "active", None, None),
    ("CPU-C1", "CPU", "Server CPU C1, 16 cores", "S-3", "active", None, None),
    ("RAM-R1", "RAM", "DDR5 RDIMM 32 GB", "S-3", "active", None, None),
    ("PSU-P1", "PSU", "Power supply 1200 W", "S-2", "active", None, None),
]
SKUS = {
    "NA-100": ("推論主機 NA-100（GPU G1、SSD S1）", {"GPU-G1": 1, "SSD-S1": 1, "CPU-C1": 1, "RAM-R1": 2, "PSU-P1": 1}),
    "NA-200": ("推論主機 NA-200（GPU G2、SSD S2）", {"GPU-G2": 1, "SSD-S2": 1, "CPU-C1": 1, "RAM-R1": 4, "PSU-P1": 1}),
}
NA200_FROM = date(2026, 1, 1)
LOT_DATES = {
    "SSD-S1": ["2023-12-01", "2024-06-03", "2025-01-06", "2025-08-04", "2025-12-01"],
    "default": ["2023-12-01", "2024-07-01", "2025-01-06", "2025-07-07", "2026-01-05", "2026-07-06"],
}
BAD_LOT = "SSD-S1-L2508"
BAD_LOT_FAILED_SITES = ["H-I", "H-A", "H-C", "H-K"]  # in failure order; H-J and H-D not yet
BAD_LOT_FAILURE_DATES = ["2026-02-10", "2026-04-22", "2026-06-30", "2026-08-12"]

BACKGROUND_CATEGORIES = [  # category, weight, severity weights (low, medium, high)
    ("missed_nodule", 0.24, (0.2, 0.5, 0.3)),
    ("false_positive_increase", 0.18, (0.4, 0.5, 0.1)),
    ("slow_inference", 0.2, (0.5, 0.4, 0.1)),
    ("ui_usability", 0.26, (0.7, 0.3, 0.0)),
    ("qc_reject", 0.09, (0.5, 0.4, 0.1)),
    ("hardware_failure", 0.03, (0.1, 0.4, 0.5)),
]
TEMPLATES = {
    "missed_nodule": [
        "放射科醫師回報：一例追蹤 CT 上約 {size} mm 的{loc}結節未被標示。",
        "複判時發現{loc}一顆 {size} mm 結節漏標，請協助確認是否在產品規格範圍內。",
    ],
    "false_positive_increase": [
        "近兩週每例標示數明顯增加，多數落在血管分岔處，醫師複判負擔變重。",
        "誤報變多，醫師反映每例平均要多看 {n} 個標記。",
    ],
    "slow_inference": [
        "上午尖峰時段推論等待時間超過 {sec} 秒，影響報告時效。",
        "結果回傳變慢，單例處理時間約 {sec} 秒。",
    ],
    "ui_usability": [
        "結節清單的排序方式不直覺，希望能依大小排序。",
        "標記框在小螢幕上會遮住病灶，請評估調整顯示方式。",
        "希望報告匯出時能附上結節的切片位置。",
    ],
    "qc_reject": [
        "部分檢查被系統拒收，原因顯示「切片間距不符」，請說明規格。",
        "拒收比例上升，技術員不清楚該如何調整重建參數。",
    ],
    "hardware_failure": [
        "推論主機風扇異音，已安排現場檢查。",
        "推論主機電源異常重開機一次。",
    ],
}
LOCATIONS = ["右上葉", "右中葉", "右下葉", "左上葉", "左下葉", "貼肋膜處"]


def d(s: str) -> date:
    return date.fromisoformat(s)


def months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


@dataclass
class Appliance:
    serial_no: str
    sku: str
    site_id: str
    build_date: date
    install_date: date


class Builder:
    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.rows: dict[str, list[tuple]] = {}

    def add(self, table: str, *row):
        self.rows.setdefault(table, []).append(row)

    # ----- ERP -----
    def build_erp(self):
        rng = self.rng
        self.site_type = {}
        for sid, name, region, typ, live in SITES:
            self.add("sites", sid, name, region, typ, live)
            self.site_type[sid] = typ

        self.scanners: dict[str, list[tuple[str, date, date | None, float]]] = {}
        n = 0
        for sid, *_ , live in SITES:
            count = 2 if self.site_type[sid] != "地區醫院" else 1
            for _ in range(count):
                n += 1
                vendor, model, thick = rng.choice(SCANNER_MODELS)
                installed = d(live) - timedelta(days=rng.randint(200, 1500))
                self._scanner(f"CT-{n:03d}", sid, vendor, model, thick, installed)
        for sid, when in NEW_SCANNER_INSTALLS:
            n += 1
            self._scanner(f"CT-{n:03d}", sid, *NEW_SCANNER, d(when))

        for row in RELEASES:
            self.add("software_releases", *row)
        for row in SUPPLIERS:
            self.add("suppliers", *row)
        for p in PARTS:
            self.add("parts", *p, None)
        for sku, (desc, bom) in SKUS.items():
            self.add("appliance_skus", sku, desc)
            for part, qty in bom.items():
                self.add("sku_bom", sku, part, qty)

        self.lots: dict[str, list[tuple[str, date]]] = {}
        for part, *_ in PARTS:
            for received in LOT_DATES.get(part, LOT_DATES["default"]):
                r = d(received)
                lot = f"{part}-L{r:%y%m}"
                self.lots.setdefault(part, []).append((lot, r))
                self.add("part_lots", lot, part, received, rng.choice([20, 30, 40]))

        installs = [(sid, d(live)) for sid, *_, live in SITES for _ in range(self._base_count(sid))]
        installs += [(sid, d(when)) for sid, when in EXTRA_APPLIANCES]
        installs.sort(key=lambda x: (x[1], x[0]))
        self.appliances: list[Appliance] = []
        for i, (sid, inst) in enumerate(installs, 1):
            build = inst - timedelta(days=14)
            sku = "NA-200" if build >= NA200_FROM else "NA-100"
            a = Appliance(f"NA-{inst:%y}{i:04d}", sku, sid, build, inst)
            self.appliances.append(a)
            self.add("appliances", a.serial_no, sku, sid, build.isoformat(), inst.isoformat(), "in_service")
            for part, qty in SKUS[sku][1].items():
                lot = max((l for l in self.lots[part] if l[1] <= build), key=lambda l: l[1])[0]
                self.add("appliance_parts", a.serial_no, part, lot, qty)

        fee = {"醫學中心": 2_400_000, "區域醫院": 1_200_000, "地區醫院": 600_000}
        for sid, *_, live in SITES:
            start, k = d(live), 0
            while start <= AS_OF:
                k += 1
                end = start.replace(year=start.year + 1) - timedelta(days=1)
                self.add("licenses", f"LIC-{sid}-{k}", sid, start.isoformat(), end.isoformat(), fee[self.site_type[sid]])
                start = end + timedelta(days=1)

        self.version_at: dict[str, list[tuple[date, str]]] = {}
        k = 0
        for a in self.appliances:
            history = [(a.install_date, max(v for v, rel, *_ in RELEASES if d(rel) <= a.install_date and v != "2.0"))]
            for ver, (lo, hi) in UPGRADES.items():
                if a.site_id in LAGGING_SITES and ver == "1.2":
                    continue
                when = d(lo) + timedelta(days=rng.randint(0, (d(hi) - d(lo)).days))
                if when > a.install_date and ver > history[-1][1]:
                    history.append((when, ver))
            self.version_at[a.serial_no] = history
            for when, ver in history:
                k += 1
                self.add("deployments", f"DEP-{k:05d}", a.serial_no, ver, when.isoformat())

        for sid, *_, live in SITES:
            scale = SITE_SCALE[self.site_type[sid]]
            for y, m in months(d(live), AS_OF):
                month = f"{y}-{m:02d}"
                studies = int(rng.gauss(900, 80) * scale * (1 + 0.01 * (y - 2024) * 12))
                qc, marks = rng.uniform(0.01, 0.03), rng.gauss(1.6, 0.12)
                if sid == "H-B" and month >= "2026-06":
                    qc, marks = rng.uniform(0.11, 0.14), rng.gauss(2.75, 0.1)
                if sid == "H-F" and month >= "2026-08":
                    qc, marks = rng.uniform(0.05, 0.07), rng.gauss(2.2, 0.1)
                gen2 = any(a.site_id == sid and a.sku == "NA-200" for a in self.appliances)
                latency = rng.gauss(70 if gen2 else 95, 6)
                self.add("monthly_usage", sid, month, max(studies, 20), round(qc, 4), round(marks, 2), round(latency, 1))

    def _base_count(self, sid):
        return {"醫學中心": 2, "區域醫院": 1, "地區醫院": 1}[self.site_type[sid]]

    def _scanner(self, scanner_id, sid, vendor, model, thick, installed):
        self.add("ct_scanners", scanner_id, sid, vendor, model, thick, installed.isoformat(), None)
        self.scanners.setdefault(sid, []).append((scanner_id, installed, None, thick))

    # ----- QMS -----
    def build_qms(self):
        rng = self.rng
        complaints = []  # (date, site, category, severity, scanner, serial, version, text, status, capa)

        for sid, *_, live in SITES:
            lam = 0.55 * (0.4 + SITE_SCALE[self.site_type[sid]])
            for y, m in months(d(live), AS_OF):
                for _ in range(poisson(rng, lam)):
                    day = date(y, m, rng.randint(1, 28))
                    if not (d(live) <= day <= AS_OF):
                        continue
                    cat, _, sev_w = rng.choices(BACKGROUND_CATEGORIES, [c[1] for c in BACKGROUND_CATEGORIES])[0]
                    sev = rng.choices(["low", "medium", "high"], sev_w)[0]
                    serial = self._pick_appliance(sid, day, exclude_lot=BAD_LOT if cat == "hardware_failure" else None)
                    if serial is None:
                        continue
                    complaints.append([day, sid, cat, sev, self._pick_scanner(sid, day, old_only=True), serial,
                                       self._version(serial, day), self._text(cat), None, None])

        new_ct = {sid: next(s[0] for s in self.scanners[sid] if s[3] == NEW_SCANNER[2]) for sid, _ in NEW_SCANNER_INSTALLS}
        s1 = [("2026-06-09", "false_positive_increase", "medium", "新 CT 上線後每例標示數明顯增加，醫師複判負擔變重。"),
              ("2026-06-16", "qc_reject", "medium", "新 CT 送來的檢查有一部分被拒收，原因顯示切片間距不符。"),
              ("2026-06-24", "false_positive_increase", "high", "新 CT 的檢查誤報很多，部分醫師開始不看 AI 標記。"),
              ("2026-07-02", "qc_reject", "medium", "拒收比例仍偏高，技術員詢問是否要改重建參數。"),
              ("2026-07-08", "missed_nodule", "high", "新 CT 一例約 5 mm 結節未被標示，請協助調查。"),
              ("2026-07-21", "false_positive_increase", "medium", "誤報情況未改善，請回覆調查進度。")]
        for when, cat, sev, text in s1:
            serial = self._pick_appliance("H-B", d(when))
            complaints.append([d(when), "H-B", cat, sev, new_ct["H-B"], serial, self._version(serial, d(when)),
                               text, "investigating", "CAPA-2026-007"])
        for when, cat, text in [("2026-08-19", "false_positive_increase", "新 CT 上線後誤報變多，想確認是否需要調整設定。"),
                                ("2026-09-03", "qc_reject", "新 CT 的部分檢查被拒收，請說明輸入規格。")]:
            serial = self._pick_appliance("H-F", d(when))
            complaints.append([d(when), "H-F", cat, "medium", new_ct["H-F"], serial, self._version(serial, d(when)),
                               text, "open", None])

        bad = {a.site_id: a.serial_no for a in self.appliances if self._lot(a.serial_no, "SSD-S1") == BAD_LOT}
        for sid, when in zip(BAD_LOT_FAILED_SITES, BAD_LOT_FAILURE_DATES):
            serial = bad[sid]
            complaints.append([d(when), sid, "hardware_failure", "high", self._pick_scanner(sid, d(when), old_only=True),
                               serial, self._version(serial, d(when)),
                               "推論主機開機時偵測不到資料碟，系統日誌出現 NVMe I/O 錯誤，服務中斷。",
                               "investigating", "CAPA-2026-004"])

        capas = self._capas(complaints)
        for c in complaints:
            if c[8] is None:
                c[8] = "closed" if (AS_OF - c[0]).days > 60 else rng.choice(["open", "investigating"])
        complaints.sort(key=lambda c: (c[0], c[1]))
        seq: dict[int, int] = {}
        for c in complaints:
            seq[c[0].year] = seq.get(c[0].year, 0) + 1
            component = None
            if c[2] == "hardware_failure":
                component = "SSD" if "NVMe" in c[7] else "FAN" if "風扇" in c[7] else "PSU"
            self.add("complaints", f"CMP-{c[0].year}-{seq[c[0].year]:04d}", c[1], c[0].isoformat(), *c[2:7],
                     component, c[7], c[8], c[9])
        for row in capas:
            self.add("capas", *row)

        self.add("change_requests", "ECR-2026-008", "model_update", "NoduleAssist 2.0 模型更新", "2026-07-30",
                 "under_review", None, "2.0", None, "新模型架構；依變更管制程序評估是否需要重新送審。")
        self.add("change_requests", "ECR-2026-009", "component_change", "GPU G1 停產，評估以 GPU G2 替代", "2026-08-27",
                 "draft", "GPU-G1", None, None, "供應商甲通知 GPU G1 停產，最後採購日 2027-02-26。需評估替代料與再驗證範圍。")
        self.add("change_requests", "ECR-2026-010", "sop_update", "安裝 SOP 加入 CT 重建切片厚度檢查", "2026-09-10",
                 "draft", None, None, "CAPA-2026-007", "新站點或新 CT 上線前，確認重建切片厚度符合輸入規格。")

    def _capas(self, complaints):
        rng = self.rng
        rows = [
            ("CAPA-2026-004", "SSD S1 特定批號早期失效調查", "2026-07-01", "2026-10-31", None, "in_progress",
             "supplier_component", "Service", "多台推論主機資料碟故障，初步懷疑與 SSD 批號有關，待確認影響範圍。"),
            ("CAPA-2026-007", "醫院B 新 CT 機型輸入超出規格", "2026-07-15", "2026-09-15", None, "in_progress",
             "input_out_of_spec", "QA", "醫院B 新 CT 上線後誤報與拒收增加，調查中。"),
        ]
        background = [  # id, title, opened, days to due, closed after (None = still open), root cause, owner
            ("CAPA-2024-001", "標記框遮蔽病灶的顯示問題", "2024-05-20", 90, 70, "software_defect", "RD"),
            ("CAPA-2024-002", "推論尖峰延遲", "2024-11-04", 90, 85, "software_defect", "RD"),
            ("CAPA-2025-001", "貼肋膜結節漏標分析", "2025-02-17", 120, 110, "software_defect", "RD"),
            ("CAPA-2025-002", "技術員未依建議重建參數送檢", "2025-05-12", 60, 40, "user_training", "QA"),
            ("CAPA-2025-003", "風扇異音", "2025-09-08", 60, 75, "supplier_component", "Service"),
            ("CAPA-2025-004", "報告匯出欄位缺漏", "2025-11-24", 90, None, "software_defect", "RD"),
            ("CAPA-2026-001", "結節清單排序需求評估", "2026-01-19", 60, 50, "user_training", "QA"),
            ("CAPA-2026-002", "推論等待時間異常", "2026-03-09", 90, None, "unknown", "RD"),
            ("CAPA-2026-003", "誤報投訴趨勢分析", "2026-04-20", 120, None, "unknown", "QA"),
            ("CAPA-2026-005", "漏標投訴季度審查", "2026-06-01", 60, 58, "software_defect", "RD"),
            ("CAPA-2026-006", "使用者教育訓練教材更新", "2026-06-22", 120, None, "user_training", "QA"),
        ]
        link = {"ui_usability": ["CAPA-2024-001", "CAPA-2025-004", "CAPA-2026-001"],
                "slow_inference": ["CAPA-2024-002", "CAPA-2026-002"],
                "missed_nodule": ["CAPA-2025-001", "CAPA-2026-005"],
                "qc_reject": ["CAPA-2025-002"],
                "false_positive_increase": ["CAPA-2026-003"],
                "hardware_failure": ["CAPA-2025-003"]}
        windows = {}
        for cid, title, opened, due_days, closed_after, root, owner in background:
            o = d(opened)
            closed = o + timedelta(days=closed_after) if closed_after is not None else None
            status = "closed" if closed and closed <= AS_OF else rng.choice(["open", "in_progress"])
            rows.append((cid, title, opened, (o + timedelta(days=due_days)).isoformat(),
                         closed.isoformat() if status == "closed" else None, status, root, owner,
                         f"{title}：彙整相關客訴並確認根本原因。"))
            windows[cid] = (o - timedelta(days=120), o)
        for c in complaints:
            if c[9] is None:
                for cid in link.get(c[2], []):
                    lo, hi = windows[cid]
                    if lo <= c[0] <= hi and rng.random() < 0.6:
                        c[9] = cid
                        break
        return sorted(rows)

    def _pick_appliance(self, sid, day, exclude_lot=None):
        pool = [a.serial_no for a in self.appliances if a.site_id == sid and a.install_date <= day
                and (exclude_lot is None or self._lot(a.serial_no, "SSD-S1") != exclude_lot)]
        return self.rng.choice(pool) if pool else None

    def _pick_scanner(self, sid, day, old_only=False):
        pool = [s[0] for s in self.scanners[sid] if s[1] <= day and not (old_only and s[3] == NEW_SCANNER[2])]
        return self.rng.choice(pool)

    def _version(self, serial, day):
        return [v for when, v in self.version_at[serial] if when <= day][-1]

    def _lot(self, serial, part):
        return next((r[2] for r in self.rows["appliance_parts"] if r[0] == serial and r[1] == part), None)

    def _text(self, cat):
        return self.rng.choice(TEMPLATES[cat]).format(
            size=self.rng.choice([4, 5, 6, 7, 8, 10]), loc=self.rng.choice(LOCATIONS),
            n=self.rng.randint(2, 4), sec=self.rng.choice([180, 240, 300, 420]))


TABLE_ORDER = ["sites", "ct_scanners", "software_releases", "suppliers", "parts", "appliance_skus", "sku_bom",
               "part_lots", "appliances", "appliance_parts", "licenses", "deployments", "monthly_usage",
               "capas", "complaints", "change_requests"]


def build(seed: int = SEED) -> dict[str, list[tuple]]:
    b = Builder(seed)
    b.build_erp()
    b.build_qms()
    return b.rows


def write_sqlite(rows: dict[str, list[tuple]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    for table in TABLE_ORDER:
        data = rows.get(table, [])
        if data:
            con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(data[0]))})", data)
    con.commit()
    con.close()


def write_csv(rows: dict[str, list[tuple]], out: Path) -> None:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    for table in TABLE_ORDER:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        with open(out / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows.get(table, []))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("data/synthetic/erpqms"))
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    rows = build(args.seed)
    write_sqlite(rows, args.out / "erpqms.sqlite")
    write_csv(rows, args.out / "csv")
    for table in TABLE_ORDER:
        print(f"{table:18s} {len(rows.get(table, [])):6d}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
