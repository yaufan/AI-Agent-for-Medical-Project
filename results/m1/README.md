# M1 檢索實驗：切塊方式 × 檢索方法 × 權限模式

完整數字見 [`summary.md`](summary.md)（由 `eval/report.py` 自動產生）；每一題的排名在 `runs/`（只存段落編號，不存文件內容）。

**目前只完成 BM25 的部分。** 向量檢索、重排序需要下載模型，這個雲端開發環境做不到，要在本機跑（指令在最後）。

## 設定

| 項目 | 內容 |
|---|---|
| 語料 | 28 份文件：FDA 指引 6 份、肺部 CADe（產品代碼 OEB）510(k) 文件 10 份、公司 M 的合成內部文件 12 份 |
| 權限群組 | `public`（FDA 文件）、`internal`（全公司 SOP、零件規格）、`proj-a`（1.x 產品，內部）、`proj-b`（2.0 開發，機密） |
| 切塊 | `structured`：依標題切、表格不切斷、每段前加標題路徑，954 段；`fixed`：1,200 字元滑動視窗、重疊 200，876 段 |
| 檢索 | BM25（自己實作；英文單字、中文雙字、代碼與條號保留原樣也拆成片段） |
| 權限模式 | `pre`：檢索前排除無權限段落；`post`：先取前 10 名再刪掉無權限的；`none`：不過濾 |
| 題庫 | 89 題：事實 32、表格數值 14、代碼與條號 11、跨語 14（其中 4 題和英文證據完全沒有共同詞彙）、越權 10、不可回答 8 |
| 相關性判定 | 每題標註證據原文；段落來自同一份文件且包含該段原文，就算相關。兩種切塊方式都沒有切斷任何一段證據（覆蓋率 76／76） |
| 個資 | 510(k) 文件裡的聯絡人 email 與電話在解析時遮蔽，共 99 處 |

## 結果（權限模式 pre，可回答的 71 題）

| 切塊 | Recall@1 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|
| structured | 0.592 | 0.831 | 0.845 | 0.681 |
| fixed | 0.592 | 0.775 | 0.789 | 0.658 |

| 題型（structured，Recall@10／MRR） | 結果 |
|---|---|
| 事實（32） | 0.97／0.81 |
| 表格數值（14） | 1.00／0.95 |
| 代碼與條號（11） | 0.82／0.60 |
| 跨語，有共同英文詞（10） | 0.60／0.23 |
| 跨語，沒有共同詞彙（4） | **0.00／0.00** |

## 觀察

### 1. 依章節切塊比固定長度好，差在「找到對的文件、卻選錯段落」

兩種切法都沒有把證據切斷，所以差距來自排序，不是覆蓋。前 5 名沒找到答案的題目，`fixed` 有 16 題，其中 10 題是**同一份文件裡的別段排在前面**；`structured` 降到 12 題，這一類剩 5 題。

原因是 510(k) 文件裡同樣的詞（產品名、nodule、predicate）在很多段反覆出現。依章節切塊後，每段前面加上「Device Description」「Predicate Device」這類標題，標題字詞本身就能幫忙排序。代碼與條號題差最多（Recall@10 0.82 對 0.73）。

### 2. BM25 做不到真正的跨語檢索

用中文問英文文件時，BM25 只能靠題目裡夾帶的英文詞（ClearRead CT、PCCP、MRMC）命中。有共同英文詞的 10 題，Recall@10 是 0.60；完全沒有共同詞彙的 4 題全部找不到。

`structured` 在前 5 名失敗的 12 題裡，**7 題是同一種情況**：題目的中文字詞（「適用」「法規」「送審」）和公司 M 的中文 SOP 重疊，SOP 排到前面，英文 FDA 文件排不上來。

最初的題庫只有夾帶英文詞的跨語題，會高估 BM25 的跨語能力。發現後補了 4 題沒有共同詞彙的題目，這組題目是下一步比較多語向量模型（bge-m3）最直接的對照。

### 3. 權限過濾要放在檢索裡面，不能放在後面

| 模式（structured） | 出現越權段落的題數 | 越權題中答案外洩 | 越權題平均回傳筆數 | 一般題平均回傳筆數 |
|---|---|---|---|---|
| pre | 0 | 0／10 | 7.0 | 9.92 |
| post | 0 | 0／10 | 1.0 | 9.47 |
| none | 27 | 10／10 | 10.0 | 9.92 |

- **不過濾時，洩漏不只發生在越權題。** 27 題出現機密或無權限段落，其中 17 題是一般使用者的正常提問，例如品保問客訴流程（I02、T01、T02）時，2.0 專案的機密文件也被排進前 10 名；反方向也有，2.0 專案的研發人員會撈到他沒有權限的 1.x 產品文件（T03、T04、C01）。
- **事後過濾（post）不會洩漏，但使用者會少拿到結果，而且不會知道。** 一般題平均回傳筆數從 9.92 降到 9.47；越權題從 7.0 降到 1.0。給 LLM 的上下文變少，回答品質會受影響，卻不會有任何錯誤訊息。
- **撤銷權限在下一次查詢就生效。** 撤銷法規專員的 `proj-b` 群組後，原本出現 54 個 `proj-b` 段落的 30 題降到 0，不需要重建索引，因為使用者群組是在查詢時才查的。

### 4. 只靠檢索分數無法判斷「該不該拒答」

第一名的 BM25 分數中位數：不可回答 16.0；跨語 21.6；事實 37.4。不可回答的題目分數確實比較低，但和跨語題重疊。如果用單一分數門檻拒答，會把跨語題一起擋掉。拒答要在回答階段由 LLM 判斷，這要接上模型後才能量（M1 尚未做）。

### 5. 延遲不是瓶頸

約 950 段的語料，BM25 加權限過濾的 P95 約 1 ms（雲端開發環境的 CPU）。之後的延遲主要會來自向量模型、重排序與 LLM 生成。

## 限制

- **題庫由 Claude 起草，還沒有人工審查。** 內部文件和題目是同一個作者寫的，題目用字容易貼近文件用字，可能高估內部文件題的分數。下一步要由有法規實務經驗的人另外出 30–50 題，並人工抽驗既有題目。
- 每題只有一位標註者，沒有標註一致性數字。
- PDF 用 pdfplumber 加規則解析，標題偵測仍有誤判（例如把下一行內文併進標題）；Docling 還沒比較。
- 題數少（可回答 71 題），各題型只有 11–32 題，題型之間的差距只能看趨勢。

## 沒做的

- 向量檢索（bge-m3）、混合檢索、重排序（bge-reranker-v2-m3）：程式與測試已完成，需要在本機跑。
- Qdrant 與 pgvector 的比較。
- Docling 與 pdfplumber 的解析比較。
- 群組目前來自 `eval/users.json`，還沒接 Keycloak。
- 回答階段的指標：引用 precision／recall、拒答率、自動評分與人工標註的一致性。

## 在本機跑向量檢索

```bash
make install corpus
ollama pull bge-m3
python eval/run_retrieval.py --methods bm25 dense hybrid --embed-url http://localhost:11434/v1 --embed-model bge-m3
# 重排序：Ollama 沒有 /rerank，用 scripts/rerank_server.py（sentence-transformers）或 vLLM 提供，例如
#   python scripts/rerank_server.py --model BAAI/bge-reranker-v2-m3 --port 8001 --device cuda
python eval/run_retrieval.py --methods hybrid --embed-url http://localhost:11434/v1 --embed-model bge-m3 \
    --rerank-url http://localhost:8001 --rerank-model BAAI/bge-reranker-v2-m3
python eval/report.py
```

---

**English summary.** BM25 over 954 heading-based chunks (6 FDA guidances, 10 lung-CADe 510(k) documents, 12 synthetic internal documents): Recall@10 0.845, MRR 0.681 on 71 answerable questions; fixed-size windows score lower (0.789 / 0.658), mostly because the right document is found but the wrong section of it is ranked first. Chinese questions about English documents fail whenever they share no English terms (0 of 4), usually because Chinese internal SOPs outrank the FDA text. Without access filtering, 27 of 89 questions surface chunks the user may not read, 17 of them ordinary questions; post-filtering prevents leaks but silently returns fewer results; filtering inside retrieval prevents leaks without that cost, and a revoked group disappears on the next query without re-indexing. Dense retrieval and reranking are implemented but need model downloads and will be run on the local machine. The question bank was drafted by Claude and has not been reviewed by a person yet.
