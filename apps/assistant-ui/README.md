# assistant-ui：公司 M 內部助理示範介面（Chainlit）

給面試或展示用的聊天介面，接在 `packages/tools` 的工具與守門上。可以切換身分（品保、服務、研發、法規、外部顧問、品保主管、營運主管），看到每一次工具呼叫的參數與回傳內容，以品保主管身分核准或退回草稿，查看稽核紀錄；營運主管有固定報表與 Text-to-SQL 自由提問。四個場景的示範腳本見 [`docs/demo.md`](../../docs/demo.md)。

*English summary: a Chainlit demo on top of the tools and guard. Switch personas, see every tool call with its arguments and result, approve or reject drafts as the QA manager, view the append-only audit log. Runs without a model (fixed workflow) or with any OpenAI-compatible server.*

## 執行

```bash
pip install -r apps/assistant-ui/requirements.txt ./packages/rag -e ./packages/tools
chainlit run apps/assistant-ui/app.py            # http://localhost:8000

# 接模型（例如本機 llama.cpp、vLLM、Ollama）
ASSISTANT_LLM_BASE_URL=http://localhost:8000/v1 ASSISTANT_LLM_MODEL=qwen3.8-27b-q8 \
  chainlit run apps/assistant-ui/app.py --port 8001
```

第一次啟動時會在 `data/synthetic/` 產生合成 ERP＋QMS 資料庫（不進 git）。如果 `data/raw/public/` 有下載好的公開 PDF，也會一併放進知識庫，啟動會多花約半分鐘。

## 兩種回答方式

| 方式 | 何時使用 | 行為 |
|---|---|---|
| 固定流程 | 沒有設定模型 | 依規則從問題抓出站點、CT 機型、CAPA 編號、批號、產品代碼，呼叫固定的工具，用工具結果組成回答。認不出的問題改成搜尋知識庫，直接列出原文段落。 |
| 模型 | 設定 `ASSISTANT_LLM_BASE_URL`、`ASSISTANT_LLM_MODEL` | 由模型決定呼叫哪些工具、怎麼回答（`agenttools.agent`）。 |

兩種方式都經過同一個守門，寫入都只產生草稿。兩者在同一份情境任務與注入樣本上的比較見 [`results/m2/`](../../results/m2/)。

## 示範流程

1. 以 **品保工程師（qa_lin）** 點「醫院F 的 C-320 客訴還沒連到 CAPA，請幫我起草 CAPA」。畫面列出 `list_complaints` 與 `draft_capa` 兩次呼叫，回答說明已建立草稿。
2. 切換成 **品保主管（qa_mgr_chou）**，草稿出現在「待核准」，按核准。
3. 點「稽核紀錄」，可以看到建立與核准兩筆紀錄。
4. 換成 **外部顧問（contractor_lee）** 問安裝 SOP：他只能讀公開文件，回答裡不會出現內部 SOP 的內容。

## 限制

- 身分用選單切換，只是示範；正式環境身分要來自公司帳號（例如 Keycloak），選單不能決定權限。
- 沒有登入、沒有對話紀錄保存。草稿與稽核紀錄存在 `data/synthetic/drafts.sqlite`，刪掉就重置。
- 模型模式下工具呼叫是整輪結束後一次顯示，不是即時串流。
- Text-to-SQL 只開放營運主管，查詢全部資料表；沒有依欄位或站點再細分權限。
- 報表的圖只在形狀明顯時才畫（一個標籤欄加一個數字欄，或有 month 欄），其他只顯示表格。
