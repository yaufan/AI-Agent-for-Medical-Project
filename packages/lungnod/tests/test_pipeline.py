"""用合成假體（phantom）測試各步驟，不需要真實 CT 資料。

假體：空氣背景中有一個軟組織「身體」，身體裡有兩個肺（-850 HU），
左肺放一顆 8 mm 的球形結節、右肺放一條血管（圓柱）。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lungnod import annotations, candidates, froc, preprocess  # noqa: E402


def make_phantom(shape=(80, 120, 160)):
    z, y, x = np.indices(shape)
    hu = np.full(shape, -1000.0, dtype=np.float32)
    body = ((y - 60) / 55) ** 2 + ((x - 80) / 75) ** 2 <= 1
    hu[body] = 40.0
    left = ((z - 40) / 35) ** 2 + ((y - 60) / 35) ** 2 + ((x - 50) / 25) ** 2 <= 1
    right = ((z - 40) / 35) ** 2 + ((y - 60) / 35) ** 2 + ((x - 110) / 25) ** 2 <= 1
    hu[left | right] = -850.0
    nodule_center = np.array([40, 60, 50])
    nodule = ((z - 40) ** 2 + (y - 60) ** 2 + (x - 50) ** 2) <= 4 ** 2
    hu[nodule] = 30.0
    vessel = (((y - 60) ** 2 + (x - 110) ** 2) <= 2 ** 2) & (np.abs(z - 40) < 25)
    hu[vessel] = 30.0
    return hu, left | right, nodule_center


def test_resample_spacing_keeps_world_coordinates():
    vol = np.random.rand(20, 30, 40).astype(np.float32)
    out, sp = preprocess.resample(vol, (2.5, 0.7, 0.7))
    # 首尾像素中心的世界座標要一致
    np.testing.assert_allclose((np.array(out.shape) - 1) * sp, (np.array(vol.shape) - 1) * [2.5, 0.7, 0.7])


def test_lung_mask_recovers_lungs_and_fills_nodule():
    hu, lungs, c = make_phantom()
    mask = preprocess.lung_mask(hu)
    dice = 2 * (mask & lungs).sum() / (mask.sum() + lungs.sum())
    assert dice > 0.95
    assert mask[tuple(c)], "結節應被補洞包進肺遮罩"
    assert not mask[0, 0, 0], "體外空氣不能算肺"


def test_log_detects_nodule_and_hessian_separates_vessel():
    hu, lungs, c = make_phantom()
    vol = preprocess.normalize_hu(hu)
    mask = preprocess.lung_mask(hu)
    idx, score, sigma, dot = candidates.detect(vol, mask, n_log=50, n_dot=50)
    d = np.linalg.norm(idx - c, axis=1)
    assert d.min() <= 1.5, "LoG 應在結節中心附近有候選點"

    nod = idx[np.argmin(d)]
    s_nod = sigma[np.argmin(d)]
    l_nod = candidates.hessian_eigs(vol, nod, s_nod)
    l_ves = candidates.hessian_eigs(vol, np.array([40, 60, 110]), 1.5)
    # 球：三個特徵值都明顯為負；管：最小的那個接近 0
    assert np.all(l_nod < 0) and abs(l_nod[0]) / abs(l_nod[2]) > 0.5
    assert abs(l_ves[0]) / abs(l_ves[2]) < 0.2

    # 點濾波：結節中心的響應要遠高於血管中段
    dres = candidates.dot_scale_space(vol, mask)
    assert dres[tuple(c)] > 5 * dres[40, 60, 110]


def test_extract_patch_pads_outside():
    vol = np.ones((10, 10, 10), np.float32)
    p = candidates.extract_patch(vol, np.array([0, 0, 0]), 8)
    assert p.shape == (8, 8, 8)
    assert p[0, 0, 0] == 0 and p[-1, -1, -1] == 1


def test_label_and_froc():
    t = [annotations.Nodule(center_mm=np.array([0.0, 0, 0]), diameter_mm=10, n_readers=4)]
    ig = [annotations.Nodule(center_mm=np.array([50.0, 0, 0]), diameter_mm=6, n_readers=1)]
    cand = np.array([[1.0, 1, 1], [2.0, 0, 0], [50.0, 1, 0], [100.0, 0, 0]])
    labels, hit = froc.label_candidates(cand, t, ig)
    assert labels.tolist() == [froc.POS, froc.POS, froc.IGNORE, froc.NEG]

    scans = [{"scores": np.array([0.9, 0.8, 0.95, 0.5]), "labels": labels, "hit": hit, "n_targets": 1}]
    _, _, at, cpm = froc.froc(scans)
    # 結節分數 0.9 排在唯一的 FP(0.5) 前面 → 0 FP 時就已偵測到
    assert at[0] == 1.0 and cpm == 1.0


def test_merge_by_distance_when_no_group():
    from lungnod.dicom_io import SegAnnotation
    m1 = np.zeros((20, 20, 20), bool)
    m1[8:12, 8:12, 8:12] = True
    m2 = np.zeros_like(m1)
    m2[9:13, 8:12, 8:12] = True
    m3 = np.zeros_like(m1)
    m3[0:2, 0:2, 0:2] = True
    anns = [SegAnnotation(m, "x", None) for m in (m1, m2, m3)]
    nods = annotations.merge_annotations(anns, np.ones(3), np.zeros(3))
    assert sorted(n.n_readers for n in nods) == [1, 2]


@pytest.mark.parametrize("readers,diam,is_target", [(4, 8, True), (3, 3.5, True), (2, 8, False), (4, 2.5, False)])
def test_split_targets(readers, diam, is_target):
    n = annotations.Nodule(center_mm=np.zeros(3), diameter_mm=diam, n_readers=readers)
    t, ig = annotations.split_targets([n])
    assert (len(t) == 1) == is_target and len(t) + len(ig) == 1


@pytest.mark.parametrize("orient,expected", [
    ([1, 0, 0, 0, 1, 0], (False, False)),
    ([-1, 0, 0, 0, -1, 0], (True, True)),     # 部分 GE 序列：影像轉 180°
    ([-1, 0, 0, 0, 1, 0], (False, True)),
])
def test_axis_flips(orient, expected):
    from lungnod.dicom_io import _axis_flips
    assert _axis_flips(np.array(orient, float)) == expected


def test_axis_flips_rejects_oblique():
    from lungnod.dicom_io import _axis_flips
    with pytest.raises(ValueError):
        _axis_flips(np.array([0.98, 0.2, 0, -0.2, 0.98, 0]))


def test_features_at_volume_border():
    hu, lungs, _ = make_phantom()
    vol = preprocess.normalize_hu(hu)
    idx = np.array([[0, 0, 0], [79, 119, 159], [40, 0, 80]])
    f = candidates.candidate_features(vol, hu, lungs, idx, np.ones(3), np.array([6.0, 6.0, 1.0]), np.ones(3))
    assert f.shape == (3, len(candidates.FEATURE_NAMES)) and np.isfinite(f).all()
