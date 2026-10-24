# M4 結果：Text-to-SQL

*English summary: 19 manager questions with gold SQL (8 from `packages/erpqms/scenarios.sql`, 11 new). Qwen3.8-27B (Q8_0, llama.cpp on the local GB10, reasoning on) matched the gold result on 11 of 19 under the automatic rule. Reading the 8 misses by hand: 6 return the right rows with different columns (site name instead of site id, or fewer context columns than the gold query), and 2 return the right numbers plus extra rows (SSD lots that were never installed; future months with zero complaints). None of the 19 queries was refused by the SQL checks. Median 155 s per question, up to 27 min when the model reasoned for 7,600 tokens. The automatic rule is too strict for questions that do not say which columns to return; that is a flaw of this question bank, recorded rather than fixed after seeing the results.*

## 做了什麼

- 題庫 `eval/text2sql/questions.jsonl`：19 題主管會問的問題。
  - 8 題來自 `packages/erpqms/scenarios.sql`，問題改寫成中文。
  - 11 題是為儀表板新寫的。
  - 每題附標準 SQL。
- 評估 `eval/text2sql/run_text2sql.py`：模型寫出的 SQL 經過和介面相同的檢查後執行，再和標準 SQL 的結果比對。
  - 比對時不看列的順序、欄的順序、欄名；預測多出來的欄位也不算錯。
  - 但標準答案的**每一欄**都必須在預測結果裡找到。
- 模型：Qwen3.8-27B（Q8_0，llama.cpp，溫度 0，有思考階段），每題呼叫一次模型。環境與等待經過見 [`env-gx10-01.md`](env-gx10-01.md)。
- 標準答案自我檢查（`--model gold`）：19/19，CI 每次都跑。

## 結果（`text2sql-qwen3.8-27b-q8.json`）

| 項目 | 數字 |
|---|---|
| 自動比對相符 | **11 / 19**（0.579） |
| 被 SQL 檢查拒絕 | 0 |
| 錯誤或逾時 | 0 |
| 每題秒數 | 26–1,622 秒，中位數約 155 秒；合計 6,646 秒 |
| 每題輸出 token | 125–7,647（包含思考階段） |

### 8 題不相符，逐題看過

| 題目 | 模型的結果 | 判斷 |
|---|---|---|
| `s1_new_ct_complaints` C-320 站點與客訴數 | 醫院B 6 件（6 件已連 CAPA）、醫院F 2 件（0 件） | 數字正確；少了標準答案附帶的 CT 編號、安裝日、切片厚度 |
| `s1_out_of_spec_scanners` 超出規格的 CT | CT-021（醫院B）、CT-022（醫院F），3.0 > 2.5 | 正確；少了機型欄，多了版本欄 |
| `s2_bad_lot_trace` 批號 L2508 的主機 | 6 台，4 台有 SSD 故障，NA-250015、NA-250018 沒有 | 正確；用站點名稱而不是站點代碼，少了出廠日 |
| `s3_eol_gpu_exposure` 停產零件的站點曝險 | 11 個站點，台數都和標準答案相同 | 正確；沒有列零件編號和最後採購日（目前只有一個停產零件，所以數字相同） |
| `s4_current_versions` 每台主機的版本 | 21 台，版本都正確 | 正確；用站點名稱，少了部署日 |
| `m03` 拒收率超過 5% 的站點 | 醫院B 0.1272、醫院F 0.0681 | 正確；用站點名稱而不是代碼 |
| `s2_failure_rate_by_lot` 各 SSD 批號的故障比例 | 有裝機的 5 個批號數字都對，另外多列 6 個沒裝在任何主機上的批號（0 台） | 數字對，多了列；「每個批號」要不要包含沒用過的批號，題目沒講清楚 |
| `m08` 2026 每月客訴數 | 1–9 月都對，另外多列 10–12 月為 0 | 數字對，多了列；資料日期是 2026-09-30，把未來月份列成 0 件容易誤導 |

- 6 題答對了問題，只是回傳的欄位和標準答案不同。
- 2 題數字對，但多列出了標準答案沒有的列。
- 逐題看下來，沒有一題算錯數字或用錯條件。例如 SSD 故障都有用 `suspected_component = 'SSD'` 過濾；目前版本都有取最新一筆部署紀錄。

### 這代表什麼

- **自動比對的規則太嚴**：題目沒有講要回傳哪些欄位，標準答案卻帶了額外的背景欄位，結果多數「錯」其實是欄位選擇不同。這是題庫設計的問題。
- 這裡**沒有**看完結果再去改題目或比對規則。下一版題庫的修法：每題寫明要回傳的欄位，例如「列出站點代碼、件數」，或在題目裡標出關鍵欄位，再重跑。
- 對主管儀表板的意義：畫面會同時顯示 SQL 和結果，欄位不同不影響閱讀。但 `m08` 這種把未來月份列成 0 的寫法，只有看得懂 SQL 或資料日期的人才會發現。
- 速度：有思考階段時，難題要想很久，最長一題 27 分鐘。`--no-think` 模式還沒跑，沒有對照數字。

## 已知限制

- 題目是自己寫的，偏向這份合成資料庫的用語，沒有測拼錯字、口語或模糊的問題。
- 只跑一個模型、一次、溫度 0，沒有量變異。
- 結果比對只看結果：寫法不同但剛好得到相同結果的 SQL 會算對；資料剛好讓錯誤條件得到相同結果的 SQL 也會算對。例如 `s3` 目前只有一個停產零件，按站點或按零件加站點分組，數字相同。
- 逐題判斷是人工看的（上表），沒有第二個人複核。

## 沒做

- `--no-think` 模式的對照。
- 題庫改版（每題寫明要回傳的欄位）後重跑。
