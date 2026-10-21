import time

import numpy as np

from conftest import make_series_zip
from service import drift


def _wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/v1/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.5)
    raise TimeoutError(job_id)


def test_health_and_ready(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").json() == {"status": "ready"}


def test_end_to_end_job(client):
    r = client.post("/v1/studies", files={"file": ("ct.zip", make_series_zip(), "application/zip")})
    assert r.status_code == 202, r.text
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "done", job
    res = job["result"]
    assert res["n_candidates"] > 0 and len(res["findings"]) > 0
    assert set(res["timing"]) == {"preprocess_s", "candidates_s", "classify_s"}
    assert "disclaimer" in res
    # 回應不能帶出病人姓名或 ID
    assert "TEST-0001" not in r.text + str(job) and "Phantom" not in str(job)


def test_qc_rejects_thick_slices(client):
    r = client.post("/v1/studies", files={"file": ("ct.zip", make_series_zip(n_slices=70, spacing=5.0),
                                                   "application/zip")})
    assert r.status_code == 422
    assert any("slice_spacing_too_large" in x for x in r.json()["detail"]["reasons"])
    assert 'nodule_qc_rejections_total{reason="slice_spacing_too_large"}' in client.get("/metrics").text


def test_bad_upload(client):
    r = client.post("/v1/studies", files={"file": ("x.zip", b"not a zip", "application/zip")})
    assert r.status_code == 400


def test_unknown_job(client):
    assert client.get("/v1/jobs/doesnotexist").status_code == 404


def test_drift_flags_new_manufacturer(client):
    for _ in range(5):
        r = client.post("/v1/studies", files={"file": ("ct.zip", make_series_zip(manufacturer="GE MEDICAL SYSTEMS"),
                                                       "application/zip")})
        assert r.status_code == 202
    psi = client.get("/v1/drift").json()["psi"]
    assert psi["manufacturer"] > 0.25          # 新廠牌：明顯漂移
    assert psi["slice_spacing_mm"] < 0.1       # 切片間距沒變
    assert 'nodule_input_psi{feature="manufacturer"}' in client.get("/metrics").text


def test_psi_basic():
    assert drift.psi([0.5, 0.5], [0.5, 0.5]) < 1e-9
    assert drift.psi([0.9, 0.1], [0.5, 0.5]) > 0.25
    ref = drift.build_reference([{"slice_spacing_mm": s, "pixel_spacing_mm": 0.7, "manufacturer": "A",
                                  "hu_hist": [1.0]} for s in np.linspace(0.6, 2.5, 50)])
    m = drift.DriftMonitor(ref)
    m.add({"slice_spacing_mm": 0.6, "pixel_spacing_mm": 0.7, "manufacturer": "A", "hu_hist": [1.0]})
    assert m.report() == {}                    # 樣本不足時不回報
    for s in np.linspace(0.6, 2.5, 50):
        m.add({"slice_spacing_mm": s, "pixel_spacing_mm": 0.7, "manufacturer": "A", "hu_hist": [1.0]})
    assert max(m.report().values()) < 0.05
