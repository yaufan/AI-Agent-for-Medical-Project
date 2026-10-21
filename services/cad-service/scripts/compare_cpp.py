"""確認 C++ 推論和 Python（onnxruntime）的輸出一致，並比較延遲。

用法：
    python scripts/compare_cpp.py --model <model.onnx> --binary cpp/build/nodule_infer \
        [--cache <P1 的 cache/xxx.npz>] [--n 300]
沒給 --cache 就用隨機區塊。
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "lungnod"))
from lungnod.patches import PATCH, center_crop  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--cache")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()

    if a.cache:
        z = np.load(a.cache)
        x = np.stack([center_crop(p.astype(np.float32)) for p in z["patches"][:a.n]])
    else:
        x = np.random.default_rng(0).random((a.n, PATCH, PATCH, PATCH), dtype=np.float32)
    x = np.ascontiguousarray(x[:, None])

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp, "patches.bin")
        with open(f, "wb") as fh:
            fh.write(np.int32(len(x)).tobytes())
            fh.write(x.astype("<f4").tobytes())
        t0 = time.time()
        r = subprocess.run([a.binary, a.model, str(f), str(a.threads)], capture_output=True, text=True, check=True)
        cpp_wall = time.time() - t0
    cpp = np.array([float(v) for v in r.stdout.split()])
    cpp_timing = dict(kv.split("=") for kv in r.stderr.split())

    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    sess = ort.InferenceSession(a.model, so, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    t0 = time.time()
    logits = np.concatenate([sess.run(None, {name: x[i:i + 64]})[0] for i in range(0, len(x), 64)])
    py_ms = (time.time() - t0) * 1000
    py = 1 / (1 + np.exp(-logits))

    report = {"n": len(x), "max_abs_diff": float(np.abs(cpp - py).max()),
              "cpp_infer_ms": float(cpp_timing["infer_ms"]), "cpp_load_ms": float(cpp_timing["load_ms"]),
              "cpp_process_wall_s": round(cpp_wall, 2), "python_infer_ms": round(py_ms, 1)}
    print(json.dumps(report, indent=1))
    assert report["max_abs_diff"] < 1e-4, "C++ 與 Python 輸出不一致"


if __name__ == "__main__":
    main()
