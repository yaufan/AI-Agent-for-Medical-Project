# 資料來源與授權

每一筆公開資料在放進知識庫或工具之前，都要在這裡登記來源、授權與確認狀態。**狀態不是「已確認」的資料，不放進 repo。**

最後更新：2026-10-21

## 公開資料

| 資料 | 用途 | 取得方式 | 授權／使用條件 | 狀態 |
|---|---|---|---|---|
| LIDC-IDRI 胸腔 CT（含 4 位放射科醫師的結節標註） | `packages/lungnod`、`services/cad-service` 的影像資料 | NCI Imaging Data Commons（`idc-index`，Google Cloud／AWS 公開 bucket） | CC BY 3.0（TCIA） | 已確認（P1 已使用）；影像不放進 repo，由腳本下載 |
| FDA 網站內容（guidance、網頁） | 知識庫：CADe、AI 軟體變更管制、軟體送審、資安 | www.fda.gov | FDA 網站政策：「除另有註明外，FDA 網站內容不受著作權保護，屬於公有領域，可自由轉載與使用」；標示來源為佳但非必要。**頁面中標示為第三方著作的內容除外** | 已確認（2026-10-21 讀取網站政策頁） |
| 510(k) 摘要與決定文件 PDF | 知識庫：同類產品的性能表格 | www.accessdata.fda.gov | 屬 FDA 公開文件，原則同上；個別文件若含第三方著作要逐份看 | 待逐份確認 |
| openFDA：510(k)、產品分類、不良事件、回收 | MCP 工具（即時查詢） | api.fda.gov | 依 openFDA 使用條款（條款頁在 open.fda.gov，這個環境尚未開放該網域） | 待確認 |
| ClinicalTrials.gov API v2 | MCP 工具（即時查詢） | clinicaltrials.gov/api/v2 | 依 ClinicalTrials.gov 使用條款（條款頁為動態載入，這個環境讀不到內容） | 待確認：請在瀏覽器打開 clinicaltrials.gov 的 Terms and Conditions 頁面確認 |
| TFDA 公告與指引 | 知識庫：中文法規（跨語題型） | www.fda.gov.tw | 要確認是否適用「政府資料開放授權條款」 | 待確認 |
| GPU／SSD datasheet | 場景 3：替代料比較 | 各廠商網站 | 每份不同，多數不允許轉載 | 待確認；不確定的只放連結與摘要，不放全文 |

## 不放進知識庫的資料

| 資料 | 原因 | 處理方式 |
|---|---|---|
| Lung-RADS（ACR） | 學會著作 | 只在文件中引用出處，不收錄全文 |
| Fleischner Society 指引 | 期刊論文 | 同上 |
| 任何醫院或公司的內部資料 | 不屬於公開資料 | 一律不用 |

## 合成資料

| 資料 | 產生方式 | 說明 |
|---|---|---|
| 公司 M 的 ERP＋QMS | `packages/erpqms`，固定種子 | 全部虛構，名稱中性；產生的檔案不進 repo（見 `.gitignore`），需要時重新產生 |

## 已確認可以連線的網域（雲端開發環境）

2026-10-21 測試：clinicaltrials.gov、api.fda.gov、www.fda.gov、www.accessdata.fda.gov、www.fda.gov.tw 可以連線；Hugging Face 不行，嵌入與重排序模型要在本機下載。
