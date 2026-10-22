# AI Agent for Medical Project

虛構的醫材公司 M 賣「肺結節 AI 輔助偵測軟體」，軟體裝在公司提供的地端 GPU 推論主機上。這個專案做的是公司 M **內部**用的 AI 平台：讓品保、法規、研發與主管，用自然語言跨 ERP、QMS、公司文件與外部法規資料完成工作，寫入動作一律經人工核准。

> 個人示範專案，研究與學習用途，非醫療器材。只使用公開資料（LIDC-IDRI、openFDA、ClinicalTrials.gov、FDA 文件）與合成資料；公司 M、醫院、廠牌、供應商都是虛構的，不對應任何真實機構或產品。

## 四個場景

| 使用者 | 情境 | 系統要做的事 |
|---|---|---|
| 品保 | 醫院B 換了新 CT 之後誤報變多 | 查類似客訴 → 查站點的 CT 機型與軟體版本 → 呼叫影像 QC／漂移工具 → 找出其他同型 CT 的醫院 → 起草 CAPA，等主管核准 |
| 法規 | 模型 v2.0 要不要重新送審 | 查 FDA 指引、已核准的同類產品、同類臨床研究的設計 → 帶引用的法規策略草稿 |
| 研發／服務 | GPU 停產要換料 | 比較規格 → 查再驗證 SOP → 查受影響站點 → 驗證新硬體推論一致 → 起草變更申請 |
| 主管 | 各站點營運狀況 | 自然語言查詢，SQL 與圖表一起顯示 |

細節見 [`docs/architecture.md`](docs/architecture.md)。

## 目前進度

| 里程碑 | 內容 | 狀態 |
|---|---|---|
| M0 | repo 結構、CI、影像模組併入、合成 ERP＋QMS、資料目錄 | 完成 |
| M1 | 附權限過濾的混合檢索與評估 | 完成（[結果](results/m1/)）：向量＋重排序 Recall@10 0.986；Qdrant／pgvector、Docling 比較與題庫人工審查未做 |
| M2 | MCP 工具、人工核准、注入測試 | 未開始 |
| M3 | 地端模型比較、gateway 分級路由、部署 | 未開始 |
| M4 | 示範介面與端到端場景 | 未開始 |

## 結構

| 路徑 | 內容 |
|---|---|
| [`packages/lungnod/`](packages/lungnod/) | 胸腔 CT 肺結節偵測：傳統影像處理與 3D CNN 比較，LIDC-IDRI，病例層級交叉驗證 |
| [`services/cad-service/`](services/cad-service/) | 推論服務：非同步工作、輸入 QC、PSI 漂移監控、Prometheus 指標、Docker／K8s、C++ 推論 |
| [`packages/erpqms/`](packages/erpqms/) | 公司 M 的合成 ERP＋QMS 資料庫，內含三條可驗證的故事線與參考查詢 |
| [`packages/rag/`](packages/rag/) | 附權限過濾的檢索（BM25、向量、RRF、重排序）與以證據原文為準的評估 |
| [`data/corpus/`](data/corpus/) | 知識庫：公司 M 的合成內部文件，以及公開文件清單（PDF 由腳本下載，不放進 repo） |
| [`eval/`](eval/) | 題庫、使用者與群組、評估與 CI 閘門 |
| [`results/`](results/) | 各里程碑的實驗結果與分析 |
| [`data/SOURCES.md`](data/SOURCES.md) | 公開資料來源與授權確認狀態 |
| [`docs/`](docs/) | 架構與規格、討論紀錄 |

## 執行

```bash
make install   # P1、P2 執行與測試所需套件
make test      # 全部測試
make data      # 產生合成 ERP＋QMS 資料到 data/synthetic/erpqms（SQLite＋CSV）
make eval-m1   # 下載公開文件並執行 M1 檢索評估
```

## 換到其他產業

| 這個專案 | 半導體／電子製造 |
|---|---|
| CT 影像偵測＋放射科醫師複判 | AXI／AOI 檢測＋人工複判 |
| 換了 CT 機型之後效能下降 | 換機台或製程之後模型漂移 |
| 推論主機的零件批號追溯 | 零件與製程批號追溯、客退分析 |
| 模型更新的變更管制與送審評估 | 製程變更通知（PCN）與客戶認證 |
| 病人影像只在院內處理，機密資料走地端模型 | 設計資料與客戶資料不上雲 |

---

## English summary

An internal AI platform for a fictional vendor of lung-nodule CAD software that runs on on-premise GPU appliances. Staff in QA, regulatory, R&D and management ask questions in natural language; the agent works across a synthetic ERP + QMS database, company documents, public regulatory data (openFDA, ClinicalTrials.gov, FDA guidance) and an imaging service built on LIDC-IDRI, and every write action waits for human approval. Personal project for research and learning, not a medical device; all organisations are fictional and only public or synthetic data is used.
