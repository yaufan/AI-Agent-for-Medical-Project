"""區塊大小常數與裁切（不依賴 torch，推論服務也能用）。"""
import numpy as np

PATCH = 32       # 模型輸入大小（1 mm 等向 → 32 mm 見方）
STORE = 40       # 預存的區塊大小，多出的邊用來做隨機平移增強


def center_crop(patch):
    m = (STORE - PATCH) // 2
    return np.ascontiguousarray(patch[m:m + PATCH, m:m + PATCH, m:m + PATCH])
