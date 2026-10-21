"""Run every query in scenarios.sql on SQLite and on PostgreSQL and require identical results.

    python scripts/check_postgres.py --dsn "host=localhost user=postgres password=postgres dbname=erpqms"

Loads the data with load_postgres.sh first. Needs psql on PATH and psycopg installed.
"""
import argparse
import re
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from erpqms import generate  # noqa: E402


def normalise(rows):
    return [tuple(float(v) if isinstance(v, (float, Decimal)) else str(v) if v is not None else None for v in r)
            for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        rows = generate.build()
        generate.write_csv(rows, Path(tmp) / "csv")
        generate.write_sqlite(rows, Path(tmp) / "erpqms.sqlite")
        subprocess.run([str(ROOT / "scripts/load_postgres.sh"), str(Path(tmp) / "csv"), args.dsn], check=True)
        lite = sqlite3.connect(Path(tmp) / "erpqms.sqlite")
        parts = re.split(r"^-- name: (\w+)\s*$", (ROOT / "scenarios.sql").read_text(encoding="utf-8"), flags=re.M)
        failed = 0
        with psycopg.connect(args.dsn) as pg:
            for name, sql in zip(parts[1::2], parts[2::2]):
                a = normalise(lite.execute(sql).fetchall())
                b = normalise(pg.execute(sql).fetchall())
                ok = a == b
                failed += not ok
                print(f"{'OK  ' if ok else 'DIFF'} {name} ({len(a)} rows)")
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
