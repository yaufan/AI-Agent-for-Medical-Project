# M4 結果：Text-to-SQL

*English summary: 19 manager questions with gold SQL (8 from `packages/erpqms/scenarios.sql`, 11 new). Execution match ignores row order, column order, column names and extra columns. The gold sanity run matches 19/19; model runs are pending.*

## 做了什麼

- 題庫 `eval/text2sql/questions.jsonl`：19 題主管會問的問題。
  - 8 題來自 `packages/erpqms/scenarios.sql`，問題改寫成中文。
  - 11 題是為儀表板新寫的。
  - 每題附標準 SQL。
- 評估 `eval/text2sql/run_text2sql.py`：模型寫出的 SQL 經過和介面相同的檢查之後執行，再和標準 SQL 的結果比對。
  - 比對時不看列的順序、欄的順序、欄名，多出來的欄位也不算錯。
  - 被檢查拒絕的查詢算錯。
- 標準答案自我檢查（`--model gold`）：19/19，CI 每次都跑。

## 結果

沒做：真實模型還沒跑。要在本機 gx10-01 用 Qwen3.8-27B 跑，結果會放在 `text2sql-<model>.json`。

## 已知限制

- 題目是自己寫的，偏向這份合成資料庫的用語，沒有測拼錯字、口語或模糊的問題。
- 比對只看結果：寫法不同但剛好得到相同結果的 SQL 會算對；資料剛好讓錯誤條件得到相同結果的 SQL 也會算對。
