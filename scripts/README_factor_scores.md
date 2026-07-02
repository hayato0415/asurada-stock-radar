# AI 選股多因子評分資料管線

本管線只使用官方公開資料，不使用新聞、不使用社群討論，也不把題材或概念股納入分數。

## 輸出檔案

- `data/processed/factor-scores.json`：前 100 名多因子評分結果，供 `factor-score.html` 顯示。
- `data/processed/factor-scores.status.json`：本次更新狀態。若官方資料不可用，會保留上一版評分並寫入失敗原因。
- `data/processed/factor-scores.meta.json`：評分權重、資料來源與欄位說明。
- `data/processed/factor-quote-history.json`：近期行情快照，用於技術面與量能分數。

## 官方資料來源

- 上市每日行情：`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
- 上市本益比 / 殖利率 / 股價淨值比：`https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL`
- 上市月營收：`https://openapi.twse.com.tw/v1/opendata/t187ap05_L`
- 上市公司基本資料：`https://openapi.twse.com.tw/v1/opendata/t187ap03_L`
- 上櫃每日行情：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
- 上櫃本益比資料：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis`
- 上櫃月營收：`https://openapi.twse.com.tw/v1/opendata/t187ap05_O`
- 上櫃公司基本資料：`https://openapi.twse.com.tw/v1/opendata/t187ap03_O`

## 分數權重

- 基本面：30%
- 技術面：30%
- 籌碼 / 市場交易力道：25%
- 週轉率 / 交易熱度：15%
- 新聞面：0%，不納入

## 更新時間

GitHub Actions 排程：

- 台灣時間 15:20，收盤後第一次更新。
- 台灣時間 16:10，補晚到行情或營收資料。
- 台灣時間 20:30，晚間補齊。

也可手動執行 `update-factor-scores.yml`，並指定 `target_date`。

## 狀態欄位

`factor-scores.status.json` 會記錄：

- `ok`：是否成功產生新評分。
- `target_date`：指定檢查日期。
- `latest_trade_date`：官方行情內容日期。
- `generated_at`：本次腳本執行時間。
- `rows_written`：輸出的評分筆數。
- `official_source_used`：使用到的官方資料源。
- `failed_reasons`：失敗原因。
- `warnings`：非阻斷警告。
- `previous_data_preserved`：失敗時是否保留上一版資料。

## 常見失敗原因

- 官方 OpenAPI 尚未發布當日收盤資料。
- 指定 `target_date` 與官方最新行情日期不同。
- 上櫃資料源暫時不可用。
- 股票主檔缺少必要欄位。
- 官方欄位名稱異動，解析不到代號、收盤價或成交量。

失敗時不會用 `0` 假裝有資料，也不會覆蓋上一版 `factor-scores.json`。
