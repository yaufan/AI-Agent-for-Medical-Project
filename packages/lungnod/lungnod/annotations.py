"""把多位醫師的 SEG 標註合併成「結節清單」。

LIDC-IDRI 每個病例由最多 4 位放射科醫師各自獨立標註，同一顆結節會有多份 SEG。
這裡依 LUNA16 的慣例：
- 把不同醫師對同一顆結節的標註合併（IDC 已提供分群編號；沒有時用距離合併）；
- 至少 3 位醫師都標到、直徑 >= 3 mm 的，當作評估用的「目標結節」；
- 只有 1～2 位醫師標到的，當作「不確定」，評估時既不算偵測到也不算誤報。
"""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi


@dataclass(eq=False)  # 含 numpy 陣列，用物件本身比較
class Nodule:
    center_mm: np.ndarray            # (z, y, x) 世界座標
    diameter_mm: float
    n_readers: int


def mask_to_measure(mask, spacing, origin):
    """遮罩 → (質心 mm, 等體積球直徑 mm)。"""
    idx = np.array(ndi.center_of_mass(mask))
    center = origin + idx * spacing
    volume = mask.sum() * float(np.prod(spacing))
    diameter = (6.0 * volume / np.pi) ** (1.0 / 3.0)
    return center, diameter


def merge_annotations(annotations, spacing, origin):
    """annotations: list[SegAnnotation]，回傳 list[Nodule]。

    有分群編號（IDC 的 "Nodule N"）就照編號分群，一群的標註數 = 標到的醫師數；
    沒有的話退回用距離分群：兩份標註質心距離小於較大者的半徑 + 1 mm 就視為同一顆。
    """
    items = []
    for a in annotations:
        c, d = mask_to_measure(a.mask, spacing, origin)
        items.append((c, d, a.group))

    if items and all(g is not None for _, _, g in items):
        keys = [g for _, _, g in items]
    else:
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ci, di, _), (cj, dj, _) = items[i], items[j]
                if np.linalg.norm(ci - cj) <= max(di, dj) / 2 + 1.0:
                    parent[find(i)] = find(j)
        keys = [find(i) for i in range(len(items))]

    groups = {}
    for k, it in zip(keys, items):
        groups.setdefault(k, []).append(it)

    nodules = []
    for g in groups.values():
        centers = np.array([c for c, _, _ in g])
        diams = np.array([d for _, d, _ in g])
        nodules.append(Nodule(center_mm=centers.mean(0), diameter_mm=float(diams.mean()),
                              n_readers=min(len(g), 4)))
    return nodules


def split_targets(nodules, min_readers=3, min_diameter=3.0):
    targets = [n for n in nodules if n.n_readers >= min_readers and n.diameter_mm >= min_diameter]
    ignore = [n for n in nodules if not any(n is t for t in targets)]
    return targets, ignore
