"""以病例為單位的 K-fold 交叉驗證，比較三種「降低誤報」方法：

  A. 只用濾波器響應排序（純傳統，無學習）：A1 LoG、A2 Hessian 點濾波
  B. 手工特徵（Hessian 特徵值、HU 統計、距肋膜距離）+ Gradient Boosting
  C. 3D CNN（以候選點為中心的 32³ 區塊）

同一個病例的所有候選點只會出現在訓練或測試其中一邊，避免資料洩漏。

用法：
    python scripts/cross_validate.py --cache cache --out results --folds 4
"""
import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lungnod import froc  # noqa: E402
from lungnod.model import NoduleNet3D, augment, predict  # noqa: E402


def load_cache(cache_dir):
    scans = []
    for f in sorted(Path(cache_dir).glob("*.npz")):
        z = np.load(f)
        scans.append({k: z[k] for k in z.files})
    return scans


def train_cnn(train_scans, epochs, samples_per_epoch, seed, log=print):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    pos, neg = [], []
    for s in train_scans:
        lb = s["labels"]
        pos += list(s["patches"][lb == froc.POS])
        pos += list(s["target_patches"])            # 醫師標註中心也當正樣本
        neg += list(s["patches"][lb == froc.NEG])
    log(f"    CNN 訓練樣本：正 {len(pos)}、負 {len(neg)}")

    model = NoduleNet3D()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    steps = epochs * (samples_per_epoch // 64)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, total_steps=steps)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    model.train()
    for ep in range(epochs):
        t0, tot = time.time(), 0.0
        for _ in range(samples_per_epoch // 64):
            # 每個 batch 正負各半（類別極度不平衡：正樣本不到 2%）
            ip = rng.integers(0, len(pos), 32)
            ineg = rng.integers(0, len(neg), 32)
            x = np.stack([augment(pos[i].astype(np.float32), rng) for i in ip] +
                         [augment(neg[i].astype(np.float32), rng) for i in ineg])
            y = torch.cat([torch.ones(32), torch.zeros(32)])
            opt.zero_grad()
            loss = loss_fn(model(torch.from_numpy(x)[:, None]), y)
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item()
        log(f"    epoch {ep + 1}/{epochs} loss={tot / (samples_per_epoch // 64):.3f} ({time.time() - t0:.0f}s)")
    return model


def train_gbm(train_scans, seed):
    X = np.concatenate([s["features"][s["labels"] != froc.IGNORE] for s in train_scans])
    y = np.concatenate([s["labels"][s["labels"] != froc.IGNORE] for s in train_scans])
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, class_weight="balanced",
                                         random_state=seed)
    return clf.fit(X, y)


def summarize(name, scans, scores_key):
    rows = [{"scores": s[scores_key], "labels": s["labels"], "hit": s["hit"],
             "n_targets": len(s["target_diameter_mm"])} for s in scans]
    fpr, sens, at, cpm = froc.froc(rows)
    lo, hi = froc.bootstrap_cpm(rows)
    # 曲線只存敏感度上升的點（畫圖時用 steps-post 就能還原階梯），檔案小很多
    step = np.r_[True, np.diff(sens) > 0]
    step[-1] = True
    return {"method": name, "cpm": cpm, "cpm_95ci": [lo, hi],
            "sens_at_fp": dict(zip([str(r) for r in froc.FP_RATES], at.tolist())),
            "curve": {"fp_per_scan": np.round(fpr[step], 4).tolist(), "sensitivity": np.round(sens[step], 4).tolist()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--out", default="results")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--samples-per-epoch", type=int, default=3200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--final", action="store_true", help="交叉驗證後，再用全部病例訓練一個最終模型給推論用")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "cv_log.txt", "w")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    scans = load_cache(a.cache)
    n_targets = sum(len(s["target_diameter_mm"]) for s in scans)
    log(f"病例 {len(scans)}，目標結節 {n_targets}")

    rng = np.random.default_rng(a.seed)
    fold_of = rng.permutation(len(scans)) % a.folds
    for k in range(a.folds):
        test = [s for s, f in zip(scans, fold_of) if f == k]
        train = [s for s, f in zip(scans, fold_of) if f != k]
        log(f"Fold {k + 1}/{a.folds}：訓練 {len(train)} 例、測試 {len(test)} 例")
        gbm = train_gbm(train, a.seed)
        t0 = time.time()
        cnn = train_cnn(train, a.epochs, a.samples_per_epoch, a.seed + k, log)
        log(f"    CNN 訓練時間 {time.time() - t0:.0f}s")
        for s in test:
            s["score_log"] = s["cand_score"]
            s["score_dot"] = s["cand_dot"]
            s["score_gbm"] = gbm.predict_proba(s["features"])[:, 1] if len(s["features"]) else np.zeros(0)
            s["score_cnn"] = predict(cnn, s["patches"].astype(np.float32))
            s["score_ens"] = (s["score_gbm"] + s["score_cnn"]) / 2
        torch.save(cnn.state_dict(), out / f"cnn_fold{k + 1}.pt")

    # 候選點階段能達到的最高敏感度（之後的分類器只能在這個上限內排序）
    found = sum(len(set(s["hit"][s["labels"] == froc.POS])) for s in scans)
    cand_per_scan = float(np.mean([len(s["cand_score"]) for s in scans]))

    # 依結節大小分層的候選點敏感度
    size_bins = {"3-6mm": (3, 6), "6-10mm": (6, 10), ">=10mm": (10, 1e9)}
    by_size = {}
    for name, (lo, hi) in size_bins.items():
        tot = hit = 0
        for s in scans:
            got = set(s["hit"][s["labels"] == froc.POS])
            for i, d in enumerate(s["target_diameter_mm"]):
                if lo <= d < hi:
                    tot += 1
                    hit += int(i in got)
        by_size[name] = {"n": tot, "candidate_sensitivity": hit / tot if tot else None}

    results = {
        "n_scans": len(scans), "n_targets": n_targets, "folds": a.folds,
        "candidate_stage": {"sensitivity": found / n_targets, "candidates_per_scan": cand_per_scan,
                            "by_size": by_size},
        "methods": [summarize("A1_LoG_only", scans, "score_log"),
                    summarize("A2_Hessian_dot_only", scans, "score_dot"),
                    summarize("B_handcrafted_GBM", scans, "score_gbm"),
                    summarize("C_3D_CNN", scans, "score_cnn"),
                    summarize("B+C_ensemble", scans, "score_ens")],
        "timing_sec_per_scan": {
            "preprocess": float(np.mean([s["timing"][0] for s in scans])),
            "candidates_features": float(np.mean([s["timing"][1] for s in scans])),
        },
    }
    (out / "cv_results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    log(f"候選點敏感度 {found}/{n_targets} = {found / n_targets:.3f}，平均 {cand_per_scan:.0f} 個候選/例")
    for m in results["methods"]:
        log(f"{m['method']:20s} CPM={m['cpm']:.3f} (95% CI {m['cpm_95ci'][0]:.3f}-{m['cpm_95ci'][1]:.3f}) "
            + " ".join(f"{k}:{v:.2f}" for k, v in m["sens_at_fp"].items()))

    if a.final:
        log("用全部病例訓練最終模型")
        joblib.dump(train_gbm(scans, a.seed), out / "gbm_final.joblib")
        torch.save(train_cnn(scans, a.epochs, a.samples_per_epoch, a.seed, log).state_dict(),
                   out / "cnn_final.pt")


if __name__ == "__main__":
    main()
