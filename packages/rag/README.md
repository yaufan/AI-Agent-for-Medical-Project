# rag：附權限過濾的混合檢索與評估

公司 M 內部知識庫的檢索層。給一個問題和使用者，回傳這個使用者**有權限看到的**最相關段落；同時提供用證據原文評估檢索品質的工具。實驗結果在 [`results/m1/`](../../results/m1/)。

## 模組

| 檔案 | 內容 |
|---|---|
| `documents.py` | 讀入合成 Markdown（front matter 帶群組與機密等級）與公開 PDF（pdfplumber）；去除頁首、目錄頁、草案的行號；偵測章節標題；**遮蔽 email 與電話** |
| `chunking.py` | `structured`（依標題、表格不切斷、表格過長時每段重複表頭、段落前加標題路徑）與 `fixed`（滑動視窗）兩種切塊 |
| `bm25.py` | BM25 與斷詞：英文單字、中文雙字；`21 CFR §892.2050`、`QMS-SOP-007`、`C-320` 這類代碼保留原樣也拆成片段 |
| `dense.py` | 向量檢索與重排序的介面：OpenAI 相容的 `/embeddings`、vLLM／TEI 的 `/rerank`；`HashingEmbedder` 只給測試用 |
| `acl.py` | 使用者群組（查詢時才查，撤銷立即生效）；`public` 所有人可讀 |
| `retriever.py` | BM25、向量、RRF 融合、重排序；權限模式 `pre`／`post`／`none`；記錄各階段耗時 |
| `metrics.py` | 以證據原文判定相關性；Recall@k、MRR、nDCG@10、覆蓋率 |
| `evaluate.py` | 依題型彙整結果、洩漏統計、撤銷權限檢查 |

## 設計重點

- **權限過濾在檢索內部做**（`pre`）：被排除的段落不會進入排名，也不會交給 LLM。不靠 LLM 自己「不要說出來」。
- **群組在查詢時查**，所以撤銷權限不需要重建索引。正式環境的群組來自 Keycloak 或 LDAP。
- **相關性用證據原文判定**，不綁死段落編號。換切塊方式、換解析器，同一份題庫都能直接用。
- **個資在進索引前遮蔽**；評估結果只存段落編號，不存文件內容。

## 使用

```python
from pathlib import Path
from rag.acl import GroupStore
from rag.chunking import chunk_corpus
from rag.documents import load_corpus
from rag.retriever import Retriever

docs, _ = load_corpus(Path("data/corpus"), Path("data/raw/public"))
retriever = Retriever(chunk_corpus(docs, "structured"))
store = GroupStore.from_json(Path("eval/users.json"))
hits, timings = retriever.search("GPU G1 的最後採購日？", store.groups("svc_wang"), k=5)
```

## 適合自己重寫練習的函式

刪掉實作、保留函式簽名，自己寫到 `python -m pytest -q packages/rag/tests` 通過：

| 函式 | 測試 |
|---|---|
| `retriever.rrf` | `test_rrf_rewards_agreement` |
| `metrics.score_ranking` | `test_score_ranking` |
| `bm25.tokenize` | `test_tokenize_*` |
| `chunking._split_table` | `test_split_table_repeats_header` |
| `bm25.BM25.scores` | `test_bm25_ranks_matching_document_first` |
