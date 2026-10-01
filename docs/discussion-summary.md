# 討論紀錄摘要（雲端 session → 本機接續用）

## 背景
- 求職者：長庚醫學科技研發副課長，台科大電子博士；專長醫療影像深度學習（分類/分割/關鍵點）、TFDA/QMS（ISO 13485、IEC 62304、ISO 14971、ISO 27001 主導稽核員）。
- 已有生成式 AI 實績：院內 AI 推論平台維運，支援「住院小助手」「門診小助手」→ 履歷需獨立成專案並量化（使用人數、架構、上線時間），以符合「1 年以上 LLM 落地」要求。

## 目標職缺分析
| 公司 | 職缺 | 適配度 | 重點 |
|---|---|---|---|
| 亞光 | AI 課長 | 最高 | 團隊管理、產品 AI 化、Edge AI、專家系統、技術選型 |
| 牧德 | AI 資深應用工程師 | 高 | RAG/ETL、Dify/n8n、Docker、MS SQL、Whisper、規格書；需 1 年 LLM 落地經驗 |
| 力旺 | Forward Deployed AI Engineer | 高 | 需求訪談→PoC→Production、知識庫、系統整合、雲端/地端依敏感度選擇、Evaluation |
| 華邦 | 資深 AI 應用工程師 | 挑戰 | 8 年、英文精通、Multi-Agent、MCP、LangGraph、Coding Agent、Benchmark/Harness |

## 已確定方向
1. 使用者偏好醫療題材 → 選「醫材研發法規 Copilot」（使用者為 RD/RA/QA，非醫護），避免診斷聊天機器人與純影像模型。
2. 故事線：以自身國家新創獎作品「AI 骨質疏鬆 X 光篩檢軟體」規劃上市法規路徑。
3. 公開資料：openFDA（510(k)、MAUDE 不良事件、回收）、FDA guidance、TFDA 公告；客訴/CAPA 為虛構資料。
4. 模組：A 文件 RAG（表格/圖表解析）、B Multi-Agent + MCP、C 依機密等級切換地端/雲端模型、D 評估與可觀測性、E Whisper 會議紀錄 + n8n、F IEC 62304 追溯 Coding Agent（選做，衝華邦）。
5. 必做「醫材 ↔ 半導體」領域對照表 + domain pack 切換示範（換成 Flash datasheet 也能用）。
6. 前端：PoC 用 Chainlit；正式版 Next.js + shadcn/ui + FastAPI(SSE)；Keycloak SSO、角色權限。
   MVP 頁面：知識庫問答（引用可點開 PDF 反白、地端/雲端標示、回饋）、法規研究任務（Agent 步驟即時顯示）、審核中心、文件管理、營運監控。
   第二版：工作台、客訴與 CAPA 儀表板（Text-to-SQL）、會議紀錄、稽核紀錄、設定（domain pack）。
7. 過程文件：使用者訪談、規格書、技術選型報告（LangGraph/Dify/n8n/Semantic Kernel）、UAT 檢核表；文件採 IEC 62304 架構。

## 時程（6 週）
1–2 週 RAG + 評估 + Chainlit PoC → 3 週 Agent + MCP → 4 週 FastAPI + Next.js 問答/任務頁 → 5 週 審核中心、文件管理、權限、地端模型 → 6 週 營運監控、會議紀錄、使用者回饋、Demo。

## 下一步
回答 `docs/architecture-v0.1.md` 第 10 節待決策事項（GPU、雲端模型預算、MVP 範圍、語言、文件迭代方式）。
