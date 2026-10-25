"""Claude as a backend for the agent loop, through the official Anthropic SDK.

The agent loop keeps its history in the OpenAI-style shape the local servers use (system / user /
assistant with tool_calls / tool). This adapter converts that history to the Messages API on each
call and converts the reply back. Claude's own content blocks (including thinking blocks, which
must be sent back unchanged) are kept on the assistant message under `_raw` and replayed as-is;
local backends ignore keys that start with an underscore.

Credentials come from the environment (ANTHROPIC_API_KEY or another source the SDK resolves).
Which requests may reach Claude at all is decided by the gateway (gateway.py), not here.
"""
from __future__ import annotations

import json
import time

import anthropic

from .agent import LLMReply

DEFAULT_MODEL = "claude-opus-5-5"


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    out: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            if m.get("_raw") is not None:
                out.append({"role": "assistant", "content": m["_raw"]})
                continue
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for c in m.get("tool_calls") or []:
                args = c["function"]["arguments"]
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                               "input": args if isinstance(args, dict) else {}})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            # every result of one assistant turn goes back in a single user message
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return system, out


def to_anthropic_tools(specs: list[dict]) -> list[dict]:
    return [{"name": s["function"]["name"], "description": s["function"]["description"],
             "input_schema": s["function"]["parameters"]} for s in specs]


class ClaudeLLM:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "medium", max_tokens: int = 16000,
                 client: anthropic.Anthropic | None = None):
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self.client = client or anthropic.Anthropic()

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        system, msgs = to_anthropic(messages)
        t0 = time.time()
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, messages=msgs,
                      output_config={"effort": self.effort},
                      # on a safety decline the API re-runs the request on a fallback model it chooses
                      betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)
        r = self.client.beta.messages.create(**kwargs)
        raw = r.to_dict()["content"]
        usage = {"prompt_tokens": r.usage.input_tokens, "completion_tokens": r.usage.output_tokens}
        if r.stop_reason == "refusal":
            return LLMReply("（雲端模型拒絕回答這個請求）", [], time.time() - t0, usage, raw=raw)
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)}
                 for b in r.content if b.type == "tool_use"]
        return LLMReply(text, calls, time.time() - t0, usage, raw=raw)
