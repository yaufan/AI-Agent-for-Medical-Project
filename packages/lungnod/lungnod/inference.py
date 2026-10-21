"""推論：CT 體積 → 結節清單。模型只在建構時載入一次，供 CLI（scripts/infer.py）與服務（P2）共用。"""
import time

import joblib
import numpy as np
import onnxruntime as ort

from . import candidates, preprocess
from .patches import PATCH, STORE, center_crop

DISCLAIMER = "研究用途，非醫療器材，不可用於臨床診斷"


class NoduleDetector:
    def __init__(self, model_path, gbm_path=None, threshold=0.5, threads=4, providers=("CPUExecutionProvider",)):
        """providers 例：("CUDAExecutionProvider", "CPUExecutionProvider")，需安裝 onnxruntime-gpu。"""
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_path), so, providers=list(providers))
        self.input_name = self.session.get_inputs()[0].name
        self.gbm = joblib.load(gbm_path) if gbm_path else None
        self.threshold = threshold

    def _cnn(self, patches):
        """和交叉驗證相同的 TTA：原圖與三軸同時翻轉的平均（見 model.predict 的 tta=2）。"""
        if len(patches) == 0:
            return np.zeros(0, np.float32)
        probs = []
        for x in (patches, np.ascontiguousarray(patches[:, :, ::-1, ::-1, ::-1])):
            logits = np.concatenate([self.session.run(None, {self.input_name: x[i:i + 64]})[0]
                                     for i in range(0, len(x), 64)])
            probs.append(1 / (1 + np.exp(-logits)))
        return np.mean(probs, axis=0)

    def detect(self, ct, keep_arrays=False):
        """ct: dicom_io.CTVolume。回傳 (report dict, 額外陣列或 None)。"""
        t = {}
        t0 = time.time()
        hu, sp = preprocess.resample(ct.hu.astype(np.float32), ct.spacing)
        lung = preprocess.lung_mask(hu, sp)
        vol = preprocess.normalize_hu(hu)
        t["preprocess_s"] = time.time() - t0

        t0 = time.time()
        idx, score, sigma, dot = candidates.detect(vol, lung)
        patches = np.stack([center_crop(candidates.extract_patch(vol, p, STORE)) for p in idx])[:, None] \
            if len(idx) else np.zeros((0, 1, PATCH, PATCH, PATCH), np.float32)
        t["candidates_s"] = time.time() - t0

        t0 = time.time()
        prob = self._cnn(patches.astype(np.float32))
        if self.gbm is not None and len(idx):
            feats = candidates.candidate_features(vol, hu, lung, idx, score, sigma, dot)
            prob = (prob + self.gbm.predict_proba(feats)[:, 1]) / 2
        t["classify_s"] = time.time() - t0

        order = np.argsort(prob)[::-1]
        order = order[prob[order] >= self.threshold]
        # 同一顆大結節常有好幾個候選點都過閾值：落在已保留結果半徑內的就合併（保留分數最高的）
        kept = []
        for i in order:
            c = idx[i] * sp
            if all(np.linalg.norm(c - idx[j] * sp) > max(5.0, np.sqrt(3) * sigma[j]) for j in kept):
                kept.append(i)
        findings = []
        for i in kept:
            mm = ct.origin + idx[i] * sp
            findings.append({
                "probability": round(float(prob[i]), 3),
                "center_mm_xyz": [round(float(v), 1) for v in mm[::-1]],   # DICOM 慣例 (x, y, z)
                "slice_index": int(np.argmin(np.abs(ct.z_positions - mm[0]))),
                "approx_diameter_mm": round(float(2 * np.sqrt(3) * sigma[i]), 1),
            })
        report = {
            "series_uid": ct.series_uid,
            "n_candidates": int(len(idx)), "threshold": self.threshold, "findings": findings,
            "lung_volume_ml": round(float(lung.sum() * np.prod(sp) / 1000), 0),
            "timing": {k: round(v, 2) for k, v in t.items()},
            "disclaimer": DISCLAIMER,
        }
        extra = (hu, sp, idx, prob) if keep_arrays else None
        return report, extra
