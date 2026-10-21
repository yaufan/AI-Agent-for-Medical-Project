"""The generator must be deterministic, referentially sound, and contain the planted storylines."""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from erpqms import generate  # noqa: E402

AS_OF = "2026-09-30"


def load_queries():
    text = (ROOT / "scenarios.sql").read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.M)
    return {name: body.strip() for name, body in zip(parts[1::2], parts[2::2])}


Q = load_queries()


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("erpqms") / "erpqms.sqlite"
    generate.write_sqlite(generate.build(), path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def rows(db, name):
    return [dict(r) for r in db.execute(Q[name])]


def test_deterministic():
    assert generate.build() == generate.build()
    assert generate.build(seed=1) != generate.build()


def test_foreign_keys(db):
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_no_dates_after_reference(db):
    for table, col in [("complaints", "received_at"), ("deployments", "deployed_at"),
                       ("capas", "opened_at"), ("appliances", "install_date")]:
        assert db.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0] <= AS_OF


def test_complaints_reference_installed_equipment(db):
    bad = db.execute("""
        SELECT c.complaint_id FROM complaints c
        JOIN appliances a ON a.serial_no = c.serial_no
        JOIN ct_scanners ct ON ct.scanner_id = c.scanner_id
        WHERE a.install_date > c.received_at OR ct.installed_at > c.received_at
           OR a.site_id <> c.site_id OR ct.site_id <> c.site_id""").fetchall()
    assert bad == []


def test_s1_new_ct(db):
    r = {x["site_id"]: x for x in rows(db, "s1_new_ct_complaints")}
    assert set(r) == {"H-B", "H-F"}
    assert (r["H-B"]["complaints"], r["H-B"]["linked_to_capa"]) == (6, 6)
    assert (r["H-F"]["complaints"], r["H-F"]["linked_to_capa"]) == (2, 0)
    assert {x["model"] for x in rows(db, "s1_out_of_spec_scanners")} == {"C-320"}
    usage = rows(db, "s1_usage_before_after")
    before = [u["marks_per_study"] for u in usage if u["month"] < "2026-06"]
    after = [u["marks_per_study"] for u in usage if u["month"] >= "2026-06"]
    assert min(after) > max(before)


def test_s2_bad_lot(db):
    r = rows(db, "s2_bad_lot_trace")
    assert len(r) == 6
    assert sorted(x["site_id"] for x in r if x["ssd_failures"] == 0) == ["H-D", "H-J"]
    by_lot = rows(db, "s2_failure_rate_by_lot")
    assert by_lot[0]["lot_no"] == "SSD-S1-L2508"
    assert all(x["appliances_failed"] == 0 for x in by_lot[1:])


def test_s3_eol_gpu(db):
    exposure = rows(db, "s3_eol_gpu_exposure")
    assert exposure and all(x["part_no"] == "GPU-G1" for x in exposure)
    ecr = db.execute("SELECT status FROM change_requests WHERE related_part_no = 'GPU-G1'").fetchone()
    assert ecr["status"] == "draft"


def test_s4_versions_and_capas(db):
    current = rows(db, "s4_current_versions")
    lagging = {x["site_id"] for x in current if x["version"] != "1.2"}
    assert lagging == {"H-E", "H-G"}
    assert all(x["version"] != "2.0" for x in current)
    overdue = {x["capa_id"] for x in rows(db, "s4_overdue_capas")}
    assert "CAPA-2026-007" in overdue and "CAPA-2026-004" not in overdue


def test_neutral_names_only(db):
    names = {r[0] for r in db.execute("SELECT name FROM sites")}
    assert all(re.fullmatch(r"醫院[A-L]", n) for n in names)
    vendors = {r[0] for r in db.execute("SELECT vendor FROM ct_scanners")}
    assert all(re.fullmatch(r"CT廠牌[ABC]", v) for v in vendors)
