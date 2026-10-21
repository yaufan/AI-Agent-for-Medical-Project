"""降低誤報（false positive reduction）用的小型 3D CNN。

輸入：以候選點為中心、1 mm 等向的 32×32×32 區塊。
輸出：是結節的 logit。
參數量約 0.3M，CPU 就能訓練。
"""
import numpy as np
import torch
from torch import nn

from .patches import PATCH, STORE, center_crop  # noqa: F401  （推論端不需要 torch，所以常數放在 patches.py）


def block(cin, cout):
    return nn.Sequential(
        nn.Conv3d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm3d(cout), nn.ReLU(inplace=True),
        nn.Conv3d(cout, cout, 3, padding=1, bias=False), nn.BatchNorm3d(cout), nn.ReLU(inplace=True),
    )


class NoduleNet3D(nn.Module):
    def __init__(self, ch=(16, 32, 64), dropout=0.3):
        super().__init__()
        layers, cin = [], 1
        for c in ch:
            layers += [block(cin, c), nn.MaxPool3d(2)]
            cin = c
        self.features = nn.Sequential(*layers)
        self.head = nn.Sequential(nn.AdaptiveAvgPool3d(1), nn.Flatten(), nn.Dropout(dropout), nn.Linear(cin, 1))

    def forward(self, x):
        return self.head(self.features(x)).squeeze(1)


def augment(patch, rng):
    """patch: (STORE,)*3 → (PATCH,)*3。隨機平移 ±4 mm、三軸翻轉、軸互換（等向才能這樣做）。"""
    m = STORE - PATCH
    o = rng.integers(0, m + 1, size=3)
    p = patch[o[0]:o[0] + PATCH, o[1]:o[1] + PATCH, o[2]:o[2] + PATCH]
    for ax in range(3):
        if rng.random() < 0.5:
            p = np.flip(p, ax)
    p = np.transpose(p, rng.permutation(3))
    return np.ascontiguousarray(p)


@torch.no_grad()
def predict(model, patches, batch=128, tta=2):
    """回傳機率。tta = 平均幾種翻轉組合的結果（test-time augmentation，1～8）。"""
    model.eval()
    masks = [0, 7, 1, 6, 2, 5, 3, 4][:max(1, min(tta, 8))]   # 每個 bit 代表翻轉一個軸
    out = []
    for i in range(0, len(patches), batch):
        x = torch.from_numpy(np.stack([center_crop(p) for p in patches[i:i + batch]])).float()[:, None]
        probs = []
        for f in masks:
            dims = [d + 2 for d in range(3) if f >> d & 1]
            probs.append(torch.sigmoid(model(torch.flip(x, dims) if dims else x)))
        out.append(torch.stack(probs).mean(0))
    return torch.cat(out).numpy() if out else np.zeros(0)
