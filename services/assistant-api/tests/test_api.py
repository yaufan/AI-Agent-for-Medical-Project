"""The API over the shared backend: identity from the proxy header, approvals, permissions."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/assistant-api"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ASSISTANT_PUBLIC_PDFS", "0")
    monkeypatch.delenv("ASSISTANT_LLM_BASE_URL", raising=False)
    from fastapi.testclient import TestClient

    from assistant_api import main
    main.STATE.clear()
    return TestClient(main.app)


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz").json()
    assert r["status"] == "ready" and r["mode"].startswith("固定流程") and r["documents"]["markdown_docs"] > 0


def test_identity_comes_from_the_proxy_header(client):
    assert client.post("/v1/ask", json={"question": "哪些醫院有 C-320 這款 CT？"}).status_code == 422
    assert client.post("/v1/ask", json={"question": "x"}, headers={"X-User": "mallory"}).status_code == 401
    r = client.post("/v1/ask", json={"question": "哪些醫院有 C-320 這款 CT？"}, headers={"X-User": "qa_lin"}).json()
    assert "醫院B" in r["answer"] and r["tool_calls"][0]["tool"] == "sites_with_scanner_model"


def test_draft_approval_flow_and_audit(client):
    r = client.post("/v1/ask", json={"question": "醫院F 的 C-320 客訴還沒連到 CAPA，請幫我起草 CAPA，關聯這些客訴"},
                    headers={"X-User": "qa_lin"}).json()
    draft_id = r["drafts"][0]["draft_id"]
    assert client.post(f"/v1/drafts/{draft_id}/decision", json={"approve": True},
                       headers={"X-User": "qa_lin"}).status_code == 403          # requester / wrong role
    assert client.get("/v1/audit", headers={"X-User": "qa_lin"}).status_code == 403
    mgr = {"X-User": "qa_mgr_chou"}
    assert [d["draft_id"] for d in client.get("/v1/drafts/pending", headers=mgr).json()["drafts"]] == [draft_id]
    assert client.post(f"/v1/drafts/{draft_id}/decision", json={"approve": True}, headers=mgr).status_code == 200
    actions = [e["action"] for e in client.get("/v1/audit", headers=mgr).json()["entries"]]
    assert actions == ["draft_created", "draft_approved"]


def test_dashboard_is_for_operations_managers(client):
    assert client.get("/v1/dashboard", headers={"X-User": "qa_lin"}).status_code == 403
    panels = client.get("/v1/dashboard", headers={"X-User": "ops_mgr_tsai"}).json()["panels"]
    assert len(panels) == 6 and all("sql" in p for p in panels)
