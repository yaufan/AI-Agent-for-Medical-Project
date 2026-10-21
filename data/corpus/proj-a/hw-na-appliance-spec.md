---
doc_id: HW-NA
title: 推論主機 NA-100／NA-200 規格
group: proj-a
classification: internal
lang: zh
---
# 推論主機 NA-100／NA-200 規格（HW-NA）

> 虛構產品，數值為合成。

## 機型比較

| 項目 | NA-100 | NA-200 |
|---|---|---|
| 推出時間 | 2024 年 1 月 | 2026 年 1 月 |
| GPU | GPU G1（24 GB）× 1 | GPU G2（48 GB）× 1 |
| 資料碟 | SSD S1（1 TB） | SSD S2（2 TB） |
| CPU | CPU C1（16 核心） | CPU C1（16 核心） |
| 記憶體 | 32 GB × 2 | 32 GB × 4 |
| 電源 | PSU P1（1200 W） | PSU P1（1200 W） |
| 單例處理時間中位數 | 約 95 秒 | 約 70 秒 |

## 維護
- 每台主機出廠時記錄每個零件的批號，維修與追溯以序列號查詢。
- SSD 存放影像暫存與工作佇列；SSD 故障時服務中斷，需要現場更換。
- 主機遠端監控項目：GPU 溫度、SSD SMART 狀態、工作佇列長度、推論時間。
