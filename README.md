# ASURADA Stock Radar｜AI 台股決策雷達

GitHub Pages 靜態網站。前端只讀取 `data/processed/*.json`，不直接抓外部網站、不使用後端、不使用 React。

## 本機預覽

```powershell
python -m http.server 8001
```

開啟：

```text
http://127.0.0.1:8001/index.html
```

## 頁面

- `index.html`：市場總覽
- `radar.html`：上市、上櫃全市場 AI 量化排序，畫面只列出前 100 名
- `news.html`：重點新聞雷達
- `themes.html`：題材資金輪動
- `stock.html?symbol=2330`：個股 AI 分析，可查詢未進入前 100 名排行榜的股票
- `backtest.html`：追蹤驗證
- `data-status.html`：資料更新狀態

## 資料來源

前端只讀取：

```text
data/processed/*.json
```

- `stocks_master.json`
- `market_snapshot.json`
- `ai_scores_daily.json`
- `stock_metrics_daily.json`
- `news_events.json`
- `theme_stats.json`
- `backtest_results.json`
- `update_log.json`

## 全市場資料更新

建立或更新上市、上櫃全市場資料：

```powershell
python scripts/update_full_market_data.py
```

流程會更新：

- `data/processed/stocks_master.json`
- `data/processed/stock_metrics_daily.json`
- `data/processed/ai_scores_daily.json`
- `data/processed/update_log.json`

資料策略：

- 股票主檔優先使用 TWSE ISIN 公開頁，涵蓋上市與上櫃普通股。
- 行情優先使用 TWSE / TPEx 相容公開報價 OpenAPI。
- 月營收優先使用 MOPS / TWSE 月營收 OpenAPI。
- EPS 與毛利率不臆造。若官方來源暫時抓不到，可手動維護 `data/manual/financial_fundamentals.csv`：

```csv
symbol,name,financial_period,eps,gross_margin_pct,source_url
2330,台積電,2026Q1,12.34,53.2,https://example.com/source
```

缺 EPS / 毛利率時，前端顯示 `--`，但股票仍保留在 `stock.html` 個股查詢與全市場排序中。

## GitHub Actions

`update-market-data.yml` 可手動執行，也會在週一到週五 UTC 10:10 排程更新全市場處理資料。若 `data/processed` 有變更，workflow 會自動 commit push。

## 部署

`deploy.yml` 使用 GitHub Pages artifact 部署整個靜態站。資料腳本輸出到 `data/processed/` 後，由 GitHub Pages 發布最新靜態檔案。
