"""從交叉驗證選操作點：用各 fold 存下的 CNN 權重重算測試分數（GBM 依同樣的 seed 重新訓練），
找出「平均每例 N 個誤報」時的分數閾值，給推論與服務當預設值。

同時重算 CPM，確認和 cross_validate.py 的結果一致（可重現性檢查）。

用法：
    python scripts/operating_point.py --cache cache --results results
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cross_validate import load_cache, train_gbm  # noqa: E402
from lungnod import froc  # noqa: E402
from lungnod.model import NoduleNet3D, predict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--results", default="results")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    scans = load_cache(a.cache)
    fold_of = np.random.default_rng(a.seed).permutation(len(scans)) % a.folds   # 與 cross_validate.py 相同
    for k in range(a.folds):
        test = [s for s, f in zip(scans, fold_of) if f == k]
        train = [s for s, f in zip(scans, fold_of) if f != k]
        gbm = train_gbm(train, a.seed)
        cnn = NoduleNet3D()
        cnn.load_state_dict(torch.load(Path(a.results) / f"cnn_fold{k + 1}.pt", map_location="cpu"))
        for s in test:
            s["score"] = (gbm.predict_proba(s["features"])[:, 1] + predict(cnn, s["patches"].astype(np.float32))) / 2
        print(f"fold {k + 1} done", flush=True)

    rows = [{"scores": s["score"], "labels": s["labels"], "hit": s["hit"], "n_targets": len(s["target_diameter_mm"])}
            for s in scans]
    _, _, at, cpm = froc.froc(rows)

    # 每個閾值對應的 (FP/scan, 敏感度)：所有非忽略的候選依分數排序後逐一累計
    events = []
    for r in rows:
        best = {}
        for sc, lb, h in zip(r["scores"], r["labels"], r["hit"]):
            if lb == froc.POS:
                best[h] = max(best.get(h, -1), sc)
            elif lb == froc.NEG:
                events.append((sc, 0))
        events += [(sc, 1) for sc in best.values()]
    events.sort(key=lambda e: -e[0])
    sc = np.array([e[0] for e in events])
    tp = np.cumsum([e[1] for e in events])
    fp = np.cumsum([1 - e[1] for e in events])
    n_t = sum(r["n_targets"] for r in rows)
    ops = {}
    for rate in (0.5, 1, 2, 4):
        ok = np.where(fp / len(rows) <= rate)[0]
        i = ok[-1]
        ops[str(rate)] = {"threshold": round(float(sc[i]), 4), "sensitivity": round(float(tp[i] / n_t), 3),
                          "fp_per_scan": round(float(fp[i] / len(rows)), 2)}
    out = {"method": "B+C_ensemble", "cpm_recomputed": cpm, "operating_points": ops}
    Path(a.results, "operating_points.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
