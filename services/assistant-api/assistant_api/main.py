"""HTTP API for Company M's assistant (FastAPI). Same backend as the demo UI.

Identity: the caller is taken from the `X-User` header, which in deployment is set by the
authenticating proxy in front of this service (and stripped from client requests there). The API
itself never accepts a user name in the request body. Unknown users get 401.

    uvicorn assistant_api.main:app --port 8080   # from services/assistant-api
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("ASSISTANT_ROOT") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(ROOT / "packages/tools"))

from agenttools.assistant import Backend  # noqa: E402

VERSION = os.environ.get("APP_VERSION", "dev")
app = FastAPI(title="Company M assistant API", version=VERSION)
STATE: dict = {}


def backend() -> Backend:
    if "backend" not in STATE:
        t0 = time.perf_counter()
        STATE["backend"] = Backend.from_env()
        STATE["load_seconds"] = round(time.perf_counter() - t0, 2)
    return STATE["backend"]


def current_user(x_user: str = Header(..., alias="X-User")) -> str:
    if x_user not in backend().users:
        raise HTTPException(401, "unknown user")
    return x_user


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    approve: bool
    acknowledge_third_party_text: bool = False


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    b = backend()
    return {"status": "ready", "version": VERSION, "mode": b.mode, "load_seconds": STATE["load_seconds"],
            "documents": b.corpus_stats}


@app.get("/version")
def version():
    return {"version": VERSION}


@app.post("/v1/ask")
def ask(body: Ask, user: str = Depends(current_user)):
    turn = backend().ask(user, body.question)
    return {"answer": turn.answer, "sources": turn.sources, "mode": turn.mode, "seconds": turn.seconds,
            "drafts": [{"draft_id": d["draft_id"], "kind": d["kind"], "status": d["status"]} for d in turn.drafts],
            "tool_calls": [{"tool": c["tool"], "ok": c["ok"], "error": c["error"], "args": c["args"]}
                           for c in turn.calls]}


@app.get("/v1/drafts/pending")
def pending(user: str = Depends(current_user)):
    return {"drafts": backend().pending_for(user)}


@app.post("/v1/drafts/{draft_id}/decision")
def decide(draft_id: str, body: Decision, user: str = Depends(current_user)):
    ok, msg = backend().decide(user, draft_id, body.approve, body.acknowledge_third_party_text)
    if not ok:
        raise HTTPException(403, msg)
    return {"message": msg}


@app.get("/v1/audit")
def audit(user: str = Depends(current_user)):
    if not any(backend().can_approve(user, k) for k in ("capa", "ticket", "notification")):
        raise HTTPException(403, "audit log is for approvers")
    return {"entries": backend().drafts.audit()[-200:]}


@app.get("/v1/dashboard")
def dashboard(user: str = Depends(current_user)):
    try:
        panels = backend().dashboard(user)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    return {"panels": [{"title": p.title, "sql": p.sql, "columns": p.columns, "rows": p.rows, "chart": p.chart}
                       for p in panels]}
