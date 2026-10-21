"""測試用的假資料：合成 DICOM CT 序列與極小的 ONNX 模型（不需要真實資料與 torch）。"""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import onnx
import pydicom
import pytest
from onnx import TensorProto, helper
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parents[1] / "packages" / "lungnod"))


def phantom(n_slices, rows=128, cols=160):
    """身體＋兩肺＋左肺一顆 8 mm 結節（與 P1 的測試假體相同概念）。"""
    z, y, x = np.indices((n_slices, rows, cols))
    zc = n_slices / 2
    hu = np.full((n_slices, rows, cols), -1000, np.int16)
    hu[((y - 64) / 58) ** 2 + ((x - 80) / 76) ** 2 <= 1] = 40
    for xc in (50, 110):
        hu[((z - zc) / (0.4 * n_slices)) ** 2 + ((y - 64) / 40) ** 2 + ((x - xc) / 26) ** 2 <= 1] = -850
    hu[(z - zc) ** 2 + (y - 64) ** 2 + (x - 50) ** 2 <= 5 ** 2] = 30
    return hu


def make_series_zip(n_slices=80, spacing=1.25, pixel=0.8, manufacturer="SIEMENS"):
    hu = phantom(n_slices)
    series_uid, study_uid = generate_uid(), generate_uid()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for k in range(n_slices):
            meta = FileMetaDataset()
            meta.MediaStorageSOPClassUID = CTImageStorage
            meta.MediaStorageSOPInstanceUID = generate_uid()
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
            ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
            ds.Modality, ds.Manufacturer, ds.ConvolutionKernel = "CT", manufacturer, "B30f"
            ds.PatientID, ds.PatientName = "TEST-0001", "Phantom^Test"
            ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [-64.0, -51.2, -100.0 + k * spacing]
            ds.PixelSpacing = [pixel, pixel]
            ds.SliceThickness = spacing
            ds.Rows, ds.Columns = hu.shape[1:]
            ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
            ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
            ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
            ds.PixelData = (hu[k].astype(np.int32) + 1024).astype(np.int16).tobytes()
            f = io.BytesIO()
            ds.save_as(f, enforce_file_format=True)
            zf.writestr(f"series/IM{k:04d}.dcm", f.getvalue())
    return buf.getvalue()


def tiny_onnx(path):
    """logit = mean(patch) × 10 − 3：輸入介面和 P1 的 3D CNN 一樣，(N,1,32,32,32) → (N,)。"""
    x = helper.make_tensor_value_info("patch", TensorProto.FLOAT, ["batch", 1, 32, 32, 32])
    y = helper.make_tensor_value_info("logit", TensorProto.FLOAT, ["batch"])
    axes = helper.make_tensor("axes", TensorProto.INT64, [4], [1, 2, 3, 4])
    scale = helper.make_tensor("scale", TensorProto.FLOAT, [], [10.0])
    bias = helper.make_tensor("bias", TensorProto.FLOAT, [], [3.0])
    nodes = [helper.make_node("ReduceMean", ["patch", "axes"], ["m"], keepdims=0),
             helper.make_node("Mul", ["m", "scale"], ["s"]),
             helper.make_node("Sub", ["s", "bias"], ["logit"])]
    g = helper.make_graph(nodes, "tiny", [x], [y], initializer=[axes, scale, bias])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 18)])
    m.ir_version = 9
    onnx.save(m, path)


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("models")
    tiny_onnx(str(tmp / "model.onnx"))

    # 參考分布：假設訓練資料都是 SIEMENS、1.25 mm
    from lungnod import dicom_io
    from service import drift, qc
    d = tmp_path_factory.mktemp("ref")
    with zipfile.ZipFile(io.BytesIO(make_series_zip())) as z:
        z.extractall(d)
    prof = qc.profile(dicom_io.load_ct(d / "series"))
    (tmp / "ref.json").write_text(json.dumps(drift.build_reference([prof] * 20)))

    os.environ.update(MODEL_PATH=str(tmp / "model.onnx"), REFERENCE_PATH=str(tmp / "ref.json"),
                      THRESHOLD="0.0", ORT_THREADS="2", DRIFT_MIN_SAMPLES="3")
    from fastapi.testclient import TestClient
    from service.main import app
    with TestClient(app) as c:
        yield c
