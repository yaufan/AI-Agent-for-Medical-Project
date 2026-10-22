"""Expose the tools over MCP (stdio), so any MCP client — Claude Code, an IDE, the M4 demo UI — can use them.

    python -m agenttools.mcp_server --user qa_lin --erpqms data/synthetic/erpqms/erpqms.sqlite

The user is fixed when the server starts (in production: from the client's authenticated identity),
so a model cannot claim to be someone else. Every call goes through the same schema checks as the
agent loop.

Write tools are NOT listed unless the server starts with `--allow-writes`. Over MCP the server only
sees what the model sends, so it cannot check the user's own words the way the agent loop's intent
gate does (any "request" field would be written by the model itself). With `--allow-writes`, write
tools still only create drafts, and the MCP client is expected to ask the user before each call.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def build(user: str, erpqms: Path, drafts_path: Path, with_kb: bool):
    sys.path.insert(0, str(ROOT / "packages/rag"))
    from rag.acl import GroupStore

    from .core import Session
    from .drafts import DraftStore
    from .guard import Guard
    from .tools import Context, build_registry

    store = GroupStore.from_json(ROOT / "eval/users.json")
    retriever = None
    if with_kb:
        from rag.chunking import chunk_corpus
        from rag.documents import load_corpus
        from rag.retriever import Retriever
        docs, _ = load_corpus(ROOT / "data/corpus", ROOT / "data/raw/public")
        retriever = Retriever(chunk_corpus(docs, "structured"))
    ctx = Context(erpqms, DraftStore(drafts_path), retriever)
    registry = build_registry(ctx)
    # intent gate off: over MCP the model would supply the request text itself (see module docstring)
    return registry, Guard(registry, intent_gate=False), lambda: Session(user, store.groups(user))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--erpqms", type=Path, default=ROOT / "data/synthetic/erpqms/erpqms.sqlite")
    ap.add_argument("--drafts", type=Path, default=ROOT / "data/synthetic/drafts.sqlite")
    ap.add_argument("--no-kb", action="store_true")
    ap.add_argument("--allow-writes", action="store_true", help="list draft_* tools (still drafts only)")
    args = ap.parse_args()

    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    registry, guard, new_session = build(args.user, args.erpqms, args.drafts, not args.no_kb)
    server = Server("company-m-tools")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=t.name, description=f"[{t.kind}] {t.description}", inputSchema=t.schema)
                for t in registry.tools.values() if t.kind == "read" or args.allow_writes]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        from .guard import to_model_message
        tool = registry.tools.get(name)
        if tool is not None and tool.kind == "write" and not args.allow_writes:
            result = {"error": {"code": "unknown_tool", "message": f"no such tool: {name}"}}
        else:
            result = guard.call(new_session(), name, dict(arguments or {}))
        return [types.TextContent(type="text", text=to_model_message(result))]

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
