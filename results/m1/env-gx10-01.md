# M1 向量檢索與重排序：本機環境紀錄（gx10-01）

2026-10-22 在本機 gx10-01 跑 `bm25`、`dense`、`hybrid`，各自加或不加重排序；數字見 [`summary.md`](summary.md)。

## 硬體與系統

| 項目 | 內容 |
|---|---|
| 架構／OS | aarch64，Ubuntu 24.04.4 LTS |
| GPU | NVIDIA GB10（CPU 與 GPU 共用統一記憶體），驅動 580.142，CUDA 13.0 |
| CPU | 20 核（Cortex-X925 ＋ Cortex-A725） |
| 記憶體 | 共 121 GB；同一台機器同時有其他人的工作在跑 |
| Python | 3.12.3（`.venv`） |

可用記憶體（`free -g` 的 available）：載入 bge-m3 前 112 GB；卸載 bge-m3、啟動重排序前 108 GB；重排序執行期間最低約 102 GB；全部結束後 114 GB。全程沒有低於 16 GB。

## 軟體與模型

| 項目 | 版本 |
|---|---|
| Ollama | 0.40.8（官方 Linux arm64 壓縮檔，放在使用者目錄執行，沒有用 sudo，也沒有安裝成系統服務） |
| bge-m3 | `ollama list` ID `790764642607`；模型層 digest `sha256:daec91ffb5dd0c27411bd71f29932917c49cf529a641d0168496c3a501e3062c`；Ollama 回報 100% GPU，佔 689 MB |
| bge-reranker-v2-m3 | Hugging Face `BAAI/bge-reranker-v2-m3`，revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| 重排序服務 | `scripts/rerank_server.py`，**GPU**（`--device cuda`），max_length 1024（預設值），FP32，佔約 2.3 GB |
| PyTorch | 2.14.1+cu130（`download.pytorch.org/whl/cu130` 的 aarch64 版本，可以使用 GB10） |
| sentence-transformers | 6.2.0（transformers 5.20.2） |
| 其他 | fastapi 0.159.1、uvicorn 0.54.0、numpy 2.5.4、pdfplumber 0.11.10 |

## 執行方式

機器同時有其他人在用，所以**一次只載入一個模型**：

1. 第一階段：只開 Ollama（bge-m3），跑 `--methods bm25 dense hybrid`（不重排序），結果直接寫入 `results/m1/`。embedding 每批 16 筆（程式預設 32），段落與題目的向量另外存成快取。
2. 卸載 bge-m3、關掉 Ollama，再啟動重排序服務。
3. 第二階段：題目與段落的向量從快取讀，不呼叫 Ollama，跑同樣三種方法加重排序；只取 `*-rerank` 的結果放進 `results/m1/`。第二階段沒有重排序的設定，排名和第一階段逐題比對，完全相同。

快取用的包裝程式沒有放進 repo，檢索程式本身沒有改。

## 耗時

| 項目 | 時間 |
|---|---|
| embedding 段落：structured 954 段 | 20.9 秒（含第一次載入模型） |
| embedding 段落：fixed 876 段 | 12.0 秒 |
| 第二階段（6 組重排序設定，每題取前 50 名重排；三種權限模式＋撤銷檢查） | 2,277 秒（約 38 分鐘） |

## BM25 重現

在這台機器重跑 BM25：每一題的排名、Recall、MRR 都和 repo 裡的結果相同，`check_gate.py` 通過。檔案不是逐位元組相同：差異只有延遲數字，以及 `top1_score`、一題 nDCG 在小數點後第 14 位以後的浮點誤差。

## 注意事項與遇到的問題

- **延遲數字要分開看。** `summary.md` 延遲表的標題寫「單執行緒 CPU」，但這次的 `dense_ms` 包含呼叫 Ollama（GPU）的時間，`rerank_ms` 是呼叫 GPU 重排序服務的時間。`*-rerank` 設定的 `dense_ms` 是讀快取的時間（約 1 ms），**不是**真正的查詢 embedding 時間；真正的查詢 embedding 時間看沒有重排序的設定（P50 約 20 ms）。structured-dense 的 P95 為 1,919 ms，是少數查詢偏慢造成的，沒有再查原因。機器同時有其他工作在跑，延遲只能看量級。
- 沒有 sudo，所以沒有用官方的 `install.sh`，改用官方的壓縮檔在使用者目錄執行。Ollama 預設的 CUDA 12 函式庫不支援 GB10（compute capability 12.1），它自動改用內附的 CUDA 13 函式庫，最後跑在 GPU 上。
- 第一次啟動重排序服務時 bge-m3 也還在記憶體裡；收到「一次只載入一個模型」的要求後，先關掉重排序服務，改成上面的兩階段流程。正式結果都是用兩階段流程產生的。
