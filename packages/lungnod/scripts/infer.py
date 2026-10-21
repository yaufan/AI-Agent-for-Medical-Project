"""對單一 CT 序列做推論：DICOM 資料夾 → 結節清單（JSON）與一張檢視圖。

用法：
    python scripts/infer.py --ct <CT 序列資料夾> --model results/nodule_cnn.onnx \
        --gbm results/gbm_final.joblib --threshold 0.5 --out out/
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lungnod import dicom_io  # noqa: E402
from lungnod.inference import NoduleDetector  # noqa: E402


def save_figure(path, hu, sp, origin, idx, prob, top=3):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = np.argsort(prob)[::-1][:top]
    fig, axes = plt.subplots(1, len(order), figsize=(4 * len(order), 4))
    for ax, i in zip(np.atleast_1d(axes), order):
        z, y, x = idx[i]
        ax.imshow(hu[z], cmap="gray", vmin=-1000, vmax=400)
        ax.add_patch(plt.Circle((x, y), 12, fill=False, color="red", lw=1.5))
        ax.set_title(f"p={prob[i]:.2f}  z={origin[0] + z * sp[0]:.0f}mm", fontsize=10)
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ct", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--gbm")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    ct = dicom_io.load_ct(a.ct)
    det = NoduleDetector(a.model, a.gbm, a.threshold)
    report, (hu, sp, idx, prob) = det.detect(ct, keep_arrays=True)
    report["patient_id"] = ct.patient_id
    (out / "findings.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    if len(idx):
        save_figure(out / "top_findings.png", hu, sp, ct.origin, idx, prob)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
