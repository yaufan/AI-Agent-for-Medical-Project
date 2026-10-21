"""讀取 CT 序列與 DICOM SEG，統一轉成 (z, y, x) 的 numpy 陣列。

座標約定：
- 陣列軸順序 (z, y, x)，spacing 與 origin 也用 (z, y, x)，單位 mm。
- 世界座標 = origin + index * spacing（只處理軸向、無傾斜的 CT）。
"""
from dataclasses import dataclass
from pathlib import Path

import re

import numpy as np
import pydicom


@dataclass
class CTVolume:
    hu: np.ndarray            # (z, y, x) int16，單位 HU
    spacing: np.ndarray       # (dz, dy, dx) mm
    origin: np.ndarray        # (z0, y0, x0) mm，第一張切片左上角像素中心
    z_positions: np.ndarray   # 每張切片的 z 座標（排序後）
    series_uid: str
    patient_id: str
    manufacturer: str = ""
    kernel: str = ""          # 重建核心（ConvolutionKernel），影響雜訊與邊緣銳利度
    flip: tuple = (False, False)  # 原始影像的 (列, 行) 是否被翻轉過；SEG 也要跟著翻


def _axis_flips(orient):
    """只接受和座標軸對齊的軸向切片：列方向 ±x、行方向 ±y。

    有些機器（例如部分 GE 序列）存的是 [-1,0,0, 0,-1,0]，也就是影像轉了 180°。
    這種情況把像素翻回來，並修正左上角的世界座標，就能和其他序列一樣處理。
    """
    row, col = orient[:3], orient[3:]
    if not (np.allclose(np.abs(row), [1, 0, 0], atol=1e-3) and np.allclose(np.abs(col), [0, 1, 0], atol=1e-3)):
        raise ValueError(f"只支援軸向、無傾斜的 CT，收到 ImageOrientationPatient={orient}")
    return bool(col[1] < 0), bool(row[0] < 0)   # (翻轉列 → y, 翻轉行 → x)


def load_ct(series_dir):
    """讀入一個 CT 序列資料夾，回傳 HU 體積。"""
    slices = []
    for f in Path(series_dir).glob("*.dcm"):
        ds = pydicom.dcmread(f)
        if ds.get("Modality") != "CT":
            continue
        slices.append(ds)
    if not slices:
        raise ValueError(f"{series_dir} 沒有 CT 影像")

    orient = np.array(slices[0].ImageOrientationPatient, dtype=float)
    flip_y, flip_x = _axis_flips(orient)

    # 依 z 排序；重複位置的切片（少數序列會有）只留一張
    slices.sort(key=lambda d: float(d.ImagePositionPatient[2]))
    uniq, last_z = [], None
    for d in slices:
        z = float(d.ImagePositionPatient[2])
        if last_z is None or abs(z - last_z) > 1e-3:
            uniq.append(d)
            last_z = z
    slices = uniq

    z = np.array([float(d.ImagePositionPatient[2]) for d in slices])
    dz = float(np.median(np.diff(z)))  # 用實際切片間距，不用 SliceThickness
    dy, dx = (float(v) for v in slices[0].PixelSpacing)

    hu = np.stack([
        d.pixel_array.astype(np.float32) * float(d.RescaleSlope) + float(d.RescaleIntercept)
        for d in slices
    ])
    # 視野外的像素常存成 -2000 之類的值，統一壓到空氣
    hu = np.clip(hu, -1024, 3071).astype(np.int16)

    x0, y0, _ = (float(v) for v in slices[0].ImagePositionPatient)
    if flip_y:
        hu = hu[:, ::-1]
        y0 -= (hu.shape[1] - 1) * dy
    if flip_x:
        hu = hu[:, :, ::-1]
        x0 -= (hu.shape[2] - 1) * dx
    hu = np.ascontiguousarray(hu)
    return CTVolume(
        hu=hu,
        spacing=np.array([dz, dy, dx]),
        origin=np.array([z[0], y0, x0]),
        z_positions=z,
        series_uid=str(slices[0].SeriesInstanceUID),
        patient_id=str(slices[0].PatientID),
        manufacturer=str(slices[0].get("Manufacturer", "")),
        kernel=str(slices[0].get("ConvolutionKernel", "")),
        flip=(flip_y, flip_x),
    )


@dataclass
class SegAnnotation:
    mask: np.ndarray     # 與 CT 同大小的 bool 陣列
    label: str           # 例："Segmentation of Nodule 2 - Annotation IL"
    group: int | None    # IDC 轉檔時已用 pylidc 把各醫師的標註分群成「Nodule N」



def load_seg(seg_file, ct):
    """讀入一個 DICOM SEG（LIDC 在 IDC 的格式：一個 SEG 一顆結節、一位醫師），
    依每個 frame 的 ImagePositionPatient 對回 CT 的切片。"""
    ds = pydicom.dcmread(seg_file)
    ref = ds.get("ReferencedSeriesSequence")
    if ref and str(ref[0].SeriesInstanceUID) != ct.series_uid:
        return []  # 這個 SEG 是畫在同一個 study 的別的序列上

    frames = ds.pixel_array
    if frames.ndim == 2:
        frames = frames[None]

    masks = {}
    for i, fg in enumerate(ds.PerFrameFunctionalGroupsSequence):
        seg_no = int(fg.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
        z = float(fg.PlanePositionSequence[0].ImagePositionPatient[2])
        k = int(np.argmin(np.abs(ct.z_positions - z)))
        if abs(ct.z_positions[k] - z) > ct.spacing[0] / 2:
            continue  # 對不到切片，略過
        m = masks.setdefault(seg_no, np.zeros(ct.hu.shape, dtype=bool))
        f = frames[i].astype(bool)
        if ct.flip[0]:
            f = f[::-1]
        if ct.flip[1]:
            f = f[:, ::-1]
        m[k] |= f

    # IDC 的 LIDC SEG：一個檔案 = 一位醫師對一顆結節的標註。
    # ContentCreatorName 一律是 "Reader1"，無法分辨醫師；
    # 但 SeriesDescription 的 "Nodule N" 是跨醫師的分群編號，同一群的每份標註來自不同醫師。
    desc = str(ds.get("SeriesDescription", ""))
    m = re.search(r"Nodule (\d+)", desc)
    group = int(m.group(1)) if m else None
    return [SegAnnotation(mask=mk, label=desc, group=group) for mk in masks.values() if mk.any()]


def find_series(patient_dir):
    """IDC 下載的資料夾結構：<patient>/<study>/<CT_xxx | SEG_xxx>/*.dcm"""
    patient_dir = Path(patient_dir)
    ct_dirs = sorted(patient_dir.glob("*/CT_*"))
    seg_files = sorted(patient_dir.glob("*/SEG_*/*.dcm"))
    return ct_dirs, seg_files
