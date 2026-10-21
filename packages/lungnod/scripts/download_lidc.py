"""從 NCI Imaging Data Commons（公開 bucket，免帳號）下載 LIDC-IDRI 的 CT 與結節 SEG。

只選切片數 120～350 張（約對應切片間距 ≤ 2.5 mm）且有醫師標註的序列，每位病人一個序列。

用法：
    python scripts/download_lidc.py --n 48 --out data --seed 42
"""
import argparse
from pathlib import Path

from idc_index import index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    client = index.IDCClient()
    df = client.index
    lidc = df[df.collection_id == "lidc_idri"]
    ct = lidc[lidc.Modality == "CT"]
    n_seg = lidc[lidc.Modality == "SEG"].groupby("StudyInstanceUID").size().rename("n_seg")
    ct = ct.join(n_seg, on="StudyInstanceUID").fillna({"n_seg": 0})
    cand = ct[(ct.instanceCount >= 120) & (ct.instanceCount <= 350) & (ct.n_seg >= 1)]
    pick = cand.drop_duplicates("PatientID").sample(n=a.n, random_state=a.seed)

    studies = set(pick.StudyInstanceUID)
    sel = lidc[lidc.StudyInstanceUID.isin(studies) &
               ((lidc.Modality == "SEG") | lidc.SeriesInstanceUID.isin(set(pick.SeriesInstanceUID)))]
    print(f"病人 {len(pick)}，序列 {len(sel)}，約 {sel.series_size_MB.sum() / 1024:.1f} GB")

    Path(a.out).mkdir(parents=True, exist_ok=True)
    pick[["PatientID", "SeriesInstanceUID", "instanceCount", "Manufacturer"]].to_csv(
        Path(a.out) / "selected_patients.csv", index=False)
    client.download_from_selection(seriesInstanceUID=list(sel.SeriesInstanceUID), downloadDir=a.out, quiet=True)


if __name__ == "__main__":
    main()
