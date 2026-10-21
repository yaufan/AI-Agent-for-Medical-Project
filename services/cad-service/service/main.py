"""肺結節偵測推論服務。

API：
    POST /v1/studies          上傳一個 CT 序列（DICOM 檔打包成 zip）→ 202 + job_id；QC 不通過 → 422
    GET  /v1/jobs/{job_id}    查詢工作狀態與結果
    GET  /healthz             存活檢查（liveness）
    GET  /readyz              就緒檢查（readiness）：模型已載入才回 200
    GET  /metrics             Prometheus 指標
    GET  /v1/drift            近期輸入和訓練資料的 PSI

設計重點：
- 一次 CT 推論在 CPU 上要數十秒到數分鐘，所以用「送出工作、之後查結果」的非同步模式，
  不讓 HTTP 連線一直掛著。工作數量用執行緒池限制，避免同時塞爆記憶體。
- QC 在送出工作前就做，不合格的輸入直接拒收並說明原因。
- 日誌和回應都不放病人姓名、ID 等個資，只用 SeriesInstanceUID 與 job_id 追蹤。
- 正式環境的工作狀態要放 Redis 或資料庫；這裡為了簡單放在記憶體。
"""
import io
import logging
import os
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from lungnod import dicom_io
from lungnod.inference import NoduleDetector

from . import qc
from .drift import DriftMonitor

log = logging.getLogger("nodule-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODEL_PATH = os.environ.get("MODEL_PATH", "models/nodule_cnn.onnx")
GBM_PATH = os.environ.get("GBM_PATH") or None
REFERENCE_PATH = os.environ.get("REFERENCE_PATH", "models/reference_profile.json")
THRESHOLD = float(os.environ.get("THRESHOLD", "0.567"))   # P1 的 1 FP/scan 操作點
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "1"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "800"))
ORT_THREADS = int(os.environ.get("ORT_THREADS", "4"))
ORT_PROVIDERS = os.environ.get("ORT_PROVIDERS", "CPUExecutionProvider").split(",")
DRIFT_WINDOW = int(os.environ.get("DRIFT_WINDOW", "50"))
DRIFT_MIN_SAMPLES = int(os.environ.get("DRIFT_MIN_SAMPLES", "20"))

REQUESTS = Counter("nodule_requests_total", "API 請求數", ["endpoint", "status"])
QC_REJECT = Counter("nodule_qc_rejections_total", "QC 拒收次數", ["reason"])
STAGE_SECONDS = Histogram("nodule_stage_seconds", "各階段耗時", ["stage"],
                          buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160, 320))
JOBS = Gauge("nodule_jobs", "目前工作數", ["state"])
FINDINGS = Histogram("nodule_findings_per_study", "每例回報的結節數", buckets=(0, 1, 2, 3, 5, 10))
DRIFT = Gauge("nodule_input_psi", "近期輸入與訓練資料的 PSI", ["feature"])

state = {"detector": None, "drift": None, "jobs": {}, "lock": threading.Lock(), "pool": None}


@asynccontextmanager
async def lifespan(app):
    # 模型只在啟動時載入一次；載入失敗 readiness 就不會通過，K8s 不會把流量導過來
    state["detector"] = NoduleDetector(MODEL_PATH, GBM_PATH, THRESHOLD, ORT_THREADS, ORT_PROVIDERS)
    if Path(REFERENCE_PATH).exists():
        state["drift"] = DriftMonitor.from_file(REFERENCE_PATH, DRIFT_WINDOW, DRIFT_MIN_SAMPLES)
    state["pool"] = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    log.info("model loaded: %s (gbm=%s, threshold=%.2f, providers=%s)", MODEL_PATH, bool(GBM_PATH), THRESHOLD,
             state["detector"].session.get_providers())
    yield
    state["pool"].shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Lung nodule detection (research use only)", lifespan=lifespan)


def _set_job(job_id, **kw):
    with state["lock"]:
        state["jobs"][job_id].update(kw)
        counts = {}
        for j in state["jobs"].values():
            counts[j["status"]] = counts.get(j["status"], 0) + 1
    for s in ("queued", "running", "done", "failed"):
        JOBS.labels(s).set(counts.get(s, 0))


def _run_job(job_id, ct):
    _set_job(job_id, status="running", started=time.time())
    try:
        report, _ = state["detector"].detect(ct)
        for stage, sec in report["timing"].items():
            STAGE_SECONDS.labels(stage.removesuffix("_s")).observe(sec)
        FINDINGS.observe(len(report["findings"]))
        _set_job(job_id, status="done", result=report, finished=time.time())
        log.info("job %s done: series=%s findings=%d", job_id, ct.series_uid, len(report["findings"]))
    except Exception as e:  # 工作失敗要記錄，不能讓執行緒默默死掉
        log.exception("job %s failed", job_id)
        _set_job(job_id, status="failed", error=type(e).__name__, finished=time.time())


@app.post("/v1/studies", status_code=202)
async def submit(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        REQUESTS.labels("submit", "413").inc()
        raise HTTPException(413, f"upload larger than {MAX_UPLOAD_MB} MB")

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for m in z.infolist():
                    # 防 zip slip：只取檔名，不照壓縮檔內的路徑解開
                    if not m.is_dir() and m.filename.lower().endswith(".dcm"):
                        Path(tmp, f"{len(os.listdir(tmp)):05d}.dcm").write_bytes(z.read(m))
            ct = dicom_io.load_ct(tmp)
        except (zipfile.BadZipFile, ValueError) as e:
            REQUESTS.labels("submit", "400").inc()
            raise HTTPException(400, f"cannot read CT series: {e}")
    STAGE_SECONDS.labels("load").observe(time.time() - t0)

    result = qc.check(ct)
    if not result.ok:
        for r in result.reasons:
            QC_REJECT.labels(r.split(":")[0]).inc()
        REQUESTS.labels("submit", "422").inc()
        raise HTTPException(422, {"qc": "rejected", "reasons": result.reasons})

    if state["drift"] is not None:
        state["drift"].add(qc.profile(ct))
        for k, v in state["drift"].report().items():
            DRIFT.labels(k).set(v)

    job_id = uuid.uuid4().hex[:12]
    with state["lock"]:
        state["jobs"][job_id] = {"status": "queued", "series_uid": ct.series_uid, "submitted": time.time()}
    _set_job(job_id)
    state["pool"].submit(_run_job, job_id, ct)
    REQUESTS.labels("submit", "202").inc()
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    with state["lock"]:
        job = state["jobs"].get(job_id)
        job = dict(job) if job else None
    if job is None:
        REQUESTS.labels("job", "404").inc()
        raise HTTPException(404, "job not found")
    REQUESTS.labels("job", "200").inc()
    return {"job_id": job_id, **job}


@app.get("/v1/drift")
def drift():
    if state["drift"] is None:
        return {"enabled": False}
    m = state["drift"]
    psi = m.report()
    return {"enabled": True, "samples": len(m.recent), "min_samples": m.min_samples,
            "status": "ok" if psi else "insufficient_samples", "psi": psi,
            "guide": "PSI < 0.1 穩定；0.1-0.25 留意；> 0.25 明顯漂移"}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if state["detector"] is None:
        raise HTTPException(503, "model not loaded")
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
