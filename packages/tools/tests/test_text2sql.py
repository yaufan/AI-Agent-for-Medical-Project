"""Text-to-SQL: only reads get through, and the result comparison used for evaluation."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in ("packages/tools", "packages/erpqms"):
    sys.path.insert(0, str(ROOT / p))

from agenttools import text2sql as t  # noqa: E402
from agenttools.agent import LLMReply  # noqa: E402
from agenttools.testing import ScriptedLLM  # noqa: E402
from erpqms import generate  # noqa: E402


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    db = tmp_path_factory.mktemp("t2s") / "erpqms.sqlite"
    generate.write_sqlite(generate.build(), db)
    return t.connect(db)


@pytest.mark.parametrize("sql", [
    "DELETE FROM complaints", "UPDATE capas SET status = 'closed'", "DROP TABLE sites",
    "SELECT 1; DELETE FROM complaints", "ATTACH DATABASE '/tmp/x.db' AS x", "PRAGMA table_info(sites)",
    "INSERT INTO sites VALUES ('H-Z','x','x','x','2026-01-01')", "", "-- just a comment",
])
def test_non_select_is_rejected_before_running(sql):
    with pytest.raises(t.SQLRejected):
        t.check_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM sqlite_master",                                   # schema internals
    "WITH x AS (SELECT 1) SELECT * FROM x, pragma_table_info('sites')",  # pragma as a table function
])
def test_database_authorizer_refuses_what_the_text_check_lets_through(con, sql):
    with pytest.raises(t.SQLRejected):
        t.run_sql(con, sql)


def test_runaway_query_is_stopped(con):
    with pytest.raises(t.SQLRejected):
        t.run_sql(con, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n")


def test_rows_are_capped(con):
    _, rows = t.run_sql(con, "SELECT * FROM complaints a, complaints b")
    assert len(rows) == t.MAX_ROWS


def test_comments_and_trailing_semicolon_are_fine(con):
    cols, rows = t.run_sql(con, "-- sites\nSELECT region, COUNT(*) FROM sites /* all */ GROUP BY region;")
    assert len(rows) == 4 and len(cols) == 2


def test_results_match_ignores_order_names_and_extra_columns():
    gold = (["site", "n"], [("H-A", 2), ("H-B", 3)])
    assert t.results_match(gold, (["count", "site_id", "name"], [(3, "H-B", "醫院B"), (2, "H-A", "醫院A")]))
    assert t.results_match(gold, (["s", "n"], [("H-B", 3.0), ("H-A", 2.0)]))
    assert not t.results_match(gold, (["s", "n"], [("H-A", 3), ("H-B", 2)]))   # values swapped between rows
    assert not t.results_match(gold, (["s", "n"], [("H-A", 2)]))                # missing row
    assert t.results_match((["r"], [(0.1272,)]), (["r"], [(0.12724,)]))       # rounding to 2 decimals


def test_ask_extracts_sql_and_never_sends_data():
    llm = ScriptedLLM([LLMReply("```sql\nSELECT region, COUNT(*) FROM sites GROUP BY region\n```", [], 0.1)])
    out = t.ask(llm, "各區域各有幾家站點？")
    assert out["sql"].startswith("SELECT region")
    sent = str(llm.seen[0])
    assert "CREATE TABLE complaints" in sent and "各區域各有幾家站點" in sent
    assert "CMP-2026-" not in sent and "CAPA-2026-" not in sent   # schema and question only, no rows
