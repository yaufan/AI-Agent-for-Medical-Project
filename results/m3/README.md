# M3 結果：模型與部署

*English summary: in progress. Done so far: the routing gateway and its evaluation (no model calls). With cloud allowed up to internal data, 7 of 30 cases sent something sensitive to the cloud — all of them cases the labels are not designed to catch (confidential facts typed by the user without a code name, personal data written in unusual forms, a confidential fact copied into an internal document); allowing public data only sent nothing but kept every call local. Model comparison, answer quality, the real Claude run and the engine load test are not done yet.*

## 已完成：分級路由（`routing.json`）

### 做了什麼

- 每次呼叫模型之前，閘道（`packages/tools/agenttools/gateway.py`）先計算這次要送出內容的等級：
  - 使用者的話
  - 這一輪工具回傳的所有內容
- 等級分四級，由 `agenttools/sensitivity.py` 判定：公開、內部、機密、含個資。判定依據是文件的分類欄位、工具類型，加上個資規則（email、電話、身分證、病歷號）和機密專案代號清單。
- 超過允許等級的呼叫留在地端。同一輪只要轉到地端，就不會再回到雲端。
- 評估（`eval/routing/run_routing.py`）**不呼叫任何模型**：
  - 30 題，每題照預先寫好的順序呼叫工具。
  - 記下兩個後端各自收到的內容。
  - 用一份**和分級規則無關**的清單判斷有沒有漏：機密文件的每一行、機密事實的常見寫法、每題標記的個資值。
  - 這份清單會先自我檢查：「PCCP」出現在非機密文件裡，所以從清單移除。

### 結果

| 政策 | 有漏放的題數 | 漏放的呼叫 | 不必要留在地端的呼叫 | 送雲端／地端的呼叫 |
|---|---|---|---|---|
| 雲端可收公開＋內部資料（預設） | **7 / 30** | 10 | 2 | 44 / 16 |
| 雲端只收公開資料 | 0 / 30 | 0 | 36 | 0 / 60 |

預設政策下，各類別的結果：

| 類別 | 題數 | 有漏放的題數 | 說明 |
|---|---|---|---|
| 公開 | 4 | 0 | 全部送雲端 |
| 內部 | 6 | 0 | 全部送雲端（政策允許） |
| 檢索到機密文件 | 4 | 0 | 第一次呼叫只有問題，送雲端；拿到機密段落後轉地端 |
| 問題提到專案代號 | 2 | 0 | 一開始就留在地端；第一次呼叫裡其實沒有機密內容，算 2 次不必要 |
| 使用者自己打出機密事實（沒提代號） | 3 | **3** | 例如「我們預計 2027-01-29 提出 510(k)」，規則看不出來 |
| 使用者打出個資（一般寫法） | 3 | 0 | 電話、病歷號、email 都抓到 |
| 使用者打出個資（特殊寫法） | 2 | **2** | 國字電話「零九一二…」、小寫身分證 |
| 資料裡的個資（一般寫法） | 2 | 0 | 查到後轉地端 |
| 資料裡的個資（特殊寫法） | 1 | **1** | 「(02) 2345 6789」 |
| 機密事實被抄進內部文件 | 1 | **1** | 文件標的是內部，規則照標籤判斷 |
| 沒有權限 | 2 | 0 | 權限過濾在檢索時就擋掉 |

### 這代表什麼

- **依標籤路由，只擋得住標籤標得對的東西。** 漏放的 7 題都不是程式錯，而是規則本來就看不到的情況：使用者自己打出來的機密、寫法特殊的個資、標錯等級的文件。
- **改成只收公開資料**就不會漏，但也不會用到雲端：連使用者的問題本身都算內部，所以全部留在地端。
- 這組數字**沒有**用來調規則。可以改進的方向：
  - 機密事實的字典比對
  - 國字數字與大小寫正規化
  - 文件入庫時的內容掃描（DLP）

  改完要用新的題目重量，不能只拿這 30 題調到滿分。

## 尚未完成

| 項目 | 狀態 |
|---|---|
| 模型比較 A（Qwen3.8-27B Q8）／B（同模型 Q4）／C（8B 小模型）：情境任務、注入、回答品質、Text-to-SQL v2 | 沒做：程式已備好，要在 gx10-01 跑 |
| 雲端模型（Claude Opus 5.5）同一套題目 | 沒做：需要在環境設定 `ANTHROPIC_API_KEY` |
| 推論引擎比較（llama.cpp／vLLM／Ollama，同時 1、2、4、8 人） | 沒做：`eval/load/run_load.py` 已備好，要在機器空閒時跑 |
| FastAPI 服務、kind 部署、部署與回滾秒數 | 沒做 |
