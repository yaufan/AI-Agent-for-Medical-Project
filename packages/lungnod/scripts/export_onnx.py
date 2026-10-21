"""把訓練好的 3D CNN 匯出成 ONNX，驗證輸出與 PyTorch 一致，並量測 CPU 推論延遲。

用法：
    python scripts/export_onnx.py --weights results/cnn_final.pt --out results/nodule_cnn.onnx
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lungnod.model import PATCH, NoduleNet3D  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()

    model = NoduleNet3D()
    model.load_state_dict(torch.load(a.weights, map_location="cpu"))
    model.eval()

    dummy = torch.randn(2, 1, PATCH, PATCH, PATCH)
    torch.onnx.export(model, dummy, a.out, input_names=["patch"], output_names=["logit"],
                      dynamic_axes={"patch": {0: "batch"}, "logit": {0: "batch"}}, opset_version=17,
                      dynamo=False)

    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    sess = ort.InferenceSession(a.out, so, providers=["CPUExecutionProvider"])

    x = np.random.rand(300, 1, PATCH, PATCH, PATCH).astype(np.float32)
    with torch.no_grad():
        ref = model(torch.from_numpy(x)).numpy()
    got = sess.run(None, {"patch": x})[0]
    diff = float(np.abs(ref - got).max())

    sess.run(None, {"patch": x[:16]})  # 暖機
    t0 = time.time()
    for i in range(0, 300, 64):
        sess.run(None, {"patch": x[i:i + 64]})
    onnx_ms = (time.time() - t0) * 1000

    t0 = time.time()
    with torch.no_grad():
        for i in range(0, 300, 64):
            model(torch.from_numpy(x[i:i + 64]))
    torch_ms = (time.time() - t0) * 1000

    report = {
        "onnx_file": a.out,
        "size_kb": round(Path(a.out).stat().st_size / 1024, 1),
        "max_abs_diff_vs_torch": diff,
        "cpu_threads": a.threads,
        "ms_per_300_candidates": {"onnxruntime": round(onnx_ms), "pytorch": round(torch_ms)},
    }
    print(json.dumps(report, indent=1))
    Path(a.out).with_suffix(".json").write_text(json.dumps(report, indent=1))
    assert diff < 1e-3, "ONNX 輸出和 PyTorch 不一致"


if __name__ == "__main__":
    main()
