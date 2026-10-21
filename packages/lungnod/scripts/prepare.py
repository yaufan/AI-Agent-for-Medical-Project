"""前處理：每個病例 → 重取樣、肺遮罩、候選點、手工特徵、CNN 區塊，存成一個 npz。

用法：
    python scripts/prepare.py --data <IDC 下載資料夾>/lidc_idri --out cache --workers 3
"""
import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lungnod import annotations, candidates, dicom_io, froc, preprocess  # noqa: E402
from lungnod.patches import STORE  # noqa: E402


def process(args):
    try:
        return _process(*args)
    except Exception as e:  # 單一病例失敗不要讓整批中斷，記錄原因後繼續
        return Path(args[0]).name, f"ERROR {type(e).__name__}: {e}"


def _process(patient_dir, out_dir):
    out = Path(out_dir) / f"{Path(patient_dir).name}.npz"
    if out.exists():
        return out.name, "cached"
    t0 = time.time()
    ct_dirs, seg_files = dicom_io.find_series(patient_dir)
    if not ct_dirs:
        return Path(patient_dir).name, "no CT"
    ct = dicom_io.load_ct(ct_dirs[0])

    segs = []
    for f in seg_files:
        segs += dicom_io.load_seg(f, ct)
    nodules = annotations.merge_annotations(segs, ct.spacing, ct.origin)
    targets, ignore = annotations.split_targets(nodules)

    hu, sp = preprocess.resample(ct.hu.astype(np.float32), ct.spacing)
    lung = preprocess.lung_mask(hu, sp)
    vol = preprocess.normalize_hu(hu)
    t_pre = time.time() - t0

    idx, score, sigma, dot = candidates.detect(vol, lung)
    feats = candidates.candidate_features(vol, hu, lung, idx, score, sigma, dot)
    cand_mm = ct.origin + idx * sp
    labels, hit = froc.label_candidates(cand_mm, targets, ignore)
    t_cand = time.time() - t0 - t_pre

    patches = np.stack([candidates.extract_patch(vol, p, STORE) for p in idx]).astype(np.float16) \
        if len(idx) else np.zeros((0, STORE, STORE, STORE), np.float16)
    # 額外的正樣本：直接以醫師標註的結節中心切區塊（只用在訓練）
    tgt_idx = [np.round((n.center_mm - ct.origin) / sp).astype(int) for n in targets]
    tgt_patches = np.stack([candidates.extract_patch(vol, p, STORE) for p in tgt_idx]).astype(np.float16) \
        if tgt_idx else np.zeros((0, STORE, STORE, STORE), np.float16)

    np.savez_compressed(
        out,
        patient_id=ct.patient_id,
        cand_idx=idx, cand_mm=cand_mm, cand_score=score, cand_sigma=sigma, cand_dot=dot,
        features=feats, labels=labels, hit=hit, patches=patches,
        target_center_mm=np.array([n.center_mm for n in targets]).reshape(-1, 3),
        target_diameter_mm=np.array([n.diameter_mm for n in targets]),
        target_readers=np.array([n.n_readers for n in targets]),
        ignore_center_mm=np.array([n.center_mm for n in ignore]).reshape(-1, 3),
        ignore_diameter_mm=np.array([n.diameter_mm for n in ignore]),
        target_patches=tgt_patches,
        spacing_orig=ct.spacing, spacing=sp, origin=ct.origin, shape=np.array(hu.shape),
        lung_volume_ml=lung.sum() * np.prod(sp) / 1000.0,
        timing=np.array([t_pre, t_cand, time.time() - t0]),
    )
    found = len(set(hit[labels == froc.POS]))
    return out.name, f"targets={len(targets)} found={found} cands={len(idx)} " \
                     f"lung={lung.sum() * np.prod(sp) / 1e6:.1f}L time={time.time() - t0:.0f}s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="含 LIDC-IDRI-xxxx 子資料夾的目錄")
    ap.add_argument("--out", default="cache")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    patients = sorted(p for p in Path(a.data).iterdir() if p.is_dir())
    if a.limit:
        patients = patients[:a.limit]
    log = {}
    with Pool(a.workers) as pool:
        for name, msg in pool.imap_unordered(process, [(str(p), a.out) for p in patients]):
            print(name, msg, flush=True)
            log[name] = msg
    Path(a.out, "prepare_log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
