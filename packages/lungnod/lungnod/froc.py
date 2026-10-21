"""候選點標記與 FROC 評估（依 LUNA16 的規則）。

- 候選點落在目標結節半徑內 → 命中該結節（同一顆被多個候選命中只算一次，取最高分）。
- 落在「不確定結節」（只有 1～2 位醫師標到）半徑內 → 忽略，不算命中也不算誤報。
- 其餘 → 誤報（FP）。
- FROC：橫軸是平均每個病例的誤報數，縱軸是結節層級的敏感度。
  CPM = 在 1/8, 1/4, 1/2, 1, 2, 4, 8 FP/scan 七個點的敏感度平均。
"""
import numpy as np

FP_RATES = (0.125, 0.25, 0.5, 1, 2, 4, 8)

POS, NEG, IGNORE = 1, 0, -1


def label_candidates(cand_mm, targets, ignore):
    """回傳 (labels, hit_index)。hit_index 是命中的目標結節編號（沒命中為 -1）。"""
    labels = np.full(len(cand_mm), NEG, dtype=np.int8)
    hit = np.full(len(cand_mm), -1, dtype=np.int32)
    for i, c in enumerate(cand_mm):
        for k, n in enumerate(targets):
            if np.linalg.norm(c - n.center_mm) <= n.diameter_mm / 2:
                labels[i], hit[i] = POS, k
                break
        else:
            if any(np.linalg.norm(c - n.center_mm) <= n.diameter_mm / 2 for n in ignore):
                labels[i] = IGNORE
    return labels, hit


def froc(scans):
    """scans: list[dict]，每個 dict 有 scores, labels, hit, n_targets。

    回傳 (fp_per_scan 陣列, sensitivity 陣列, 各 FP 率下的敏感度, CPM)。
    """
    n_scans = len(scans)
    total_targets = sum(s["n_targets"] for s in scans)
    if total_targets == 0:
        raise ValueError("沒有目標結節，無法計算 FROC")

    # 每顆目標結節只保留命中它的最高分；FP 全部保留
    events = []   # (score, is_tp)
    for si, s in enumerate(scans):
        best = {}
        for sc, lb, h in zip(s["scores"], s["labels"], s["hit"]):
            if lb == POS:
                best[h] = max(best.get(h, -np.inf), sc)
            elif lb == NEG:
                events.append((sc, 0))
        events.extend((sc, 1) for sc in best.values())

    events.sort(key=lambda e: -e[0])
    is_tp = np.array([e[1] for e in events])
    tp = np.cumsum(is_tp)
    fp = np.cumsum(1 - is_tp)
    sens = tp / total_targets
    fpr = fp / n_scans

    at = []
    for r in FP_RATES:
        ok = fpr <= r
        at.append(float(sens[ok].max()) if ok.any() else 0.0)
    return fpr, sens, np.array(at), float(np.mean(at))


def bootstrap_cpm(scans, n_boot=1000, seed=0):
    """以「病例」為單位重抽樣，估計 CPM 的 95% 信賴區間。"""
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = [scans[i] for i in rng.integers(0, len(scans), len(scans))]
        if sum(s["n_targets"] for s in pick) == 0:
            continue
        vals.append(froc(pick)[3])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
