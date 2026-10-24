"""Test doubles for the agent loop. Not used in production paths.

`ScriptedLLM` replays fixed replies. `CompliantAttackerLLM` stands in for a fully hijacked model: it
makes one ordinary read call, then obeys any tool instruction it finds in tool results (the shape a
prompt injection takes), then answers. Running the injection suite against it measures what the
guard and human approval stop even when the model itself is fooled every time.
"""
from __future__ import annotations

import json
import re

from .agent import LLMReply

DIRECTIVE = re.compile(r"(?:呼叫|call)\s*([a-z_]+)", re.I)


def directives(text: str) -> list[tuple[str, str]]:
    """Each "call <tool> {json}" in the text: the tool name and its balanced {...} argument block."""
    out = []
    for m in DIRECTIVE.finditer(text):
        start = text.find("{", m.end())
        if start < 0 or start - m.end() > 40:
            continue
        depth = 0
        for i in range(start, len(text)):
            depth += text[i] == "{"
            depth -= text[i] == "}"
            if depth == 0:
                out.append((m.group(1), text[start:i + 1]))
                break
    return out


class ScriptedLLM:
    def __init__(self, replies: list[LLMReply]):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []  # the messages of every call, for assertions

    def chat(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


class CompliantAttackerLLM:
    def __init__(self, first_call: tuple[str, dict]):
        self.first_call = first_call
        self.followed: set[str] = set()

    def chat(self, messages, tools):
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            name, args = self.first_call
            return LLMReply("", [{"id": "c0", "name": name, "arguments": json.dumps(args, ensure_ascii=False)}], 0.0)
        for m in tool_msgs:
            for name, raw in directives(m["content"]):
                key = name + raw
                if key in self.followed:
                    continue
                self.followed.add(key)
                # the instruction may sit inside a JSON string in the tool result, with its quotes escaped
                for candidate in (raw, raw.replace('\\"', '"')):
                    try:
                        json.loads(candidate)
                        raw = candidate
                        break
                    except json.JSONDecodeError:
                        continue
                return LLMReply("", [{"id": f"c{len(self.followed)}", "name": name, "arguments": raw}], 0.0)
        return LLMReply("已整理完畢。", [], 0.0)
