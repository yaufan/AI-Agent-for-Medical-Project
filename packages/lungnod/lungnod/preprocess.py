"""重取樣與肺部遮罩（全部用傳統影像處理，不用深度學習）。"""
import numpy as np
from scipy import ndimage as ndi


def resample(volume, spacing, new_spacing=(1.0, 1.0, 1.0), order=1):
    """把體積重取樣到等向性解析度。

    不同 CT 的切片厚度從 0.6 到 2.5 mm 都有，先統一成 1 mm 等向，
    後面的濾波器尺度（mm）和 CNN 的輸入大小才有一致的物理意義。
    order=1 是三線性內插（影像），遮罩要用 order=0（最近鄰）以免出現小數。
    """
    spacing = np.asarray(spacing, dtype=float)
    new_spacing = np.asarray(new_spacing, dtype=float)
    zoom = spacing / new_spacing
    out = ndi.zoom(volume, zoom, order=order, mode="nearest", prefilter=False)
    # zoom 會四捨五入輸出大小；scipy 預設讓首尾像素中心對齊，
    # 所以實際 spacing = 原 spacing × (原像素數-1)/(新像素數-1)
    real_spacing = spacing * (np.array(volume.shape) - 1) / (np.array(out.shape) - 1)
    return out, real_spacing


def _largest_components(labels, n):
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = np.argsort(sizes)[::-1][:n]
    return [k for k in keep if sizes[k] > 0], sizes


def lung_mask(hu, spacing=(1.0, 1.0, 1.0), threshold=-320, closing_mm=5.0):
    """傳統方法分割肺部。

    步驟：
    1. 閾值：HU < -320 的是空氣或肺（肺實質約 -900～-500 HU）。
    2. 去掉體外空氣：逐張切片，把和影像邊界相連的空氣元件移除
       （病人身體外、檢查床下方的空氣都碰得到邊界，肺碰不到）。
    3. 3D 連通元件：留下最大的兩塊（左右肺；若經氣管相連就是一塊）。
    4. 補洞：肺裡的血管、結節 HU 高於閾值，會變成洞，逐張填補。
    5. 閉運算：把貼著肋膜的結節包回來（這是傳統方法最常漏掉的地方）。
    """
    air = hu < threshold

    body_air_free = np.zeros_like(air)
    for z in range(air.shape[0]):
        lab, n = ndi.label(air[z])
        if n == 0:
            continue
        border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        inside = ~np.isin(lab, border)
        body_air_free[z] = inside & (lab > 0)

    lab3d, n = ndi.label(body_air_free)
    if n == 0:
        return np.zeros_like(air)
    keep, sizes = _largest_components(lab3d, 2)
    # 第二大元件如果小於最大元件的 10%，通常是腸氣或氣管，不算肺
    if len(keep) == 2 and sizes[keep[1]] < 0.1 * sizes[keep[0]]:
        keep = keep[:1]
    mask = np.isin(lab3d, keep)

    for z in range(mask.shape[0]):
        mask[z] = ndi.binary_fill_holes(mask[z])

    r = np.maximum(1, np.round(closing_mm / np.asarray(spacing))).astype(int)
    zz, yy, xx = np.ogrid[-r[0]:r[0] + 1, -r[1]:r[1] + 1, -r[2]:r[2] + 1]
    ball = (zz / r[0]) ** 2 + (yy / r[1]) ** 2 + (xx / r[2]) ** 2 <= 1
    # 先在邊緣墊空白再閉運算，避免影像邊界造成侵蝕
    pad = r.max()
    mask = ndi.binary_closing(np.pad(mask, pad), structure=ball)[pad:-pad, pad:-pad, pad:-pad]
    for z in range(mask.shape[0]):
        mask[z] = ndi.binary_fill_holes(mask[z])
    return mask


def normalize_hu(hu, lo=-1000.0, hi=400.0):
    """肺窗附近的 HU 線性映射到 [0, 1]，給濾波器與 CNN 使用。"""
    return np.clip((hu.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)
