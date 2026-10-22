# M1 檢索實驗：切塊方式 × 檢索方法 × 權限模式

完整數字見 [`summary.md`](summary.md)（由 `eval/report.py` 自動產生）；每一題的排名在 `runs/`（只存段落編號，不存文件內容）。BM25 在雲端開發環境跑；向量與重排序在本機 gx10-01 跑，BM25 在兩台機器上的排名逐題相同。

## 設定

| 項目 | 內容 |
|---|---|
| 語料 | 28 份文件：FDA 指引 6 份、肺部 CADe（產品代碼 OEB）510(k) 文件 10 份、公司 M 的合成內部文件 12 份 |
| 權限群組 | `public`（FDA 文件）、`internal`（全公司 SOP、零件規格）、`proj-a`（1.x 產品，內部）、`proj-b`（2.0 開發，機密） |
| 切塊 | `structured`：依標題切、表格不切斷、每段前加標題路徑，954 段；`fixed`：1,200 字元滑動視窗、重疊 200，876 段 |
| 檢索 | BM25（自己實作；英文單字、中文雙字、代碼與條號保留原樣也拆成片段）；向量 bge-m3（Ollama）；混合＝BM25＋向量以 RRF 融合；重排序 bge-reranker-v2-m3（取前 50 名重排）。向量與重排序在本機 gx10-01 的 GPU 上跑，環境見 [`env-gx10-01.md`](env-gx10-01.md) |
| 權限模式 | `pre`：檢索前排除無權限段落；`post`：先取前 10 名再刪掉無權限的；`none`：不過濾 |
| 題庫 | 89 題：事實 32、表格數值 14、代碼與條號 11、跨語 14（其中 4 題和英文證據完全沒有共同詞彙）、越權 10、不可回答 8 |
| 相關性判定 | 每題標註證據原文；段落來自同一份文件且包含該段原文，就算相關。兩種切塊方式都沒有切斷任何一段證據（覆蓋率 76／76） |
| 個資 | 510(k) 文件裡的聯絡人 email 與電話在解析時遮蔽，共 99 處 |

## 結果（權限模式 pre，可回答的 71 題）

| 設定（structured 切塊） | Recall@1 | Recall@5 | Recall@10 | MRR | 每題延遲 P50 |
|---|---|---|---|---|---|
| BM25 | 0.592 | 0.831 | 0.845 | 0.681 | 0.1 ms |
| 向量 | 0.620 | 0.775 | 0.859 | 0.689 | 22 ms |
| 混合 | 0.606 | 0.859 | 0.915 | 0.712 | 22 ms |
| BM25＋重排序 | 0.789 | 0.887 | 0.901 | 0.837 | 2.0 s |
| **向量＋重排序** | **0.831** | **0.958** | **0.986** | **0.896** | 2.4 s |
| 混合＋重排序 | 0.817 | 0.958 | 0.972 | 0.880 | 1.1 s |

`fixed` 切塊的每一種方法都比 `structured` 低（最好的是向量／混合＋重排序，Recall@10 0.930）。

| 跨語、沒有共同詞彙的 4 題（Recall@10） | structured | fixed |
|---|---|---|
| BM25（有無重排序） | 0／4 | 0／4 |
| 向量 | 2／4 | 2／4 |
| 混合 | 1／4 | 1／4 |
| 向量＋重排序 | 4／4 | 4／4 |
| 混合＋重排序 | 4／4 | 4／4 |

延遲在共用的 GB10 上量，同一時間機器上還有其他工作；只能看量級。重排序設定裡的向量查詢時間是讀快取的時間，不是真實值（見 `env-gx10-01.md`）。

## 觀察

### 1. 重排序帶來的提升最大

同樣是 structured 切塊，加上重排序後 MRR 從 0.68–0.71 升到 0.84–0.90，Recall@1 從約 0.6 升到 0.79–0.83。差距主要來自「找到對的文件、卻選錯段落」這一類（第 6 點）：前 50 名裡通常已經有正確段落，重排序把它排到前面。

代價是延遲：每題重排 50 段約 1–2.4 秒（FP32、max_length 1024、GPU）。互動式問答可以接受，但不適合批次大量查詢；下一步可以比較少重排幾段（例如前 20 段）、或用 FP16 的差別。

### 2. 跨語檢索：向量模型找得到範圍，重排序才排得準

沒有共同詞彙的 4 題，BM25 一題都找不到；bge-m3 向量檢索找到 2 題；加上重排序後 4 題都進前 10 名。

**混合檢索在這 4 題反而比單用向量差**（1／4 對 2／4）。原因是 BM25 在這些題目上排出來的都是錯的中文 SOP（第 7 點），RRF 融合時把這些錯誤結果一起拉上來，擠掉了向量檢索找到的英文段落。整體來看混合檢索的 Recall@10 仍比單用向量高（0.915 對 0.859），所以「混合一定比較好」只在整體平均上成立，在特定題型會變差。加上重排序後兩者差距消失。

### 3. 最佳設定唯一的失敗，是題庫標註問題

structured 向量＋重排序只漏掉 P01（「Product code OEB 對應的法規條號是什麼？」）。排在前面的段落（K240554、K251203 的決定函）同樣寫著「21 CFR 892.2050」，答案正確，但題庫只把 K231157 列為正確出處。這題應該接受任何一份 OEB 510(k) 的出處；下一版題庫修正，並重新跑所有設定。

### 4. 權限過濾要放在檢索裡面，不能放在後面（BM25 的數字；12 組設定的洩漏都在 summary.md）

| 模式（structured） | 出現越權段落的題數 | 越權題中答案外洩 | 越權題平均回傳筆數 | 一般題平均回傳筆數 |
|---|---|---|---|---|
| pre | 0 | 0／10 | 7.0 | 9.92 |
| post | 0 | 0／10 | 1.0 | 9.47 |
| none | 27 | 10／10 | 10.0 | 9.92 |

- **不過濾時，洩漏不只發生在越權題。** 27 題出現機密或無權限段落，其中 17 題是一般使用者的正常提問，例如品保問客訴流程（I02、T01、T02）時，2.0 專案的機密文件也被排進前 10 名；反方向也有，2.0 專案的研發人員會撈到他沒有權限的 1.x 產品文件（T03、T04、C01）。
- **事後過濾（post）不會洩漏，但使用者會少拿到結果，而且不會知道。** 一般題平均回傳筆數從 9.92 降到 9.47；越權題從 7.0 降到 1.0。給 LLM 的上下文變少，回答品質會受影響，卻不會有任何錯誤訊息。
- **撤銷權限在下一次查詢就生效。** 撤銷法規專員的 `proj-b` 群組後，原本出現 54 個 `proj-b` 段落的 30 題降到 0，不需要重建索引，因為使用者群組是在查詢時才查的。

### 5. BM25 分數分不出「該不該拒答」，重排序分數分得比較開

第一名的 BM25 分數中位數：不可回答 16.0；跨語 21.6；事實 37.4。不可回答的題目分數確實比較低，但和跨語題重疊。如果用單一分數門檻拒答，會把跨語題一起擋掉。重排序分數的第一名中位數（structured-dense-rerank）：不可回答 0.44；跨語 0.98；事實 0.996。中位數分得開，但這只是中位數，還沒有逐題看分布、也沒有選門檻；拒答最終仍要在回答階段由 LLM 判斷，要接上模型後才能量（M1 尚未做）。

### 6. 依章節切塊比固定長度好（BM25），差在「找到對的文件、卻選錯段落」

兩種切法都沒有把證據切斷，所以差距來自排序，不是覆蓋。前 5 名沒找到答案的題目，`fixed` 有 16 題，其中 10 題是**同一份文件裡的別段排在前面**；`structured` 降到 12 題，這一類剩 5 題。

原因是 510(k) 文件裡同樣的詞（產品名、nodule、predicate）在很多段反覆出現。依章節切塊後，每段前面加上「Device Description」「Predicate Device」這類標題，標題字詞本身就能幫忙排序。代碼與條號題差最多（Recall@10 0.82 對 0.73）。

### 7. BM25 失敗的原因：中文問英文文件

用中文問英文文件時，BM25 只能靠題目裡夾帶的英文詞（ClearRead CT、PCCP、MRMC）命中。有共同英文詞的 10 題，Recall@10 是 0.60；完全沒有共同詞彙的 4 題全部找不到。

`structured` 在前 5 名失敗的 12 題裡，**7 題是同一種情況**：題目的中文字詞（「適用」「法規」「送審」）和公司 M 的中文 SOP 重疊，SOP 排到前面，英文 FDA 文件排不上來。

最初的題庫只有夾帶英文詞的跨語題，會高估 BM25 的跨語能力。發現後補了 4 題沒有共同詞彙的題目，向量檢索與重排序的結果見第 1、2 點。

## 限制

- **題庫由 Claude 起草，還沒有人工審查。** 內部文件和題目是同一個作者寫的，題目用字容易貼近文件用字，可能高估內部文件題的分數。下一步要由有法規實務經驗的人另外出 30–50 題，並人工抽驗既有題目。
- 每題只有一位標註者，沒有標註一致性數字。
- PDF 用 pdfplumber 加規則解析，標題偵測仍有誤判（例如把下一行內文併進標題）；Docling 還沒比較。
- 題數少（可回答 71 題），各題型只有 11–32 題，題型之間的差距只能看趨勢；沒有做顯著性檢定。
- 題庫有標註過窄的題目（P01，見第 3 點），可能還有其他類似情況，人工審查時要一起看。
- 延遲在共用機器上量，不是乾淨的效能測試。

## 沒做的

- Qdrant 與 pgvector 的比較（目前向量存在記憶體裡的 numpy 陣列）。
- Docling 與 pdfplumber 的解析比較。
- 重排序的候選數、精度（FP16）、輸入長度對品質與延遲的影響。
- 群組目前來自 `eval/users.json`，還沒接 Keycloak。
- 回答階段的指標：引用 precision／recall、拒答率、自動評分與人工標註的一致性。
- 題庫的人工審查。

## 重跑向量檢索與重排序

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

**English summary.** On 71 answerable questions over 954 heading-based chunks, BM25 reaches Recall@10 0.845 / MRR 0.681, bge-m3 dense retrieval 0.859 / 0.689, and RRF hybrid 0.915 / 0.712. Cross-encoder reranking (bge-reranker-v2-m3 over the top 50) gives the largest gain: dense + rerank reaches 0.986 / 0.896, at about 2.4 s per query on a shared GB10. For the four Chinese questions that share no terms with their English evidence, BM25 finds none, dense finds two, hybrid only one (BM25's wrong Chinese SOP hits are fused in), and both reranked variants find all four. The single remaining miss of the best configuration is a labelling problem: other 510(k) letters retrieved first state the same regulation number. Filtering inside retrieval leaks nothing in all 12 configurations; without filtering, ordinary questions also surface confidential chunks. Fixed-size chunks score lower than heading-based chunks with every method. The question bank was drafted by Claude and still needs human review.
