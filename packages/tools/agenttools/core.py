"""Tool registry shared by the MCP server, the agent loop and the tests.

Each tool declares a JSON schema for its arguments and whether it only reads (`read`) or proposes a
change (`write`). The registry validates arguments before any tool code runs; a tool never sees
input that failed validation. Who is calling comes from the `Session`, which the host builds from
the signed-in user — it is never an argument the model can fill in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """Raised for rejected calls. `code` is stable; the message is safe to show the model."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Session:
    user: str                 # bound by the host from the signed-in user
    groups: set[str]          # document access groups, looked up at session start
    role: str = ""
    request: str = ""         # the user's own words for this turn (used by the write policy)
    trace: list[dict] = field(default_factory=list)
    untrusted_seen: list[str] = field(default_factory=list)  # third-party text returned by tools this turn


@dataclass
class Tool:
    name: str
    description: str
    kind: str                 # "read" or "write"
    schema: dict
    fn: Callable[..., Any]

    def openai_spec(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.schema}}


def _check(schema: dict, value: Any, path: str) -> None:
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            raise ToolError("invalid_argument", f"{path or 'arguments'} must be an object")
        props = schema.get("properties", {})
        unknown = set(value) - set(props)
        if unknown and not schema.get("additionalProperties", False):
            raise ToolError("invalid_argument", f"unknown argument(s): {', '.join(sorted(unknown))}")
        for req in schema.get("required", []):
            if req not in value:
                raise ToolError("invalid_argument", f"missing argument: {req}")
        for k, v in value.items():
            if k in props:
                _check(props[k], v, f"{path}.{k}" if path else k)
        return
    if t == "string":
        if not isinstance(value, str):
            raise ToolError("invalid_argument", f"{path} must be a string")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ToolError("invalid_argument", f"{path} is longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ToolError("invalid_argument", f"{path} has an invalid format")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolError("invalid_argument", f"{path} must be one of: {', '.join(schema['enum'])}")
        return
    if t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolError("invalid_argument", f"{path} must be an integer")
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ToolError("invalid_argument", f"{path} must be between {schema.get('minimum')} and {schema.get('maximum')}")
        return
    if t == "array":
        if not isinstance(value, list):
            raise ToolError("invalid_argument", f"{path} must be an array")
        if len(value) > schema.get("maxItems", len(value)):
            raise ToolError("invalid_argument", f"{path} has more than {schema['maxItems']} items")
        for i, item in enumerate(value):
            _check(schema.get("items", {}), item, f"{path}[{i}]")


class Registry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, kind: str, schema: dict):
        assert kind in ("read", "write")

        def deco(fn):
            self.tools[name] = Tool(name, description, kind, schema, fn)
            return fn
        return deco

    def validate(self, name: str, args: Any) -> Tool:
        if name not in self.tools:
            raise ToolError("unknown_tool", f"no such tool: {name}")
        tool = self.tools[name]
        _check(tool.schema, args, "")
        return tool

    def specs(self) -> list[dict]:
        return [t.openai_spec() for t in self.tools.values()]


# Shared argument patterns: identifiers in the synthetic ERP/QMS, dates, free text.
SITE_ID = {"type": "string", "pattern": r"H-[A-Z]", "maxLength": 3}
DATE = {"type": "string", "pattern": r"\d{4}-\d{2}-\d{2}", "maxLength": 10}
LOT_NO = {"type": "string", "pattern": r"[A-Z]{3}-[A-Z0-9]{2}-L\d{4}", "maxLength": 20}
CAPA_ID = {"type": "string", "pattern": r"CAPA-\d{4}-\d{3}", "maxLength": 13}
TEXT = {"type": "string", "maxLength": 2000}
