"""結節候選點偵測：多尺度 LoG + Hessian 特徵值分析。

想法：
- 結節在肺窗下是「暗背景中的亮球」，血管是「亮管子」。
- 尺度正規化的 LoG（-σ²∇²G_σ * I）在半徑 r ≈ √3·σ 的亮球中心有最大響應，
  掃過多個 σ 就能同時找到大小不同的結節（scale-space 的 blob detection）。
- 但 LoG 對血管也有響應。用 Hessian 的三個特徵值區分形狀（候選點的第二個來源，也是特徵）：
    亮球： λ1 ≈ λ2 ≈ λ3 < 0
    亮管： λ1 ≈ 0，λ2 ≈ λ3 < 0（沿血管方向沒有曲率）
    亮板： λ1 ≈ λ2 ≈ 0，λ3 < 0
  （這裡依絕對值排序 |λ1| <= |λ2| <= |λ3|）
"""
import numpy as np
from scipy import ndimage as ndi

SIGMAS_MM = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)

FEATURE_NAMES = [
    "log_response", "dot_response", "sigma_mm", "lambda1", "lambda2", "lambda3",
    "blobness", "tubeness", "ratio_12", "ratio_23",
    "mean_hu_core", "std_hu_core", "mean_hu_shell", "dist_to_pleura_mm",
]


def log_scale_space(vol01, sigmas=SIGMAS_MM):
    """回傳 (最大響應, 對應的 σ)。vol01 是 1 mm 等向、[0,1] 正規化的體積。"""
    best = np.full(vol01.shape, -np.inf, dtype=np.float32)
    best_sigma = np.zeros(vol01.shape, dtype=np.float32)
    for s in sigmas:
        r = (-(s ** 2) * ndi.gaussian_laplace(vol01, s)).astype(np.float32)
        upd = r > best
        best[upd] = r[upd]
        best_sigma[upd] = s
    return best, best_sigma


def dot_scale_space(vol01, lung, sigmas=SIGMAS_MM):
    """多尺度 Hessian「點」濾波（Li et al. 2003 的 dot enhancement filter）。

    只在肺遮罩內的像素算特徵值。對每個像素：
        三個特徵值都為負（各方向都是亮的凸起）→ 響應 = |λ1|² / |λ3|
        否則 → 0
    管狀的血管 |λ1| ≈ 0，響應會被壓得很低，這是它比 LoG 好的地方。
    """
    zz, yy, xx = np.nonzero(lung)
    if zz.size == 0:
        return np.zeros(vol01.shape, np.float32)
    bb = tuple(slice(a.min(), a.max() + 1) for a in (zz, yy, xx))
    v, m = vol01[bb], lung[bb]
    best = np.zeros(v.shape, np.float32)
    for s in sigmas:
        H = np.empty((int(m.sum()), 3, 3), np.float32)
        for i in range(3):
            for j in range(i, 3):
                order = [0, 0, 0]
                order[i] += 1
                order[j] += 1
                d = (s ** 2) * ndi.gaussian_filter(v, s, order=order)[m]
                H[:, i, j] = d
                H[:, j, i] = d
        ev = np.linalg.eigvalsh(H)
        a = np.sort(np.abs(ev), axis=1)
        dot = np.where((ev < 0).all(1), a[:, 0] ** 2 / np.maximum(a[:, 2], 1e-6), 0.0)
        tmp = np.zeros(v.shape, np.float32)
        tmp[m] = dot
        np.maximum(best, tmp, out=best)
    out = np.zeros(vol01.shape, np.float32)
    out[bb] = best
    return out


def _peaks(resp, lung, min_distance_mm, min_response, k):
    size = 2 * int(min_distance_mm) + 1
    pk = (resp == ndi.maximum_filter(resp, size=size)) & (resp > min_response) & lung
    idx = np.argwhere(pk)
    order = np.argsort(resp[pk])[::-1][:k]
    return idx[order]


def detect(vol01, lung, n_log=300, n_dot=300, min_distance_mm=4, sigmas=SIGMAS_MM):
    """兩種傳統濾波器各取前 N 個區域最大值，合併後去重複。

    - LoG：對大的、或和血管相連的結節比較穩；
    - Hessian 點濾波：能壓掉血管，小結節（3～6 mm）排名大幅提前。
    只用 LoG 時，4～6 mm 的結節常排在第 400～800 名，被每例 300 個的上限切掉。

    回傳 (idx, log_response, sigma, dot_response)。
    """
    log_resp, log_sigma = log_scale_space(vol01, sigmas)
    dot_resp = dot_scale_space(vol01, lung, sigmas)
    a = _peaks(log_resp, lung, min_distance_mm, 0.02, n_log)
    b = _peaks(dot_resp, lung, min_distance_mm, 1e-3, n_dot)
    if len(a) and len(b):
        d = np.linalg.norm(b[:, None, :] - a[None, :, :], axis=2).min(1)
        b = b[d > 3]
    idx = np.concatenate([a, b]).astype(int) if len(a) + len(b) else np.zeros((0, 3), int)
    t = tuple(idx.T)
    return idx, log_resp[t], log_sigma[t], dot_resp[t]


def hessian_eigs(vol01, center, sigma):
    """只在候選點附近的小區塊算 Hessian（比整個體積算 6 個導數濾波快得多）。"""
    m = int(np.ceil(4 * sigma)) + 2
    sl = tuple(slice(max(c - m, 0), min(c + m + 1, n)) for c, n in zip(center, vol01.shape))
    patch = vol01[sl]
    c = tuple(int(ci - s.start) for ci, s in zip(center, sl))
    H = np.zeros((3, 3))
    for i in range(3):
        for j in range(i, 3):
            order = [0, 0, 0]
            order[i] += 1
            order[j] += 1
            d = ndi.gaussian_filter(patch, sigma, order=order, mode="nearest")
            H[i, j] = H[j, i] = (sigma ** 2) * d[c]
    ev = np.linalg.eigvalsh(H)
    return ev[np.argsort(np.abs(ev))]     # |λ1| <= |λ2| <= |λ3|


def candidate_features(vol01, hu, lung, idx, log_resp, sigma, dot_resp):
    """每個候選點的手工特徵，給傳統分類器（Gradient Boosting）使用。"""
    dist = ndi.distance_transform_edt(lung)  # 到肺邊界（肋膜）的距離，1 mm 等向所以單位就是 mm
    feats = []
    for p, r, s, dr in zip(idx, log_resp, sigma, dot_resp):
        l1, l2, l3 = hessian_eigs(vol01, p, s)
        a1, a2, a3 = abs(l1), abs(l2), abs(l3)
        all_neg = (l1 < 0) and (l2 < 0) and (l3 < 0)
        blob = (a1 ** 2 / a3) if (all_neg and a3 > 0) else 0.0         # Li et al. dot filter
        tube = (a2 * (a2 - a1) / a3) if (l2 < 0 and l3 < 0 and a3 > 0) else 0.0  # Li et al. line filter

        rad = max(1.0, np.sqrt(3) * s)
        core, shell = _sphere_stats(hu, p, rad)
        feats.append([
            r, dr, s, l1, l2, l3, blob, tube,
            a1 / (a2 + 1e-6), a2 / (a3 + 1e-6),
            core[0], core[1], shell, dist[tuple(p)],
        ])
    return np.asarray(feats, dtype=np.float32)


def _sphere_stats(hu, center, radius):
    r_out = int(np.ceil(radius * 2))
    sl = tuple(slice(max(c - r_out, 0), min(c + r_out + 1, n)) for c, n in zip(center, hu.shape))
    patch = hu[sl].astype(np.float32)
    grids = np.meshgrid(*[np.arange(s.start, s.stop) - c for s, c in zip(sl, center)], indexing="ij")
    d = np.sqrt(sum(g ** 2 for g in grids))
    inner = patch[d <= radius]
    outer = patch[(d > radius) & (d <= 2 * radius)]
    core = (float(inner.mean()), float(inner.std())) if inner.size else (0.0, 0.0)
    shell = float(outer.mean()) if outer.size else 0.0
    return core, shell


def extract_patch(vol01, center, size):
    """以 center 為中心切出 size³ 的方塊，超出邊界補 0（空氣）。"""
    half = size // 2
    out = np.zeros((size, size, size), dtype=np.float32)
    src, dst = [], []
    for c, n in zip(center, vol01.shape):
        lo, hi = c - half, c - half + size
        src.append(slice(max(lo, 0), min(hi, n)))
        dst.append(slice(max(lo, 0) - lo, size - (hi - min(hi, n))))
    out[tuple(dst)] = vol01[tuple(src)]
    return out
