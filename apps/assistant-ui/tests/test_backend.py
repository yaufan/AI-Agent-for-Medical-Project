"""The demo UI's backend without Chainlit: a turn, its tool calls, a draft, and the approval rules."""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Backend, describe_draft, sources_from_calls  # noqa: E402


def make(tmp_path):
    return Backend(data_dir=tmp_path, http_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                   include_public_pdfs=False)  # synthetic documents only: fast and the same with or without downloads


def test_workflow_turn_records_calls_and_sources(tmp_path):
    b = make(tmp_path)
    turn = b.ask("qa_lin", "哪些醫院有 C-320 這款 CT？")
    assert "醫院B" in turn.answer and "醫院F" in turn.answer
    assert [c["tool"] for c in turn.calls] == ["sites_with_scanner_model"] and turn.calls[0]["ok"]
    assert turn.sources and turn.drafts == [] and turn.mode.startswith("固定流程")


def test_draft_then_approval_by_the_right_person(tmp_path):
    b = make(tmp_path)
    turn = b.ask("qa_lin", "醫院F 的 C-320 客訴還沒連到 CAPA，請幫我起草 CAPA，關聯這些客訴")
    assert len(turn.drafts) == 1
    draft_id = turn.drafts[0]["draft_id"]
    assert draft_id in describe_draft(turn.drafts[0]) and "⚠️" not in describe_draft(turn.drafts[0])
    assert b.pending_for("qa_lin") == []                      # an engineer cannot approve CAPA drafts
    ok, msg = b.decide("qa_lin", draft_id, approve=True)
    assert not ok and "may not decide" in msg
    assert [d["draft_id"] for d in b.pending_for("qa_mgr_chou")] == [draft_id]
    ok, _ = b.decide("qa_mgr_chou", draft_id, approve=True)
    assert ok and b.pending_for("qa_mgr_chou") == []
    assert [a["action"] for a in b.drafts.audit()] == ["draft_created", "draft_approved"]


def test_access_control_holds_in_the_ui(tmp_path):
    b = make(tmp_path)
    turn = b.ask("qa_lin", "NoduleAssist 2.0 預計什麼時候提出 510(k)？")
    assert "2027-01-29" not in turn.answer                   # proj-b document, qa_lin is not in proj-b


def test_sources_from_agent_calls():
    calls = [{"tool": "get_capa", "ok": True, "kind": "read", "args": {"capa_id": "CAPA-2026-007"},
              "result": {"capa": {"capa_id": "CAPA-2026-007"}}},
             {"tool": "site_overview", "ok": False, "kind": "read", "args": {"site_id": "H-Z"}, "result": {}}]
    assert sources_from_calls(calls) == ["CAPA-2026-007"]


def test_dashboard_is_for_operations_managers_only(tmp_path):
    b = make(tmp_path)
    panels = b.dashboard("ops_mgr_tsai")
    assert len(panels) == 6 and all(p.rows for p in panels if p.title != "2026 年底前到期的授權")
    overdue = next(p for p in panels if "CAPA" in p.title)
    assert "CAPA-2026-007" in {r[0] for r in overdue.rows}
    import pytest
    with pytest.raises(PermissionError):
        b.dashboard("qa_lin")
    with pytest.raises(PermissionError):
        b.ask_sql("contractor_lee", "SELECT * FROM licenses")


def test_text_to_sql_needs_a_model_and_runs_only_reads(tmp_path, monkeypatch):
    import backend
    from agenttools.agent import LLMReply
    from agenttools.testing import ScriptedLLM

    b = make(tmp_path)
    assert "設定模型" in b.ask_sql("ops_mgr_tsai", "各區域各有幾家站點？").error

    b.llm_base_url, b.llm_model = "http://model.invalid/v1", "m"
    replies = iter(["```sql\nSELECT region, COUNT(*) AS sites FROM sites GROUP BY region\n```",
                    "```sql\nDELETE FROM complaints\n```"])
    monkeypatch.setattr(backend.agent, "ChatLLM", lambda *a, **k: ScriptedLLM([LLMReply(next(replies), [], 0.1)]))
    t = b.ask_sql("ops_mgr_tsai", "各區域各有幾家站點？")
    assert t.chart == "bar" and sorted(r[1] for r in t.rows) == [2, 3, 3, 4]
    bad = b.ask_sql("ops_mgr_tsai", "把客訴清空")
    assert bad.error.startswith("查詢被拒絕") and bad.rows == []


def test_chart_guess():
    from backend import guess_chart
    assert guess_chart(["site", "n"], [("H-A", 1)]) == "bar"
    assert guess_chart(["month", "n"], [("2026-01", 1)]) == "line"
    assert guess_chart(["a", "b", "c"], [("x", "y", 1)]) == "table"
