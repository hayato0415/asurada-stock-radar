# ASURADA Stock Radar｜AI 台股決策雷達

GitHub Pages 靜態網站 MVP。第一階段只使用 `data/processed/*.json` sample data，不直接抓外部網站、不使用後端、不使用 React。

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
- `radar.html`：AI 選股清單
- `news.html`：重點新聞雷達
- `themes.html`：題材資金輪動
- `stock.html?symbol=2330`：個股 AI 分析
- `backtest.html`：追蹤驗證
- `data-status.html`：資料更新狀態

## 資料來源

前端只讀取：

```text
data/processed/*.json
```

第一階段 sample data：

- `stocks_master.json`
- `market_snapshot.json`
- `ai_scores_daily.json`
- `news_events.json`
- `theme_stats.json`
- `backtest_results.json`
- `update_log.json`

## 部署

`deploy.yml` 使用 GitHub Pages artifact 部署整個靜態站。`update-data.yml` 目前是預留資料更新流程，未來資料腳本應輸出到 `data/processed/`。
