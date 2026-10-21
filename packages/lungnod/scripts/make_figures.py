"""產生 README 用的圖：流程示意（單一病例）與 FROC 曲線。

用法：
    python scripts/make_figures.py --patient <LIDC-IDRI-xxxx 資料夾> --cache cache --results results --out docs/img
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
from scipy import ndimage as ndi

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lungnod import candidates, dicom_io, froc, preprocess  # noqa: E402


def pipeline_figure(patient_dir, cache_dir, out):
    name = Path(patient_dir).name
    z = np.load(Path(cache_dir) / f"{name}.npz")
    ct_dirs, _ = dicom_io.find_series(patient_dir)
    ct = dicom_io.load_ct(ct_dirs[0])
    hu, sp = preprocess.resample(ct.hu.astype(np.float32), ct.spacing)
    lung = preprocess.lung_mask(hu, sp)
    vol = preprocess.normalize_hu(hu)
    resp = candidates.dot_scale_space(vol, lung)

    # 選最大的目標結節所在的切片
    k = int(np.argmax(z["target_diameter_mm"]))
    c = np.round((z["target_center_mm"][k] - z["origin"]) / z["spacing"]).astype(int)
    s = c[0]
    idx, labels = z["cand_idx"], z["labels"]
    near = np.abs(idx[:, 0] - s) <= 3

    fig, ax = plt.subplots(1, 4, figsize=(16, 4.4))
    ax[0].imshow(hu[s], cmap="gray", vmin=-1000, vmax=400)
    ax[0].set_title("1. CT（肺窗，1 mm 重取樣）")
    ax[1].imshow(hu[s], cmap="gray", vmin=-1000, vmax=400)
    ax[1].contour(lung[s], levels=[0.5], colors="cyan", linewidths=1)
    ax[1].set_title("2. 肺部分割：閾值＋連通元件＋形態學")
    from matplotlib.colors import PowerNorm
    ax[2].imshow(np.where(lung[s], resp[s], 0), cmap="magma",
                 norm=PowerNorm(0.4, vmin=0, vmax=np.percentile(resp[s][lung[s]], 99.9)))
    ax[2].set_title("3. 多尺度 Hessian 點濾波響應")
    ax[3].imshow(hu[s], cmap="gray", vmin=-1000, vmax=400)
    for (zz, yy, xx), lb in zip(idx[near], labels[near]):
        color = {froc.POS: "lime", froc.NEG: "red", froc.IGNORE: "yellow"}[int(lb)]
        ax[3].add_patch(plt.Circle((xx, yy), 6, fill=False, color=color, lw=1.2))
    r = z["target_diameter_mm"][k] / 2 / z["spacing"][2]
    ax[3].add_patch(plt.Circle((c[2], c[1]), r + 4, fill=False, color="lime", lw=2, ls="--"))
    ax[3].set_title("4. 候選點（綠=結節、紅=誤報）")
    for a in ax:
        a.axis("off")
    fig.suptitle(f"{name}（LIDC-IDRI，CC BY 3.0）", fontsize=11)
    fig.tight_layout()
    fig.savefig(Path(out) / "pipeline.png", dpi=100)
    plt.close(fig)


def froc_figure(results_dir, out):
    res = json.loads((Path(results_dir) / "cv_results.json").read_text())
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    labels = {"A1_LoG_only": "A1. 只用 LoG", "A2_Hessian_dot_only": "A2. 只用 Hessian 點濾波",
              "B_handcrafted_GBM": "B. 手工特徵＋GBM",
              "C_3D_CNN": "C. 3D CNN", "B+C_ensemble": "B＋C 平均"}
    for m in res["methods"]:
        cv = m["curve"]
        ax.plot(cv["fp_per_scan"], cv["sensitivity"], drawstyle="steps-post",
                label=f"{labels[m['method']]}（CPM {m['cpm']:.2f}）")
    ax.set_xscale("log", base=2)
    ax.set_xlim(0.125, 16)
    ticks = [0.125, 0.25, 0.5, 1, 2, 4, 8, 16]
    ax.set_xticks(ticks, ["1/8", "1/4", "1/2", "1", "2", "4", "8", "16"])
    ax.set_ylim(0, 1)
    ax.axhline(res["candidate_stage"]["sensitivity"], color="gray", ls=":", lw=1)
    ax.text(0.13, res["candidate_stage"]["sensitivity"] + 0.02, "候選點階段上限", color="gray", fontsize=9)
    ax.set_xlabel("平均每例誤報數（FP/scan）")
    ax.set_ylabel("結節敏感度")
    ax.set_title(f"FROC（{res['n_scans']} 例、{res['n_targets']} 顆結節，{res['folds']}-fold 病例層級交叉驗證）",
                 fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(Path(out) / "froc.png", dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", required=True)
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="docs/img")
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    for f in ["Noto Sans CJK TC", "Noto Sans TC", "Noto Sans CJK JP", "WenQuanYi Zen Hei"]:
        if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    froc_figure(a.results, a.out)
    pipeline_figure(a.patient, a.cache, a.out)


if __name__ == "__main__":
    main()
