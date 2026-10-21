"""用訓練資料建立「輸入概況」的參考分布，給服務的漂移監控使用。

用法：
    python scripts/build_reference.py --data <P1 的 data/lidc_idri> --out models/reference_profile.json
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parents[1] / "packages" / "lungnod"))
from lungnod import dicom_io  # noqa: E402
from service import drift, qc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    profiles = []
    for p in sorted(Path(a.data).iterdir()):
        ct_dirs, _ = dicom_io.find_series(p)
        if ct_dirs:
            profiles.append(qc.profile(dicom_io.load_ct(ct_dirs[0])))
    ref = drift.build_reference(profiles)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(ref, indent=1))
    print(f"{len(profiles)} 例；廠牌 {dict(Counter(p['manufacturer'] for p in profiles))}")
    print("切片間距分箱切點：", ref["numeric"]["slice_spacing_mm"]["cuts"])


if __name__ == "__main__":
    main()
