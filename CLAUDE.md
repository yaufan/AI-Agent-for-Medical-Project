# CLAUDE.md

## 專案
個人作品集：虛構公司 M（肺結節 AI 輔助偵測軟體，裝在地端 GPU 推論主機）的**內部 AI Agent 平台**，展示 RAG、Agent／MCP、企業系統整合、地端＋雲端模型、評估與治理。
- 架構、場景、里程碑：`docs/architecture.md`
- 設計決策紀錄：`docs/decisions.md`（新 session 先讀）
- 公開資料來源與授權：`data/SOURCES.md`

## 規則
- 只用公開資料或合成資料。不使用任何醫院、公司或真實客戶的內部資料；合成資料一律用中性名稱（醫院A、CT廠牌A、供應商甲、GPU G1）。
- 新增公開資料前先登記到 `data/SOURCES.md`，授權未確認的不放進 repo。
- 這個 repo 是公開的：不寫入作者的個人資訊、工作經歷細節、任何真實機構的內部資訊。
- 實驗只定要量的指標，不預設結果；結果照實寫，沒做的寫「沒做」。
- 不做臨床診斷用途；README 保留「研究與學習用途，非醫療器材」聲明。

## 結構與指令
| 路徑 | 內容 | 測試 |
|---|---|---|
| `packages/lungnod/` | P1：肺結節偵測 | `python -m pytest -q packages/lungnod/tests` |
| `services/cad-service/` | P2：推論服務 | `python -m pytest -q services/cad-service/tests` |
| `packages/erpqms/` | 合成 ERP＋QMS、`scenarios.sql` | `python -m pytest -q packages/erpqms/tests` |
| `packages/rag/` | 檢索與評估 | `python -m pytest -q packages/rag/tests`（PDF 相關測試在未下載時自動略過） |
| `packages/tools/` | 工具、守門、草稿核准、MCP | `python -m pytest -q packages/tools/tests` |
| `apps/assistant-ui/` | Chainlit 示範介面（`make ui`） | `python -m pytest -q apps/assistant-ui/tests` |
| `eval/` | 題庫、使用者、評估、閘門 | `python eval/run_retrieval.py`；`python eval/check_gate.py --baseline results/m1 --candidate <dir>`；`python eval/injection/run_injection.py --fail-on-created` |

`make test` 跑全部測試；`make data` 產生合成資料到 `data/synthetic/`（不進 git）；`make eval-m1` 下載公開 PDF 到 `data/raw/`（不進 git）並跑 M1 評估。

題庫或檢索程式修改後：跑 `python eval/run_retrieval.py`、`python eval/run_retrieval.py --corpus internal`、`python eval/report.py`，再一起提交 `results/m1/`（含 `internal/`），否則 CI 閘門會拿舊基準比較。

CI 的 GitHub 主機常被 FDA 網站擋下載：內部語料的閘門每次都跑；完整語料的檢查只在下載成功時跑，失敗時顯示警告。

## 環境
- 雲端環境：沒有 GPU、連不到 Hugging Face；PostgreSQL 16 已安裝；openFDA、ClinicalTrials.gov、FDA 網站可連線。
- 模型下載與 GPU 實驗在使用者本機 gx10-01 做（GB10，CPU 與 GPU 共用記憶體，機器上還有其他工作）：一次只載入一個模型、可用記憶體低於 16 GB 就暫停、不碰不是自己啟動的程序。gx10-01 用 repo 專用的部署金鑰推送（`~/.ssh/ai_agent_medical`，需搭配 `-F /dev/null`）。
- 慣例：介面與文件繁體中文、附英文摘要；程式碼與 commit message 英文。
