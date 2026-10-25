# assistant-api：公司 M 助理的 HTTP API

和示範介面共用同一個後端（`packages/tools/agenttools/assistant.py`），把它包成服務：提問、草稿核准、稽核紀錄、營運報表。附 Docker 映像、Kubernetes 設定，以及在 kind 上量部署、更新、回滾秒數的腳本。

*English summary: FastAPI service over the same backend as the demo UI. Identity comes from the `X-User` header set by the authenticating proxy. Ships with a non-root, read-only-root-filesystem image, Kubernetes manifests, and a script that times deploy, update and rollback on kind (run in CI).*

## 端點

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/healthz`、`/readyz`、`/version` | 存活、就緒（含回答方式與載入文件數）、版本 |
| POST | `/v1/ask` | `{"question": ...}`，回傳回答、出處、工具呼叫、建立的草稿 |
| GET | `/v1/drafts/pending` | 這個人可以核准的草稿 |
| POST | `/v1/drafts/{id}/decision` | `{"approve": true, "acknowledge_third_party_text": false}`；角色不符或申請人自己核准會回 403 |
| GET | `/v1/audit` | 稽核紀錄（核准者才能看） |
| GET | `/v1/dashboard` | 營運報表（營運主管） |

**身分**：從 `X-User` 標頭取得。部署時這個標頭由前面的登入代理（例如接 Keycloak 的 oauth2-proxy）設定，並清掉用戶端自己帶的同名標頭。API 不接受請求內容裡的使用者名稱。

## 執行

```bash
pip install -r services/assistant-api/requirements.txt ./packages/rag -e ./packages/tools
cd services/assistant-api && uvicorn assistant_api.main:app --port 8080
curl -s localhost:8080/v1/ask -H 'X-User: qa_lin' -H 'Content-Type: application/json' -d '{"question":"哪些醫院有 C-320 這款 CT？"}'
```

環境變數：

| 變數 | 用途 |
|---|---|
| `ASSISTANT_DATA_DIR` | SQLite 的位置（合成 ERP＋QMS、草稿與稽核） |
| `ASSISTANT_LLM_BASE_URL`、`ASSISTANT_LLM_MODEL` | 地端模型；不設就用固定流程 |
| `ASSISTANT_PUBLIC_PDFS` | 設為 `0` 時不載入公開 PDF |

## 部署

```bash
docker build -f services/assistant-api/deploy/Dockerfile --build-arg APP_VERSION=0.1.0 -t assistant-api:0.1.0 .
kubectl apply -f services/assistant-api/deploy/k8s/
```

- 容器不用 root 執行，根檔案系統唯讀，只有 `/data` 和 `/tmp` 可以寫。
- 草稿和稽核紀錄存在 SQLite，所以只能跑一個副本。要水平擴充，得先把它們搬到 PostgreSQL。
- `deploy/kind-timing.sh` 在 kind 上做三件事並各自計時：部署 0.1.0 → 更新到 0.2.0 → 回滾。CI 的 `assistant-api` job 每次都跑，秒數寫在 job summary。

## 限制

- 沒有登入，身分完全交給前面的代理；直接對外開放這個服務，就等於任何人都能冒用身分。
- 示範設定的資料放在 `emptyDir`，Pod 重啟後草稿會消失。
- 沒有串流回應；接地端模型時，一個問題可能要幾分鐘（見 `results/m2/`）。
