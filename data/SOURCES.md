# 資料來源與授權

每一筆公開資料在放進知識庫或工具之前，都要在這裡登記來源、授權與確認狀態。**狀態不是「已確認」的資料，不放進 repo。**

最後更新：2026-10-21（M1）

## 公開資料

| 資料 | 用途 | 取得方式 | 授權／使用條件 | 狀態 |
|---|---|---|---|---|
| LIDC-IDRI 胸腔 CT（含 4 位放射科醫師的結節標註） | `packages/lungnod`、`services/cad-service` 的影像資料 | NCI Imaging Data Commons（`idc-index`，Google Cloud／AWS 公開 bucket） | CC BY 3.0（TCIA） | 已確認（P1 已使用）；影像不放進 repo，由腳本下載 |
| FDA 網站內容（guidance 6 份，見 `data/corpus/public_manifest.json`） | 知識庫：CADe、AI 軟體變更管制、軟體送審 | www.fda.gov | FDA 網站政策：「除另有註明外，FDA 網站內容不受著作權保護，屬於公有領域，可自由轉載與使用」；標示來源為佳但非必要。**頁面中標示為第三方著作的內容除外** | 已確認（2026-10-21 讀取網站政策頁） |
| 510(k) 決定文件與摘要 PDF（10 份，產品代碼 OEB，2020 年以後） | 知識庫：同類產品的適應症、性能與比較表 | www.accessdata.fda.gov，清單見 `data/corpus/public_manifest.json` | FDA 公開的文件；摘要由申請廠商撰寫，著作權狀態未逐份確認 | 已使用於檢索實驗；**不放進 repo**，由 `scripts/fetch_public_corpus.py` 下載；解析時遮蔽聯絡人 email 與電話 |
| openFDA：510(k)、產品分類、不良事件、回收 | MCP 工具（即時查詢）；M1 用來挑選 510(k) 清單 | api.fda.gov | 依 openFDA 使用條款（條款頁在 open.fda.gov，這個環境尚未開放該網域） | 待確認 |
| ClinicalTrials.gov API v2 | MCP 工具（即時查詢） | clinicaltrials.gov/api/v2 | 依 ClinicalTrials.gov 使用條款（條款頁為動態載入，這個環境讀不到內容） | 待確認：請在瀏覽器打開 clinicaltrials.gov 的 Terms and Conditions 頁面確認 |
| TFDA 公告與指引 | 知識庫：中文法規（跨語題型） | www.fda.gov.tw | 要確認是否適用「政府資料開放授權條款」 | 待確認 |
| GPU／SSD datasheet | 場景 3：替代料比較 | 各廠商網站 | 每份不同，多數不允許轉載 | 待確認；不確定的只放連結與摘要，不放全文 |

## 模型

| 模型 | 用途 | 來源 | 授權（依模型頁面標示，使用前再確認） |
|---|---|---|---|
| bge-m3 | 向量檢索 | Ollama `bge-m3`（原始模型 BAAI/bge-m3） | MIT |
| bge-reranker-v2-m3 | 重排序 | Hugging Face `BAAI/bge-reranker-v2-m3` | Apache-2.0 |
| Qwen3.8-27B（GGUF Q8_0） | M2／M4 地端對話模型；M3 比較 A | 本機既有的 llama.cpp 容器（GGUF，`ggml-org` 轉檔） | 待確認：M3 在本機從模型頁面確認後填入 |
| Qwen3.8-27B（GGUF Q4） | M3 比較 B：量化影響 | Hugging Face（GGUF 轉檔，下載前確認來源與授權） | 待確認：下載前確認 |
| Qwen3-8B | M3 比較 C：小模型、分級路由的地端端 | Ollama `qwen3:8b`／Hugging Face `Qwen/Qwen3-8B` | Apache-2.0（下載前再確認模型頁面） |
| Claude Opus 5.5（`claude-opus-5-5`） | M3 雲端模型（Anthropic API） | Anthropic API | 商用 API，依 Anthropic 服務條款；只送公開與內部等級的資料（見 `agenttools/gateway.py`） |

模型檔不放進 repo；版本與 digest 記在 `results/m1/env-gx10-01.md`。

## 不放進知識庫的資料

| 資料 | 原因 | 處理方式 |
|---|---|---|
| Lung-RADS（ACR） | 學會著作 | 只在文件中引用出處，不收錄全文 |
| Fleischner Society 指引 | 期刊論文 | 同上 |
| 任何醫院或公司的內部資料 | 不屬於公開資料 | 一律不用 |

## 合成資料

| 資料 | 產生方式 | 說明 |
|---|---|---|
| 公司 M 的 ERP＋QMS | `packages/erpqms`，固定種子 | 全部虛構，名稱中性；產生的檔案不進 repo（見 `.gitignore`），需要時重新產生 |
| 公司 M 的內部文件（12 份 Markdown） | `data/corpus/internal`、`proj-a`、`proj-b` | 全部虛構；零件與產品規格都是合成數值 |
| 題庫（89 題）與使用者 | `eval/questions.jsonl`、`eval/users.json` | 由 Claude 起草，尚未人工審查 |

## 已確認可以連線的網域（雲端開發環境）

2026-10-21 測試：clinicaltrials.gov、api.fda.gov、www.fda.gov、www.accessdata.fda.gov、www.fda.gov.tw 可以連線；Hugging Face 不行，嵌入與重排序模型要在本機下載。
