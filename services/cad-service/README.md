# P2　醫療影像 AI 推論服務：把 P1 的模型變成可維運的服務

把 P1 的肺結節偵測包成一個 HTTP 服務，補齊模型上線後真正會遇到的問題：輸入品質把關、長時間推論的非同步處理、監控指標、資料漂移、容器化與 Kubernetes 部署（含 A100 MIG 切片），以及 C++ 推論整合。

> 研究與學習用途，非醫療器材，不可用於臨床診斷。

## 架構

```
          zip(DICOM)                       ┌──────────────── nodule-service（FastAPI）────────────────┐
 用戶端 ─────────────▶ POST /v1/studies ──▶│ 讀取 DICOM → QC 檢查 ──不合格──▶ 422 + 原因              │
          ◀── 202 job_id ─────────────────│      │合格                                              │
                                           │      ├─▶ 輸入概況 → 漂移監控（PSI）                       │
 用戶端 ─▶ GET /v1/jobs/{id} ─────────────▶│      └─▶ 工作佇列（執行緒池）→ lungnod.NoduleDetector    │
          ◀── 狀態／結節清單 ──────────────│              重取樣 → 肺分割 → 候選點 → ONNX CNN(+GBM)   │
                                           │ /healthz  /readyz  /metrics  /v1/drift                   │
                                           └──────────────────────────────────────────────────────────┘
                                                         │ /metrics
                                                   Prometheus（告警：PSI > 0.25、QC 拒收率、處理時間）
```

## 設計決策

| 問題 | 做法 | 為什麼 |
|---|---|---|
| 一次推論要數十秒到數分鐘 | 送出工作回 202，之後用 job_id 查詢 | HTTP 連線不會逾時；同時處理數量由執行緒池控制，不會塞爆記憶體 |
| 不合格的輸入 | 推論前先做 QC：切片間距 ≤ 2.5 mm、切片數 ≥ 60、像素間距、切片是否等距；不合格回 422 並列出原因 | 模型沒看過的條件下硬推論，結果不可信；拒收原因也計入指標，可以回頭找是哪台機器或哪種協定 |
| 模型載入 | 啟動時載入一次；載入完成 `/readyz` 才回 200 | K8s 的 readiness probe 會等模型載好才導流量；liveness 和 readiness 分開，避免重啟迴圈 |
| 資料漂移 | 每次請求記錄輸入概況（切片間距、像素間距、廠牌、HU 分布），和訓練資料比 PSI；累積到 20 筆才回報 | 換機器、換協定時效能會掉，PSI 是不需要標註就能先發現的警訊。實測只有 1 筆時 PSI 高達 5 以上，沒有意義，所以要設最少樣本數 |
| 個資 | 回應與日誌只用 SeriesInstanceUID 與 job_id，不輸出 PatientName、PatientID | 測試裡有檢查回應不含病人姓名與 ID |
| 前處理一致性 | 服務直接 import P1 的 `lungnod` 套件，不另外寫一份 | 訓練和部署用同一份前處理程式，從根本避免兩邊不一致 |
| 映像大小 | 推論只裝 onnxruntime，不裝 torch | 映像小、啟動快；訓練與推論的相依套件分開 |
| 多副本 | 目前工作狀態放記憶體，所以 `replicas: 1` | 要水平擴充，先把工作狀態移到 Redis 或資料庫，再依佇列長度擴充（例如 KEDA） |
| GPU 共用 | `deploy/k8s/gpu-mig-patch.yaml`：請求 `nvidia.com/mig-1g.5gb` | 小模型用一個 MIG 切片就夠，一張 A100 40GB 最多切 7 片，各服務記憶體與算力互相隔離 |

## 執行

```bash
cd services/cad-service
pip install ../../packages/lungnod -r requirements-dev.txt

# 測試（合成的 DICOM 假體與極小的 ONNX 模型，不需要真實資料）
python -m pytest -q tests

# 準備模型：從 P1 複製，並用訓練資料建立漂移參考分布（閾值預設 0.567 = P1 的 1 FP/scan 操作點）
mkdir -p models
cp ../../packages/lungnod/results/nodule_cnn.onnx ../../packages/lungnod/results/gbm_final.joblib models/
python scripts/build_reference.py --data ../../packages/lungnod/data/lidc_idri --out models/reference_profile.json

# 本機啟動
MODEL_PATH=models/nodule_cnn.onnx GBM_PATH=models/gbm_final.joblib REFERENCE_PATH=models/reference_profile.json \
  uvicorn service.main:app --port 8000

# 送一個 CT 序列（把某個 CT 資料夾的 .dcm 壓成 zip）
curl -F "file=@ct.zip" localhost:8000/v1/studies          # → {"job_id": "..."}
curl localhost:8000/v1/jobs/<job_id>
curl localhost:8000/metrics | grep nodule_
```

Windows PowerShell 設環境變數的寫法是 `$env:MODEL_PATH="models/nodule_cnn.onnx"`。

### Docker 與 Kubernetes（在你的電腦上：Docker Desktop 內建 K8s）

```bash
cd ../..    # 回到 repo 根目錄
docker compose -f services/cad-service/deploy/docker-compose.yml up --build    # 服務 + Prometheus（:9090）

docker build -f services/cad-service/deploy/Dockerfile -t nodule-service:0.1.0 .
kubectl apply -f services/cad-service/deploy/k8s/
kubectl get pods -w
```

PVC 裡的模型檔要先放進去（例如用一個暫時的 Pod 掛載後 `kubectl cp`）。這部分是很好的練習：想一想正式環境的模型應該從哪裡來（模型註冊表、物件儲存），以及怎麼做版本切換和回滾。

### C++ 推論（`cpp/`）

示範產線或設備端常見的整合方式：前處理在 Python，模型推論在 C++。

```bash
# 下載 ONNX Runtime 官方 release（Windows 選 onnxruntime-win-x64-<版本>.zip），解壓後：
cmake -S cpp -B cpp/build -DONNXRUNTIME_DIR=<解壓路徑> -DCMAKE_BUILD_TYPE=Release
cmake --build cpp/build --config Release
python scripts/compare_cpp.py --model models/nodule_cnn.onnx --binary cpp/build/nodule_infer \
  --cache ../../packages/lungnod/cache/<某個病例>.npz
```

`compare_cpp.py` 會確認 C++ 和 Python 的輸出一致（最大差異 < 1e-4），並比較延遲。

在開發環境實測（P1 的真實模型、某例的 300 個候選區塊、4 執行緒 CPU）：C++ 與 Python 輸出的最大差異 **5.1e-7**；推論時間 C++ 2.31 秒、Python 2.19 秒，模型載入 25 ms。兩邊用的是同一個 ONNX Runtime 引擎，所以速度差不多。C++ 的價值在於能整合進既有的 C++ 系統（設備軟體、產線程式），不需要 Python 執行環境。

### CI

`ci/github-actions.yml`：跑 P1、P2 的測試 → 建置映像 → 啟動容器確認 `/readyz`。獨立成公開 repo 時放到 `.github/workflows/`。

## 已驗證與未驗證

| 項目 | 狀態 |
|---|---|
| API 流程、QC、漂移、指標、個資不外流（`tests/`，7 項） | 已在開發環境通過 |
| uvicorn 實際啟動、`/readyz`、`/metrics` | 已驗證 |
| 真實模型＋真實 CT 的端到端流程 | 已驗證：LIDC-IDRI-0003（140 張切片）上傳 zip → 209 秒完成；找到 3 顆目標結節（22、13、9 mm），另有 2 個誤報（閾值 0.567）；重複的結果已合併；回應與日誌不含病人姓名、ID。這個病例在最終模型的訓練資料裡，只用來驗證流程，不代表效能 |
| C++ 推論與 Python 輸出一致 | 已驗證：真實模型最大差異 5.1e-7 |
| Dockerfile、docker-compose、K8s 部署檔、MIG patch、CI | YAML 語法已檢查；**開發環境沒有 Docker daemon 和 K8s，請在你的電腦上實際跑一次** |

## 還缺什麼才能上正式環境

工作狀態移到 Redis、模型註冊與版本回滾、身分驗證、稽核日誌、DICOM SR 輸出回 PACS，以及 IEC 62304 的軟體生命週期文件。

---

## English summary

A FastAPI service that wraps the P1 lung-nodule detector for production-style use. Requests upload a zipped DICOM series and get a job ID back (inference takes tens of seconds on CPU), and input QC rejects series the model was not trained for, with explicit reasons. Every request's input profile (slice spacing, pixel spacing, manufacturer, HU histogram) is compared with the training distribution using the Population Stability Index. Prometheus metrics cover requests, QC rejections, per-stage latency, findings per study and drift. The model is loaded once at startup and gates the readiness probe, and patient identifiers never appear in responses or logs. Deployment files cover Docker, Docker Compose with Prometheus, Kubernetes (probes, non-root, read-only root filesystem), and a patch that requests an A100 MIG slice (`nvidia.com/mig-1g.5gb`). A C++ ONNX Runtime client reproduces the Python outputs. Tests use a synthetic DICOM phantom and a tiny ONNX model, so they run without real data.
