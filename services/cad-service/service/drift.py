"""資料漂移偵測：拿每次請求的輸入概況，和訓練資料的參考分布比較。

用 PSI（Population Stability Index）：
    PSI = Σ (p_i − q_i) · ln(p_i / q_i)
p 是近期輸入的分布、q 是參考分布。業界常用的經驗值：
    < 0.1 穩定；0.1～0.25 需要留意；> 0.25 明顯漂移
連續數值（切片間距）先用參考資料的分位數切箱；類別值（廠牌、重建核心）直接用類別頻率。
"""
import json
from collections import Counter, deque
from pathlib import Path

import numpy as np

EPS = 1e-4
NUMERIC = ("slice_spacing_mm", "pixel_spacing_mm")
CATEGORICAL = ("manufacturer",)


def psi(p, q):
    p = np.clip(np.asarray(p, float), EPS, None)
    q = np.clip(np.asarray(q, float), EPS, None)
    p, q = p / p.sum(), q / q.sum()
    return float(np.sum((p - q) * np.log(p / q)))


def _edges(cuts):
    return np.concatenate([[-np.inf], np.asarray(cuts, float), [np.inf]])


def build_reference(profiles, n_bins=5):
    """profiles: 訓練資料每個病例的 profile（qc.profile 的輸出）。"""
    ref = {"n": len(profiles), "numeric": {}, "categorical": {}}
    for k in NUMERIC:
        v = np.array([p[k] for p in profiles])
        cuts = np.unique(np.quantile(v, np.linspace(0, 1, n_bins + 1))[1:-1])
        hist = np.histogram(v, bins=_edges(cuts))[0]
        ref["numeric"][k] = {"cuts": cuts.tolist(), "freq": (hist / hist.sum()).tolist()}
    for k in CATEGORICAL:
        c = Counter(p[k] for p in profiles)
        ref["categorical"][k] = {name: n / len(profiles) for name, n in c.items()}
    ref["hu_hist"] = np.mean([p["hu_hist"] for p in profiles], axis=0).tolist()
    return ref


class DriftMonitor:
    """保留最近 window 筆請求的概況，隨時可以算出各特徵的 PSI。

    樣本太少時 PSI 沒有意義：只有 1 筆時分布是一個尖峰，PSI 會大到 5 以上。
    所以累積到 min_samples 筆之前，report() 回傳空字典。
    """

    def __init__(self, reference, window=50, min_samples=20):
        self.ref = reference
        self.recent = deque(maxlen=window)
        self.min_samples = min_samples

    @classmethod
    def from_file(cls, path, window=50, min_samples=20):
        return cls(json.loads(Path(path).read_text()), window, min_samples)

    def add(self, prof):
        self.recent.append(prof)

    def report(self):
        if len(self.recent) < self.min_samples:
            return {}
        out = {}
        for k, r in self.ref["numeric"].items():
            v = np.array([p[k] for p in self.recent])
            out[k] = psi(np.histogram(v, bins=_edges(r["cuts"]))[0], r["freq"])
        for k, freq in self.ref["categorical"].items():
            names = sorted(set(freq) | {p[k] for p in self.recent})
            c = Counter(p[k] for p in self.recent)
            out[k] = psi([c.get(n, 0) for n in names], [freq.get(n, 0) for n in names])
        out["hu_hist"] = psi(np.mean([p["hu_hist"] for p in self.recent], axis=0), self.ref["hu_hist"])
        return out
