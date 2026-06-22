# 雷達資料欄位規格

本文件描述 `docs/data/stocks-latest.json` 的公開前端資料契約。資料更新器可增加欄位，但不得任意改名、改型別或刪除既有欄位；需要破壞性變更時，必須同步修改前端與本文件。

## 儲存格式

- 檔案：UTF-8 JSON。
- 根節點：股票物件陣列。
- 股票代號：字串，保留前導零；前端顯示時不包含 `.TW` 或 `.TWO`。
- 金額：`current_revenue_million` 統一使用百萬元。
- 比率：數值欄位使用百分點，例如 `5.8` 代表 `5.8%`。
- 缺值：使用 `null` 或空字串；不得寫入字串 `undefined`、`null`、`NaN`。

## 核心欄位

| 欄位 | 型別 | 用途 | 格式／範例 |
| --- | --- | --- | --- |
| `rank` | number | 原始雷達排序 | `1` |
| `code` | string | 股票代號 | `"2337"` |
| `name` | string | 股票名稱快照；正式名稱仍以 `stock-master.json` 為準 | `"旺宏"` |
| `market` | string | 市場別 | `"上市"` |
| `concept` | string | 原始概念或題材，以分號分隔 | `"記憶體;NOR Flash"` |
| `business` | string | 公司主要業務摘要 | `"記憶體製造與銷售。"` |
| `reason` | string | 原始入選理由 | `"營收年增 175.8%..."` |
| `rating` | string | 舊雷達評級，只供相容與排序參考 | `"B"` |
| `score` | string | 舊分數文字 | `"62.0"` |
| `score_value` | number | 排序使用的數值分數 | `62.0` |
| `risk_tags` | string | 原始風險標籤，以頓號分隔 | `"低基期、月增轉弱"` |
| `tracking_status` | string | 研究追蹤狀態 | `"研究觀察"` |

## 行情欄位

| 欄位 | 型別 | 用途 | 格式／範例 |
| --- | --- | --- | --- |
| `close` | string | 收盤價顯示值 | `"169.0"` |
| `volume` | string | 當日成交量顯示值，單位為張 | `"124602"` |
| `volume_value` | number | 量能條件運算值，單位為張 | `124602.0` |
| `daily_change` | string／number | 當日漲跌幅；資料不足時可為 `"-"` | `3.25` |
| `market_date` | string | 行情日期 | `"2026-06-18"` |

## 月營收欄位

| 欄位 | 型別 | 用途 | 格式／範例 |
| --- | --- | --- | --- |
| `revenue_month` | string | 月營收所屬月份 | `"2026-05"` |
| `current_revenue` | string | 原始營收顯示文字 | `"62.56億元"` |
| `current_revenue_million` | number | 當月營收，單位百萬元 | `6255.65` |
| `previous_year_revenue` | string | 去年同月營收顯示文字 | `"22.68億元"` |
| `revenue_mom` | string | 月增率顯示文字 | `"+5.80%"` |
| `revenue_mom_value` | number | 月增率運算值，單位百分點 | `5.8` |
| `revenue_yoy` | string | 年增率顯示文字 | `"+175.80%"` |
| `revenue_yoy_value` | number | 年增率運算值，單位百分點 | `175.8` |
| `data_version` | string | 前端資料版本摘要 | `"營收 2026-05｜行情 2026-06-18"` |

## 前端衍生欄位

以下欄位由 `docs/js/stockClassifier.js` 即時計算，不應回寫或偽造到原始 JSON。

| 欄位 | 型別 | 來源 | 可能值／範例 |
| --- | --- | --- | --- |
| `industryName` | string | 股票欄位或 `stock-master.json` 產業代碼 | `"半導體"` |
| `themeTags` | string[] | 原始題材與 taxonomy 關鍵字推斷 | `["記憶體", "半導體"]` |
| `radarPool` | string | `getRadarPool(stock)` | `electronicTechPool`、`nonElectronicPool` |
| `display_rank` | number | 各雷達池重新排序後的前端名次 | `1` |

## 相容規則

1. `score`、`rating` 不得作為單一投資判斷，只保留相容與排序用途。
2. 股票名稱優先由 `docs/data/stock-master.json` 補齊。
3. 題材只能根據現有文字欄位與 taxonomy 推斷，不得自行編造。
4. 無法分類時預設 `electronicTechPool`，並在 console 留下警告供補資料。
5. 表格欄位若需調整，必須先檢查 `docs/app.js` 的 `radarEvidenceTable()` 與手機版 CSS。
