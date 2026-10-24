"""Text-to-SQL for the manager dashboard: a question in, one read-only SELECT out.

The model sees the schema and the question, never the data: rows go straight to the screen, not
back to the model, so text stored in the database (complaint descriptions) cannot steer it.

What runs is checked twice before and during execution:
1. `check_sql`: one statement, starting with SELECT or WITH, comments removed;
2. the SQLite connection is read-only (`mode=ro`) and has an authorizer that allows only reading
   tables and calling functions, so ATTACH, PRAGMA, writes and schema changes are refused by the
   database itself even if a check above were wrong; a progress handler stops runaway queries and
   at most `MAX_ROWS` rows are returned.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

SCHEMA_SQL = Path(__file__).resolve().parents[3] / "packages/erpqms/erpqms/schema.sql"
AS_OF = "2026-09-30"
MAX_ROWS = 500
MAX_VM_STEPS = 50_000_000  # SQLite progress-handler budget, about a few seconds on a laptop

SYSTEM_PROMPT = f"""You write one SQLite query for Company M's ERP + QMS database (synthetic data).
Rules:
- Return exactly one read-only query (SELECT or WITH ... SELECT) in a ```sql code block, nothing else needed.
- Use only the tables and columns in the schema below. Dates are ISO strings; months are 'YYYY-MM'.
- "Today" is {AS_OF}. Use it for anything relative to now (overdue, current, expiring).
- Give columns short readable names. Do not add LIMIT unless the question asks for a top N.

Schema:
"""


class SQLRejected(Exception):
    pass


def schema_prompt() -> str:
    return SYSTEM_PROMPT + SCHEMA_SQL.read_text(encoding="utf-8")


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()


def check_sql(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if not sql:
        raise SQLRejected("empty query")
    if ";" in sql:
        raise SQLRejected("only one statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", sql):
        raise SQLRejected("only SELECT queries are allowed")
    return sql


_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED.add(sqlite3.SQLITE_RECURSIVE)


def _authorizer(action, arg1, arg2, dbname, source):
    if action not in _ALLOWED:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and arg1 and arg1.startswith("sqlite_"):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def connect(path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, check_same_thread=False)
    con.set_authorizer(_authorizer)
    return con


def run_sql(con: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple]]:
    sql = check_sql(sql)
    steps = {"n": 0}

    def budget():
        steps["n"] += 1
        return 1 if steps["n"] > MAX_VM_STEPS // 1000 else 0

    con.set_progress_handler(budget, 1000)
    try:
        cur = con.execute(sql)
        rows = cur.fetchmany(MAX_ROWS)
    except sqlite3.DatabaseError as e:
        raise SQLRejected(f"database refused the query: {e}") from e
    finally:
        con.set_progress_handler(None, 0)
    return [c[0] for c in cur.description], rows


def ask(llm, question: str) -> dict:
    """One model call: question -> SQL. Returns the raw reply and the extracted SQL."""
    t0 = time.time()
    reply = llm.chat([{"role": "system", "content": schema_prompt()}, {"role": "user", "content": question}], [])
    return {"sql": extract_sql(reply.content), "raw": reply.content, "usage": reply.usage,
            "seconds": round(time.time() - t0, 2)}


# ---------------- evaluation ----------------
def _norm(v):
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, int):
        return float(v)
    return v


def results_match(gold: tuple[list[str], list[tuple]], pred: tuple[list[str], list[tuple]]) -> bool:
    """Same rows, ignoring row order, column order, column names and extra predicted columns.

    Each gold column is matched to a distinct predicted column holding the same multiset of values;
    the prediction is projected onto those columns and the rows are compared as multisets.
    """
    g_rows = [tuple(_norm(v) for v in r) for r in gold[1]]
    p_rows = [tuple(_norm(v) for v in r) for r in pred[1]]
    if len(g_rows) != len(p_rows):
        return False
    if not g_rows:
        return True
    k, m = len(g_rows[0]), len(p_rows[0])
    g_cols = [Counter(r[i] for r in g_rows) for i in range(k)]
    p_cols = [Counter(r[j] for r in p_rows) for j in range(m)]

    def search(i, used, mapping):
        if i == k:
            proj = Counter(tuple(r[j] for j in mapping) for r in p_rows)
            return proj == Counter(g_rows)
        for j in range(m):
            if j not in used and p_cols[j] == g_cols[i] and search(i + 1, used | {j}, mapping + [j]):
                return True
        return False

    return search(0, frozenset(), [])
