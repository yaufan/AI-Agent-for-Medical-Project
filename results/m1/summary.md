# M1 檢索結果（自動產生，請勿手改）

由 `python eval/report.py` 從 `results/m1/*.json` 產生。

## 可回答的題目（權限模式 pre）

| 設定 | 段落數 | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| fixed-bm25-rerank | 876 | 0.775 | 0.859 | 0.859 | 0.817 | 0.828 |
| fixed-bm25 | 876 | 0.592 | 0.775 | 0.789 | 0.658 | 0.683 |
| fixed-dense-rerank | 876 | 0.775 | 0.930 | 0.930 | 0.846 | 0.868 |
| fixed-dense | 876 | 0.535 | 0.746 | 0.831 | 0.632 | 0.674 |
| fixed-hybrid-rerank | 876 | 0.775 | 0.930 | 0.930 | 0.846 | 0.868 |
| fixed-hybrid | 876 | 0.592 | 0.845 | 0.873 | 0.687 | 0.724 |
| structured-bm25-rerank | 954 | 0.789 | 0.887 | 0.901 | 0.837 | 0.850 |
| structured-bm25 | 954 | 0.592 | 0.831 | 0.845 | 0.681 | 0.713 |
| structured-dense-rerank | 954 | 0.831 | 0.958 | 0.986 | 0.896 | 0.915 |
| structured-dense | 954 | 0.620 | 0.775 | 0.859 | 0.689 | 0.729 |
| structured-hybrid-rerank | 954 | 0.817 | 0.958 | 0.972 | 0.880 | 0.900 |
| structured-hybrid | 954 | 0.606 | 0.859 | 0.915 | 0.712 | 0.759 |

題數：71（事實、表格數值、代碼與條號、跨語）

## 依題型（Recall@10／MRR，權限模式 pre）

| 設定 | fact | table | code | cross_lingual | 跨語：無共同詞彙 |
|---|---|---|---|---|---|
| fixed-bm25-rerank | 0.97／0.91（32） | 1.00／0.96（14） | 0.73／0.73（11） | 0.57／0.54（14） | 0.00／0.00（4） |
| fixed-bm25 | 0.91／0.79（32） | 1.00／0.96（14） | 0.73／0.49（11） | 0.36／0.19（14） | 0.00／0.00（4） |
| fixed-dense-rerank | 0.97／0.91（32） | 1.00／0.96（14） | 0.82／0.74（11） | 0.86／0.67（14） | 1.00／0.71（4） |
| fixed-dense | 0.88／0.73（32） | 1.00／0.81（14） | 0.73／0.47（11） | 0.64／0.35（14） | 0.50／0.15（4） |
| fixed-hybrid-rerank | 0.97／0.91（32） | 1.00／0.96（14） | 0.82／0.74（11） | 0.86／0.67（14） | 1.00／0.71（4） |
| fixed-hybrid | 0.94／0.82（32） | 1.00／0.95（14） | 0.82／0.47（11） | 0.64／0.29（14） | 0.25／0.05（4） |
| structured-bm25-rerank | 0.97／0.91（32） | 1.00／0.96（14） | 0.82／0.76（11） | 0.71／0.62（14） | 0.00／0.00（4） |
| structured-bm25 | 0.97／0.81（32） | 1.00／0.95（14） | 0.82／0.60（11） | 0.43／0.17（14） | 0.00／0.00（4） |
| structured-dense-rerank | 1.00／0.92（32） | 1.00／0.96（14） | 0.91／0.86（11） | 1.00／0.80（14） | 1.00／0.62（4） |
| structured-dense | 0.97／0.78（32） | 0.93／0.87（14） | 0.73／0.56（11） | 0.64／0.41（14） | 0.50／0.28（4） |
| structured-hybrid-rerank | 0.97／0.91（32） | 1.00／0.96（14） | 0.91／0.80（11） | 1.00／0.80（14） | 1.00／0.63（4） |
| structured-hybrid | 0.97／0.83（32） | 1.00／0.93（14） | 0.91／0.60（11） | 0.71／0.32（14） | 0.25／0.06（4） |

括號內是題數。

## 權限控管

| 設定 | 模式 | 出現越權段落的題數 | 越權段落總數 | 越權題中答案段落外洩 | 越權題平均回傳筆數 | 一般題平均回傳筆數 |
|---|---|---|---|---|---|---|
| fixed-bm25-rerank | pre | 0 | 0 | 0／10 | 7.0 | 8.68 |
| fixed-bm25-rerank | post | 0 | 0 | 0／10 | 4.8 | 8.41 |
| fixed-bm25-rerank | none | 38 | 91 | 10／10 | 9.2 | 9.07 |
| fixed-bm25 | pre | 0 | 0 | 0／10 | 7.0 | 8.68 |
| fixed-bm25 | post | 0 | 0 | 0／10 | 4.6 | 8.40 |
| fixed-bm25 | none | 38 | 94 | 10／10 | 9.2 | 9.07 |
| fixed-dense-rerank | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| fixed-dense-rerank | post | 0 | 0 | 0／10 | 7.3 | 9.69 |
| fixed-dense-rerank | none | 29 | 49 | 10／10 | 10.0 | 10.00 |
| fixed-dense | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| fixed-dense | post | 0 | 0 | 0／10 | 7.4 | 9.66 |
| fixed-dense | none | 29 | 50 | 10／10 | 10.0 | 10.00 |
| fixed-hybrid-rerank | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| fixed-hybrid-rerank | post | 0 | 0 | 0／10 | 7.0 | 9.54 |
| fixed-hybrid-rerank | none | 32 | 63 | 10／10 | 10.0 | 10.00 |
| fixed-hybrid | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| fixed-hybrid | post | 0 | 0 | 0／10 | 5.6 | 9.49 |
| fixed-hybrid | none | 37 | 80 | 10／10 | 10.0 | 10.00 |
| structured-bm25-rerank | pre | 0 | 0 | 0／10 | 7.0 | 9.92 |
| structured-bm25-rerank | post | 0 | 0 | 0／10 | 2.9 | 9.42 |
| structured-bm25-rerank | none | 30 | 106 | 10／10 | 10.0 | 9.92 |
| structured-bm25 | pre | 0 | 0 | 0／10 | 7.0 | 9.92 |
| structured-bm25 | post | 0 | 0 | 0／10 | 1.0 | 9.47 |
| structured-bm25 | none | 27 | 122 | 10／10 | 10.0 | 9.92 |
| structured-dense-rerank | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| structured-dense-rerank | post | 0 | 0 | 0／10 | 4.4 | 9.69 |
| structured-dense-rerank | none | 22 | 78 | 10／10 | 10.0 | 10.00 |
| structured-dense | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| structured-dense | post | 0 | 0 | 0／10 | 4.1 | 9.55 |
| structured-dense | none | 24 | 91 | 9／10 | 10.0 | 10.00 |
| structured-hybrid-rerank | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| structured-hybrid-rerank | post | 0 | 0 | 0／10 | 4.4 | 9.64 |
| structured-hybrid-rerank | none | 25 | 82 | 10／10 | 10.0 | 10.00 |
| structured-hybrid | pre | 0 | 0 | 0／10 | 10.0 | 10.00 |
| structured-hybrid | post | 0 | 0 | 0／10 | 2.1 | 9.45 |
| structured-hybrid | none | 31 | 118 | 10／10 | 10.0 | 10.00 |

## 撤銷權限

| 設定 | 使用者 | 撤銷群組 | 撤銷前該群組段落數 | 撤銷後 | 下一次查詢即生效 | 需要重建索引 |
|---|---|---|---|---|---|---|
| fixed-bm25-rerank | ra_huang | proj-b | 30 | 0 | 是 | 否 |
| fixed-bm25 | ra_huang | proj-b | 30 | 0 | 是 | 否 |
| fixed-dense-rerank | ra_huang | proj-b | 5 | 0 | 是 | 否 |
| fixed-dense | ra_huang | proj-b | 5 | 0 | 是 | 否 |
| fixed-hybrid-rerank | ra_huang | proj-b | 17 | 0 | 是 | 否 |
| fixed-hybrid | ra_huang | proj-b | 17 | 0 | 是 | 否 |
| structured-bm25-rerank | ra_huang | proj-b | 54 | 0 | 是 | 否 |
| structured-bm25 | ra_huang | proj-b | 54 | 0 | 是 | 否 |
| structured-dense-rerank | ra_huang | proj-b | 7 | 0 | 是 | 否 |
| structured-dense | ra_huang | proj-b | 7 | 0 | 是 | 否 |
| structured-hybrid-rerank | ra_huang | proj-b | 29 | 0 | 是 | 否 |
| structured-hybrid | ra_huang | proj-b | 29 | 0 | 是 | 否 |

## 延遲（毫秒，權限模式 pre，單執行緒 CPU）

| 設定 | 階段 | P50 | P95 |
|---|---|---|---|
| fixed-bm25-rerank | acl_ms | 0.057 | 0.077 |
| fixed-bm25-rerank | bm25_ms | 0.214 | 0.718 |
| fixed-bm25-rerank | fusion_ms | 0.004 | 0.011 |
| fixed-bm25-rerank | rerank_ms | 1056.298 | 1559.878 |
| fixed-bm25-rerank | total_ms | 1056.694 | 1560.288 |
| fixed-bm25 | acl_ms | 0.011 | 0.012 |
| fixed-bm25 | bm25_ms | 0.094 | 0.397 |
| fixed-bm25 | fusion_ms | 0.003 | 0.004 |
| fixed-bm25 | total_ms | 0.110 | 0.412 |
| fixed-dense-rerank | acl_ms | 0.057 | 0.077 |
| fixed-dense-rerank | dense_ms | 0.921 | 1.368 |
| fixed-dense-rerank | fusion_ms | 0.005 | 0.010 |
| fixed-dense-rerank | rerank_ms | 1275.535 | 1564.891 |
| fixed-dense-rerank | total_ms | 1276.623 | 1565.954 |
| fixed-dense | acl_ms | 0.021 | 0.051 |
| fixed-dense | dense_ms | 21.563 | 44.511 |
| fixed-dense | fusion_ms | 0.008 | 0.011 |
| fixed-dense | total_ms | 21.614 | 44.539 |
| fixed-hybrid-rerank | acl_ms | 0.056 | 0.078 |
| fixed-hybrid-rerank | bm25_ms | 0.210 | 0.848 |
| fixed-hybrid-rerank | dense_ms | 0.987 | 1.221 |
| fixed-hybrid-rerank | fusion_ms | 0.028 | 0.055 |
| fixed-hybrid-rerank | rerank_ms | 1356.828 | 1581.938 |
| fixed-hybrid-rerank | total_ms | 1358.266 | 1583.265 |
| fixed-hybrid | acl_ms | 0.041 | 0.047 |
| fixed-hybrid | bm25_ms | 0.234 | 1.125 |
| fixed-hybrid | dense_ms | 19.589 | 55.416 |
| fixed-hybrid | fusion_ms | 0.039 | 0.059 |
| fixed-hybrid | total_ms | 19.892 | 55.554 |
| structured-bm25-rerank | acl_ms | 0.144 | 0.232 |
| structured-bm25-rerank | bm25_ms | 0.457 | 1.514 |
| structured-bm25-rerank | fusion_ms | 0.008 | 0.015 |
| structured-bm25-rerank | rerank_ms | 2040.283 | 2561.141 |
| structured-bm25-rerank | total_ms | 2041.883 | 2561.990 |
| structured-bm25 | acl_ms | 0.011 | 0.013 |
| structured-bm25 | bm25_ms | 0.099 | 0.430 |
| structured-bm25 | fusion_ms | 0.003 | 0.003 |
| structured-bm25 | total_ms | 0.113 | 0.445 |
| structured-dense-rerank | acl_ms | 0.135 | 0.236 |
| structured-dense-rerank | dense_ms | 4.505 | 10.184 |
| structured-dense-rerank | fusion_ms | 0.012 | 0.026 |
| structured-dense-rerank | rerank_ms | 2385.802 | 2625.445 |
| structured-dense-rerank | total_ms | 2390.767 | 2630.499 |
| structured-dense | acl_ms | 0.028 | 0.053 |
| structured-dense | dense_ms | 21.828 | 1919.492 |
| structured-dense | fusion_ms | 0.007 | 0.012 |
| structured-dense | total_ms | 21.865 | 1919.541 |
| structured-hybrid-rerank | acl_ms | 0.073 | 0.101 |
| structured-hybrid-rerank | bm25_ms | 0.321 | 1.193 |
| structured-hybrid-rerank | dense_ms | 0.962 | 3.687 |
| structured-hybrid-rerank | fusion_ms | 0.038 | 0.058 |
| structured-hybrid-rerank | rerank_ms | 1118.710 | 1275.816 |
| structured-hybrid-rerank | total_ms | 1119.681 | 1278.110 |
| structured-hybrid | acl_ms | 0.020 | 0.045 |
| structured-hybrid | bm25_ms | 0.179 | 0.821 |
| structured-hybrid | dense_ms | 21.446 | 43.670 |
| structured-hybrid | fusion_ms | 0.023 | 0.046 |
| structured-hybrid | total_ms | 21.824 | 43.887 |

## 第一名分數中位數（用來觀察能否設定拒答門檻）

| 設定 | 不可回答 | fact | table | code | cross_lingual |
|---|---|---|---|---|---|
| fixed-bm25-rerank | 0.2402 | 0.986 | 0.9686 | 0.9799 | 0.851 |
| fixed-bm25 | 13.0386 | 31.3394 | 32.0115 | 21.9372 | 20.2637 |
| fixed-dense-rerank | 0.2402 | 0.986 | 0.9686 | 0.9799 | 0.9174 |
| fixed-dense | 0.6242 | 0.6616 | 0.6538 | 0.5618 | 0.6616 |
| fixed-hybrid-rerank | 0.2402 | 0.986 | 0.9686 | 0.9799 | 0.9174 |
| fixed-hybrid | 0.0313 | 0.0328 | 0.0328 | 0.032 | 0.0319 |
| structured-bm25-rerank | 0.4044 | 0.9962 | 0.9624 | 0.974 | 0.9311 |
| structured-bm25 | 16.0321 | 37.4145 | 39.5554 | 26.5206 | 21.6324 |
| structured-dense-rerank | 0.4389 | 0.9962 | 0.9624 | 0.9901 | 0.9805 |
| structured-dense | 0.6364 | 0.7264 | 0.719 | 0.684 | 0.6822 |
| structured-hybrid-rerank | 0.4389 | 0.9962 | 0.9624 | 0.9901 | 0.9805 |
| structured-hybrid | 0.0315 | 0.0328 | 0.0328 | 0.0328 | 0.0321 |
