# 阿斯拉台股主升段雷達

每天盤後掃描台股上市股票，找出中長線主升段候選股。重點線索包含低基期、月營收轉強、概念股重新估值、股價低位階與成交量變化。

本專案只做研究報告，不做自動下單。所有內容僅供研究與風險控管，不構成投資建議。

## 安裝

```powershell
cd C:\Users\Jasper\Documents\asurada-stock-lab\阿斯拉台股主升段雷達
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 每天盤後產生報告

```powershell
.\.venv\Scripts\python.exe run_daily_scan.py --refresh --price-limit 60 --top-n 30
```

如果只是重跑既有快取資料：

```powershell
.\.venv\Scripts\python.exe run_daily_scan.py --price-limit 60 --top-n 30
```

產生後會輸出兩份：

- `output/asurada_candidates_YYYYMMDD.csv`
- `output/asurada_candidates_YYYYMMDD.html`

同時也會自動更新 GitHub Pages 用的靜態網站資料夾：

- `docs/index.html`：首頁，會自動導到最新報告
- `docs/latest.html`：最新 HTML 報告
- `docs/latest.csv`：最新 CSV
- `docs/reports/`：歷史報告

## 報告欄位

目前主要欄位包含：

- 排名
- 股票代號
- 股票名稱
- 概念股
- 公司業務
- 關注原因
- 月營收年增率
- 月營收月增率
- EPS 是否轉虧為盈
- 毛利率是否改善
- 法人是否上修目標價
- 股價是否仍在低位階
- 成交量是否溫和放大
- 阿斯拉評級
- 風險說明
- 是否適合慢慢買
- 阿斯拉分數
- 收盤價
- 當天成交量(張)
- 股價最後日期
- 市場
- 年月

報告排行榜會自動排除 `當天成交量(張)` 低於 1000 張的股票。低量股即使營收成長漂亮，也先不列入主升段候選，避免流動性不足與假突破。

## 發布到 GitHub Pages

這是目前最簡單、最穩的公開方式。適合把每日 HTML 報告做成一個網址給別人看。

1. 到 GitHub 建立一個 repository，例如：

```text
asurada-stock-radar
```

2. 把本專案上傳到 GitHub。

3. 到 GitHub repository 的：

```text
Settings -> Pages
```

4. Source 選：

```text
Deploy from a branch
```

5. Branch 選：

```text
main
```

Folder 選：

```text
/docs
```

6. 儲存後等幾分鐘，GitHub 會給你網址，通常像：

```text
https://你的帳號.github.io/asurada-stock-radar/
```

打開這個網址時，`docs/index.html` 會自動導到最新的 `docs/latest.html`。

## 每天自動更新公開網站

GitHub Actions 會在每週一到週五台灣時間 16:10 自動執行：

1. 下載最新台股清單、月營收、股價與成交量
2. 產生 `docs/latest.html` 與 `docs/latest.csv`
3. 自動 commit 並 push 回 `main`
4. 觸發 GitHub Pages 重新部署

設定檔：

```text
.github/workflows/update-daily-report.yml
```

你也可以到 GitHub 的 `Actions -> Update Daily Stock Report -> Run workflow` 手動更新一次。

## 本機手動更新公開網站

每天盤後：

```powershell
.\.venv\Scripts\python.exe run_daily_scan.py --refresh --price-limit 60 --top-n 30
```

然後把更新後的檔案推送到 GitHub：

```powershell
git add output docs
git commit -m "Update daily stock report"
git push
```

GitHub Pages 更新後，別人打開同一個網址就會看到最新報告。

## Streamlit Cloud 互動版

本專案也準備了互動版入口：

```text
streamlit_app.py
```

本機測試：

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

部署到 Streamlit Community Cloud 時：

1. 將專案推到 GitHub。
2. 到 Streamlit Community Cloud 建立 app。
3. Repository 選你的 GitHub repository。
4. Main file path 填：

```text
streamlit_app.py
```

5. Deploy。

部署完成後會得到類似這樣的網址：

```text
https://你的專案名稱.streamlit.app/
```

Streamlit 版適合之後做搜尋、篩選、互動排行與圖表。GitHub Pages 版適合現在先公開每日 HTML 報告。

## 手動補資料

第一版尚未接 EPS、毛利率與法人目標價正式資料源。你可以先在：

```text
data/manual_factors.csv
```

手動補欄位：

- 題材分類
- 關注原因
- 催化時間
- EPS 是否轉虧為盈
- 毛利率是否改善
- 法人是否上修目標價
- 風險說明

`題材分類` 會優先轉成報告中的 `概念股`。如果沒有手動補，系統會用產業別和內建個股對照產生概念股與公司業務。

## 評分模型

分數由以下線索加總，滿分 100：

- 月營收年增率：最多 25 分
- 月營收月增率：最多 15 分
- EPS 是否轉虧為盈：10 分
- 毛利率是否改善：10 分
- 法人是否上修目標價：10 分
- 股價是否仍在低位階：15 分
- 成交量是否溫和放大：10 分
- 概念股是否明確：5 分

輸出報告另有流動性門檻：當天成交量至少 1000 張。

評級：

- `S`：85 分以上
- `A`：75 到 85 分
- `A-`：65 到 75 分
- `B`：50 到 65 分
- `觀察`：50 分以下

## 資料來源

- 台股清單：TWSE OpenAPI
- 月營收：TWSE OpenAPI
- 股價與成交量：Yahoo Finance via `yfinance`
- 備援股價：TWSE STOCK_DAY

第一版只掃描上市股票，會先用月營收預篩，再對前幾名抓股價量能，避免一次對全市場大量打 API。
