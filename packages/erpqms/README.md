# erpqms：虛構公司 M 的合成 ERP＋QMS 資料庫

公司 M 賣「肺結節 AI 輔助偵測軟體」，軟體裝在公司提供的地端 GPU 推論主機上。這個套件產生公司 M 的內部資料：誰買了什麼、裝了哪些零件、跑哪個版本、出過哪些問題、怎麼處理。之後的 MCP 工具、Text-to-SQL 和 Agent 都查這一份資料。

> **全部是虛構資料。** 醫院、CT 廠牌、供應商、零件一律用中性名稱（醫院A、CT廠牌A、供應商甲、GPU G1），不對應任何真實機構或產品。

## 產生

```bash
cd packages/erpqms
python -m erpqms.generate --out ../../data/synthetic/erpqms   # 只用標準函式庫
python -m pytest -q tests                                     # 9 項測試
```

輸出 `erpqms.sqlite` 和每張表一個 CSV。種子固定（`SEED = 20261021`），每次產生的內容完全相同。資料的基準日是 **2026-09-30**。

載入 PostgreSQL：

```bash
./scripts/load_postgres.sh ../../data/synthetic/erpqms/csv -h localhost -U postgres -d erpqms
python scripts/check_postgres.py --dsn "host=localhost user=postgres dbname=erpqms"   # 每個查詢在 SQLite 與 Postgres 結果必須相同
```

## 資料表

```
ERP                                                   QMS
sites ─┬─ ct_scanners                                  complaints ──▶ capas
       ├─ licenses                                       │  （site、scanner、serial、version）
       ├─ monthly_usage（每月檢查量、QC 拒收率、每例標示數）   change_requests ──▶ parts / releases / capas
       └─ appliances ─┬─ deployments ──▶ software_releases
                      └─ appliance_parts ──▶ part_lots ──▶ parts ──▶ suppliers
                 sku_bom（NA-100、NA-200 的組成）
```

| 規模 | 數量 |
|---|---|
| 醫院 | 12 |
| CT 掃描儀 | 22 |
| 推論主機 | 21（105 筆零件批號紀錄） |
| 軟體版本 | 4（2.0 送審中，尚未部署） |
| 每月使用紀錄 | 261 |
| 客訴 | 157 |
| CAPA | 13 |
| 設計變更申請 | 3 |

## 刻意埋進去的三條故事線

背景資料是隨機產生的；下面三條故事是刻意放的，讓 Agent 場景有**可以驗證的標準答案**。對應的 SQL 在 [`scenarios.sql`](scenarios.sql)，測試會檢查答案是否成立。

| 故事 | 發生了什麼 | 要查出來的答案 |
|---|---|---|
| **S1 新 CT 超出規格** | 醫院B 2026-06 裝了新機型 C-320，預設重建切片 3.0 mm，超過軟體的 2.5 mm 輸入規格；QC 拒收率和每例標示數同時跳升。CAPA-2026-007 處理中，已逾期 | 醫院F 2026-08 也裝了 C-320，已有 2 件客訴，**還沒有人把它連到 CAPA** |
| **S2 SSD 批號早期失效** | SSD 批號 SSD-S1-L2508 有 4 台主機故障，CAPA-2026-004 調查中 | 同一批號還裝在**醫院D、醫院J** 的主機上，尚未故障 |
| **S3 GPU 停產** | 供應商甲通知 GPU G1 停產，ECR-2026-009 還是草稿 | 哪些站點、幾台主機受影響；最後採購日 2027-02-26 |

另外還有：醫院E、醫院G 一直停在 1.1 版；4 張 CAPA 已逾期。

## 一個刻意保留的陷阱

客訴的 `category = 'hardware_failure'` 也包含風扇異音、電源重開機。如果直接用這個類別算「每個 SSD 批號的故障率」，只裝在 1 台主機上的批號 L2501 會因為一件電源客訴變成 100%，排在第一名。正確做法是用 `suspected_component = 'SSD'` 過濾，再除以裝了該批號的主機數。這正好是評估 Text-to-SQL 時要測的情境：**查詢能執行、數字看起來合理，結論卻是錯的。**
