# agenttools：工具、守門、人工核准、agent 迴圈與 MCP

公司 M 助理可以呼叫的工具，以及讓工具「不會被資料裡的指令帶著走」的那一層。實驗結果在 [`results/m2/`](../../results/m2/)。

*English summary: read tools (parameterised ERP/QMS queries on a read-only connection, ACL-bound knowledge-base search, openFDA and ClinicalTrials.gov), write tools that only create drafts a named person must approve, a guard every call passes through, a minimal OpenAI-compatible agent loop, and an MCP stdio server.*

## 模組

| 檔案 | 內容 |
|---|---|
| `core.py` | `Session`（使用者、群組、本回合請求、trace）、`Registry`、JSON schema 參數檢查（型別、enum、pattern、長度、未知欄位） |
| `tools.py` | 讀取工具：`list_complaints`、`get_capa`、`site_overview`、`sites_with_scanner_model`、`software_release`、`trace_part_lot`、`search_knowledge_base`、`search_510k`、`device_recalls`、`search_clinical_trials`；寫入工具：`draft_capa`、`draft_ticket`、`draft_notification` |
| `drafts.py` | 草稿與核准：依草稿種類限定核准角色、申請人不能核准自己的草稿、含第三方文字的草稿需明確確認；稽核紀錄只能新增（SQLite trigger 擋 UPDATE／DELETE） |
| `guard.py` | 每個呼叫都先經過：參數檢查 → 寫入意圖（使用者本回合的話）→ 收件站點須是使用者提到的 → 每回合最多一個寫入 → 標記從第三方文字複製來的欄位；工具結果裡的第三方文字以 `<untrusted_data>` 包起來 |
| `agent.py` | 小型 tool-calling 迴圈，接任何 OpenAI 相容端點（Ollama、vLLM、雲端） |
| `mcp_server.py` | MCP stdio 伺服器；使用者在啟動時固定；寫入工具預設不列出，`--allow-writes` 才開 |
| `testing.py` | 測試用替身：`ScriptedLLM`、`CompliantAttackerLLM`（照做所有植入指令的最壞情況模型） |

## 設計重點

- **ERP／QMS 只用參數化查詢**，連線以 `mode=ro` 開啟；模型不能寫 SQL。
- **寫入只產生草稿**。核准不是工具，模型呼叫不到；由核准介面代表具名人員執行並寫入稽核紀錄。
- **寫入意圖只看使用者自己的話**（`session.request`），工具回傳的資料再怎麼寫都滿足不了這個條件。
- **MCP 模式關掉意圖檢查、改成預設不提供寫入工具**：MCP 伺服器只看得到模型送來的內容，「使用者說了什麼」也是模型寫的，檢查沒有意義。開啟 `--allow-writes` 時，靠 MCP 用戶端在每次呼叫前詢問使用者。

## 已知限制

- 寫入意圖用關鍵字判斷：「不要通知」也含「通知」；使用者要求 CAPA 時，資料裡同類的植入指令仍可通過（只靠第三方文字標記與人工核准擋下）。
- 第三方文字標記比對的是整段字串，少於 4 字或改寫過的內容不會被標記。
- 站點檢查只認「醫院X」這種寫法；請求沒提到任何站點時不檢查。

## 使用

```bash
pip install -e "./packages/tools[test]" ./packages/rag   # -e：MCP 伺服器從 repo 讀題庫使用者與語料
python -m pytest -q packages/tools/tests

# MCP（例如給 Claude Code 用）；先 make data 產生合成資料庫
cd packages/tools && python -m agenttools.mcp_server --user qa_lin --erpqms ../../data/synthetic/erpqms/erpqms.sqlite
```
