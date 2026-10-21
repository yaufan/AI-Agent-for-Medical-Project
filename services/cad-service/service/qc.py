"""輸入品質檢查（QC）與輸入概況（profile）。

QC 不通過就直接拒收並回報原因，不要讓模型在它沒看過的條件下硬推論。
profile 是每次請求的輸入摘要，用來和訓練資料比對、偵測資料漂移。
這兩件事都只用 DICOM 標頭和原始 HU，不需要跑模型，所以很快。
"""
from dataclasses import dataclass, field

import numpy as np

# 與 P1 訓練資料一致的允收條件
MAX_SLICE_SPACING_MM = 2.5
MIN_SLICES = 60
HU_BINS = np.arange(-1000, 401, 100)   # 肺窗附近的 HU 分布


@dataclass
class QCResult:
    ok: bool
    reasons: list = field(default_factory=list)


def check(ct):
    """ct: lungnod.dicom_io.CTVolume"""
    reasons = []
    dz, dy, dx = ct.spacing
    if dz > MAX_SLICE_SPACING_MM:
        reasons.append(f"slice_spacing_too_large: {dz:.2f} mm > {MAX_SLICE_SPACING_MM} mm")
    if ct.hu.shape[0] < MIN_SLICES:
        reasons.append(f"too_few_slices: {ct.hu.shape[0]} < {MIN_SLICES}")
    if not (0.4 <= dy <= 1.0 and 0.4 <= dx <= 1.0):
        reasons.append(f"pixel_spacing_out_of_range: {dy:.2f} x {dx:.2f} mm")
    gaps = np.diff(ct.z_positions)
    if len(gaps) and (gaps.max() - gaps.min()) > 0.1 * dz + 1e-3:
        reasons.append("non_uniform_slice_spacing")
    return QCResult(ok=not reasons, reasons=reasons)


def profile(ct):
    """每次請求的輸入摘要。HU 分布只抽 1/4 的切片計算，約 0.1 秒。"""
    sample = ct.hu[::4].ravel()
    hist, _ = np.histogram(np.clip(sample, HU_BINS[0], HU_BINS[-1]), bins=HU_BINS)
    return {
        "slice_spacing_mm": float(ct.spacing[0]),
        "pixel_spacing_mm": float(ct.spacing[1]),
        "n_slices": int(ct.hu.shape[0]),
        "manufacturer": ct.manufacturer or "unknown",
        "kernel": ct.kernel or "unknown",
        "hu_hist": (hist / max(hist.sum(), 1)).tolist(),
    }
