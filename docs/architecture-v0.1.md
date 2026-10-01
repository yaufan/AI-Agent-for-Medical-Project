# 醫材研發法規 Copilot：架構與規格草案 v0.1

## 1. 系統定位
| 項目 | 內容 |
|---|---|
| 一句話描述 | 給醫材公司研發、法規、品保人員用的內部 AI 平台：法規知識問答、上市前法規研究、客訴分析與 CAPA 流程 |
| 使用者 | RD、RA、QA、系統管理員 |
| 不做的事 | 臨床診斷、真實病患資料、取代人做法規決策 |

## 2. 系統架構
```
前端  Next.js + shadcn/ui
  問答 │ 法規研究任務 │ 審核中心 │ 客訴儀表板 │ 會議紀錄 │ 管理後台
        │ REST + SSE
後端  FastAPI：身分驗證(Keycloak OIDC)、角色權限、稽核紀錄、背景任務佇列
        │
  ├─ Agent 編排 LangGraph：問答流程、法規研究多 Agent、人工核准中斷/續行
  ├─ 文件匯入管線：Docling 解析 → 表格/圖片處理 → 結構化切塊 → 權限中繼資料 → 向量化 → 索引
  ├─ 工具層 MCP servers：知識庫檢索、openFDA、客訴資料庫(唯讀 SQL)、工單、通知
  └─ 模型閘道 LiteLLM：雲端 API（公開/內部）＋地端 vLLM/Ollama Qwen（機密）
       另：bge-m3 embedding、bge-reranker-v2-m3、Whisper
資料層：PostgreSQL + pgvector、MinIO、Redis
可觀測性：Langfuse；評估程序於 CI 執行
部署：Docker Compose 一鍵啟動
```

## 3. 關鍵技術決策
| 決策 | 選擇 | 理由 | 替代方案 |
|---|---|---|---|
| Agent 框架 | LangGraph | 狀態保存、人工核准中斷續行 | Semantic Kernel、AutoGen |
| 工具整合 | MCP | 業界標準、工具可重用 | 直接 function calling |
| 模型閘道 | LiteLLM | 雲端/地端統一介面、集中路由與成本 | 自寫轉接層 |
| 向量資料庫 | pgvector | 與應用資料同庫，權限過濾可用 SQL | Qdrant、Milvus |
| 文件解析 | Docling | PDF 表格與版面；圖表交 vision 模型 | Unstructured、MinerU |
| 檢索 | BM25 + 向量混合，再 rerank | 法規專有名詞與條號 | 純向量 |
| Embedding / Rerank | bge-m3 / bge-reranker-v2-m3 | 中英皆可、可地端 | 雲端 API |

## 4. 核心資料流
- **文件匯入**：上傳 → MinIO → 背景解析 → 表格結構化、圖片描述 → 依章節切塊 → 附中繼資料（來源、頁碼、部門、機密等級）→ 向量＋關鍵字索引 → 前端顯示狀態。
- **知識庫問答**：提問 → 權限檢查 → 混合檢索（檢索階段即依權限過濾）→ rerank → 依機密等級選模型 → 串流回答附引用 → 點引用開啟 PDF 原文反白 → 稽核紀錄＋Langfuse。
- **法規研究任務**：表單 → 研究 Agent（知識庫＋openFDA）→ 風險 Agent（不良事件、回收、客訴）→ 撰寫 Agent → 審查 Agent（引用檢查，最多退回 2 次）→ 報告草稿；寫入動作暫停送審核中心，核准後續行。

## 5. 安全與治理
- 文件分級：公開 / 內部 / 機密；上下文含機密或偵測到個資（Presidio）→ 強制地端模型。
- 權限：角色＋部門，細到文件段落。
- 工具分唯讀 / 寫入；寫入一律人工核准；SQL 帳號唯讀。
- 稽核紀錄只增不改。
- 防提示詞注入：檢索內容視為資料；工具參數格式驗證。

## 6. 主要資料表
使用者/角色、文件、文件段落、對話、訊息、引用、任務、任務步驟、核准請求、稽核紀錄、回饋、評估紀錄、客訴、CAPA、工單。

## 7. 非功能需求（初稿）
| 項目 | 目標 |
|---|---|
| 問答首字時間 P95 | < 3 秒 |
| 法規研究任務 | < 5 分鐘 |
| Recall@5 | ≥ 85% |
| 引用正確率 | ≥ 90% |
| 資料庫外問題正確拒答 | ≥ 80% |
| 稽核紀錄完整率 | 100% |
| 部署 | `docker compose up`，有 GPU / 無 GPU 兩種模式 |

## 8. 規格文件清單
PRD、SRS（REQ-xxx 編號）、SAD + ADR、評估計畫、追溯矩陣（需求 → 程式碼 → 測試 → 評估題目）。

## 9. Repo 結構（規劃）
```
apps/web/          Next.js 前端
apps/api/          FastAPI 後端
services/agents/   LangGraph 流程
services/ingest/   文件匯入管線
mcp/               openfda、kb、complaints、ticket MCP servers
eval/              評估集、評估程序、報告
domain_packs/      meddev/、semiconductor/
infra/             docker-compose、Keycloak、LiteLLM 設定
docs/              PRD、SRS、SAD、ADR、評估計畫
```

## 10. 待決策事項
1. 硬體：是否有 NVIDIA GPU、VRAM 大小（決定 vLLM 或 Ollama）。
2. 雲端模型供應商與每月預算。
3. MVP 範圍：文件匯入、問答、法規研究任務、審核中心、評估；會議紀錄、客訴儀表板、Coding Agent 放第二版？
4. 語言：介面繁中、程式碼與 README 英文？
5. 文件迭代方式：持續在 `docs/` 中更新。
