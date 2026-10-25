"""Sensitivity labels, routing decisions and the Claude message conversion (no network)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/tools"))

from agenttools import sensitivity as s  # noqa: E402
from agenttools.agent import LLMReply  # noqa: E402
from agenttools.claude_llm import ClaudeLLM, to_anthropic, to_anthropic_tools  # noqa: E402
from agenttools.core import Session  # noqa: E402
from agenttools.gateway import NO_LOCAL, RoutedLLM  # noqa: E402
from agenttools.testing import ScriptedLLM  # noqa: E402


def test_text_labels():
    assert s.label_text("哪些醫院有 C-320？") == (s.INTERNAL, [])
    assert s.label_text("NoduleAssist 2.0 的時程")[0] == s.CONFIDENTIAL
    assert s.label_text("聯絡 0912-345-678")[0] == s.RESTRICTED
    assert s.label_text("寄到 a.b@example.com")[0] == s.RESTRICTED
    assert s.label_text("出貨日 2026-09-30，序號 NA-240010，年費 2400000")[0] == s.INTERNAL  # no false PII


def test_result_labels():
    kb = {"untrusted": [{"classification": "public"}, {"classification": "confidential"}]}
    assert s.label_result("search_knowledge_base", kb)[0] == s.CONFIDENTIAL
    assert s.label_result("search_510k", {"untrusted": [{"k_number": "K1"}]})[0] == s.PUBLIC
    assert s.label_result("list_complaints", {"complaints": [], "untrusted": [{"description": "電話 02-2345-6789"}]})[0] \
        == s.RESTRICTED
    assert s.label_result("some_new_tool", {"x": 1})[0] == s.CONFIDENTIAL   # unknown tools assume the worst
    assert s.label_result("get_capa", {"error": {"code": "not_found"}})[0] == s.PUBLIC


class Rec:
    def __init__(self, name):
        self.name, self.calls = name, 0

    def chat(self, messages, tools):
        self.calls += 1
        return LLMReply(self.name, [], 0.0)


def test_routing_moves_to_local_and_stays_there():
    session = Session("ra_huang", {"internal"}, request="2.0 版預計什麼時候送審？")
    local, cloud = Rec("local"), Rec("cloud")
    llm = RoutedLLM(local, cloud, session)
    llm.chat([], [])
    session.data_level = s.CONFIDENTIAL          # a confidential passage came back
    llm.chat([], [])
    session.data_level = s.PUBLIC                # never moves back within the turn
    llm.chat([], [])
    assert [d["backend"] for d in llm.decisions] == ["cloud", "local", "local"]


def test_cloud_only_deployment_refuses_instead_of_sending():
    session = Session("qa_lin", {"internal"}, request="病歷號 A20260915 的檢查")
    cloud = Rec("cloud")
    reply = RoutedLLM(None, cloud, session).chat([], [])
    assert reply.content == NO_LOCAL and cloud.calls == 0


def test_openai_history_converts_to_messages_api():
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "_raw": None, "tool_calls": [
            {"id": "c0", "type": "function", "function": {"name": "get_capa", "arguments": '{"capa_id": "CAPA-2026-007"}'}},
            {"id": "c1", "type": "function", "function": {"name": "site_overview", "arguments": '{"site_id": "H-B"}'}}]},
        {"role": "tool", "tool_call_id": "c0", "content": "r0"},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "assistant", "content": "x", "_raw": [{"type": "thinking", "thinking": "", "signature": "sig"},
                                                       {"type": "text", "text": "x"}], "tool_calls": []},
    ]
    system, msgs = to_anthropic(history)
    assert system == "sys" and [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert [b["type"] for b in msgs[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["c0", "c1"]   # both results in one message
    assert msgs[3]["content"][0]["signature"] == "sig"                     # Claude's own blocks replayed as-is
    tools = to_anthropic_tools([{"type": "function", "function": {"name": "t", "description": "d",
                                                                    "parameters": {"type": "object"}}}])
    assert tools == [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]


class FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_response(stop_reason, content):
    blocks = [SimpleNamespace(**b) for b in content]
    return SimpleNamespace(stop_reason=stop_reason, content=blocks,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                           to_dict=lambda: {"content": content})


def test_claude_reply_parsing_and_request_shape():
    resp = fake_response("tool_use", [{"type": "text", "text": "查一下"},
                                      {"type": "tool_use", "id": "toolu_1", "name": "get_capa",
                                       "input": {"capa_id": "CAPA-2026-007"}}])
    messages = FakeMessages(resp)
    llm = ClaudeLLM(client=SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    reply = llm.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}], [])
    assert reply.tool_calls[0]["name"] == "get_capa" and json.loads(reply.tool_calls[0]["arguments"])["capa_id"]
    assert reply.raw == resp.to_dict()["content"] and reply.usage == {"prompt_tokens": 10, "completion_tokens": 5}
    k = messages.kwargs
    assert k["model"] == "claude-opus-5-5" and k["fallbacks"] == "default" and "tools" not in k
    assert "temperature" not in k and "thinking" not in k


def test_claude_refusal_is_not_read_as_an_answer():
    messages = FakeMessages(fake_response("refusal", []))
    reply = ClaudeLLM(client=SimpleNamespace(beta=SimpleNamespace(messages=messages))).chat(
        [{"role": "user", "content": "q"}], [])
    assert reply.tool_calls == [] and "拒絕" in reply.content
