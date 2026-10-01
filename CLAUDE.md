# CLAUDE.md

## 專案目標
求職作品集專案：以醫療器材（醫材）研發法規為題材，展示「企業內部 AI Agent 應用」的端到端落地能力。
目標職缺：力旺（Forward Deployed AI Engineer）、牧德（AI 資深應用工程師）、亞光（AI 課長）、華邦（資深 AI 應用工程師）。
這些職缺共同要求：內部知識庫 RAG、Agent / Tool Use / MCP、企業系統整合、地端＋雲端模型、Evaluation、Docker/Linux、需求訪談與規格書。

## 專案定位
「醫材研發法規 Copilot」——給醫材公司 RD / RA / QA 用的內部 AI 平台。
- 不做臨床診斷、不使用真實病患資料；資料皆為公開（openFDA、FDA guidance、TFDA 公告）或虛構。
- README 必須包含「醫材 ↔ 半導體」領域對照表，並設計 `domain_packs/` 可切換產業資料。

## 目前狀態
- 規格討論階段，尚未開始實作。
- 架構草案：`docs/architecture-v0.1.md`
- 先前討論摘要（職缺分析、已確定方向）：`docs/discussion-summary.md`，新 session 請先讀
- 待決策事項列在該文件最後一節。

## 慣例
- 介面繁體中文；程式碼、commit message、README 以英文為主（待確認）。
- 規格文件採 IEC 62304 精神：PRD、SRS（需求編號如 REQ-RAG-001）、SAD + ADR、評估計畫、追溯矩陣。
