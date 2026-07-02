import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, renderEmpty } from "./utils.js";
import { formatDateTime, formatNumber, formatPercent, formatSignedPercent, valueClass } from "./formatters.js";
import { riskBadge, scoreBadge, statusBadge } from "./scoring-ui.js";

let stocks = [];
let scores = [];
let news = [];
let metrics = [];
let stockDataUpdatedAt = "";
let metricsUpdatedAt = "";
let metricsRevenueMonth = "";

function getSymbolFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get("symbol") || params.get("code") || "";
}

function findStock(query) {
  const rawValue = String(query || "").trim();
  const value = rawValue.toLowerCase();
  const codeMatch = rawValue.match(/\b\d{4,6}\b/);

  if (codeMatch) {
    return stocks.find((stock) => String(stock.symbol) === codeMatch[0]);
  }

  if (!value) return null;

  return stocks.find((stock) => String(stock.name || "").toLowerCase() === value)
    || stocks.find((stock) => String(stock.name || "").toLowerCase().includes(value)
      || String(stock.symbol || "").includes(value));
}

function renderStockOptions() {
  const list = $("#stockOptions");
  if (!list) return;
  list.innerHTML = stocks
    .map((stock) => `<option value="${escapeHtml(stock.symbol)} ${escapeHtml(stock.name)}"></option>`)
    .join("");
}

function scoreLine(label, value) {
  const width = Math.max(0, Math.min(100, Number(value || 0)));
  return `
    <div class="score-line">
      <span>${escapeHtml(label)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
      <strong>${escapeHtml(value ?? "--")}</strong>
    </div>
  `;
}

function findMetric(symbol) {
  return metrics.find((item) => String(item.symbol) === String(symbol)) || {};
}

function hasNumericValue(value) {
  if (value === null || value === undefined || value === "") return false;
  return Number.isFinite(Number(value));
}

function formatMetricNumber(value, digits = 2) {
  return hasNumericValue(value) ? formatNumber(value, digits) : "--";
}

function formatMetricPercent(value, digits = 2) {
  return hasNumericValue(value) ? formatPercent(value, digits) : "--";
}

function formatMetricSignedPercent(value, digits = 2) {
  return hasNumericValue(value) ? formatSignedPercent(value, digits) : "--";
}

function formatVolumeLots(value) {
  if (!hasNumericValue(value)) return "--";
  return `${formatNumber(Math.round(Number(value) / 1000), 0)} 張`;
}

function getTurnoverRate(metric) {
  if (hasNumericValue(metric.turnover_rate_pct)) {
    return formatPercent(metric.turnover_rate_pct, 2);
  }

  if (hasNumericValue(metric.volume) && hasNumericValue(metric.listed_shares)) {
    const listedShares = Number(metric.listed_shares);
    if (listedShares > 0) {
      return formatPercent((Number(metric.volume) / listedShares) * 100, 2);
    }
  }

  return "--";
}

function getRevenueMonthLabel(metric) {
  const revenueMonth = metric.revenue_month || metricsRevenueMonth;
  if (revenueMonth) {
    const match = String(revenueMonth).match(/(?:\d{4}-)?(\d{1,2})$/);
    if (match) return `${Number(match[1])}月`;
    return escapeHtml(String(revenueMonth));
  }
  if (metric.revenue_period) {
    const match = String(metric.revenue_period).match(/-(\d{1,2})$/);
    if (match) return `${Number(match[1])}月`;
  }
  return "最新月份";
}

function renderTradingRevenueSnapshot(metric) {
  const monthLabel = getRevenueMonthLabel(metric);
  const financialPeriod = metric.financial_period || "最新季";
  return `
    <section class="panel stock-snapshot-panel">
      <div class="section-head">
        <h2>交易、營收與獲利快照</h2>
        <span class="muted">資料更新：${formatDateTime(metric.updated_at || metricsUpdatedAt)}</span>
      </div>
      <div class="metric-grid stock-snapshot-grid">
        <article class="metric-card"><span>成交價</span><strong>${formatMetricNumber(metric.trade_price, 2)}</strong></article>
        <article class="metric-card"><span>漲幅%</span><strong class="${valueClass(metric.change_pct)}">${formatMetricSignedPercent(metric.change_pct, 2)}</strong></article>
        <article class="metric-card"><span>成交量</span><strong>${formatVolumeLots(metric.volume)}</strong></article>
        <article class="metric-card"><span>週轉率</span><strong>${getTurnoverRate(metric)}</strong></article>
        <article class="metric-card"><span>當月營收(百萬)</span><strong>${formatMetricNumber(metric.revenue_million, 2)}</strong></article>
        <article class="metric-card"><span>月增率(${monthLabel})</span><strong class="${valueClass(metric.revenue_mom_pct)}">${formatMetricSignedPercent(metric.revenue_mom_pct, 2)}</strong></article>
        <article class="metric-card"><span>年增率(${monthLabel})</span><strong class="${valueClass(metric.revenue_yoy_pct)}">${formatMetricSignedPercent(metric.revenue_yoy_pct, 2)}</strong></article>
        <article class="metric-card"><span>EPS(${escapeHtml(financialPeriod)})</span><strong>${formatMetricNumber(metric.eps, 2)}</strong></article>
        <article class="metric-card"><span>毛利率(${escapeHtml(financialPeriod)})</span><strong>${formatMetricPercent(metric.gross_margin_pct, 2)}</strong></article>
      </div>
    </section>
  `;
}

function renderStock(stock) {
  const root = $("#stockDetail");
  if (!stock) {
    root.innerHTML = renderEmpty("請輸入股票代號或名稱查詢個股 AI 分析");
    return;
  }

  const score = scores.find((item) => String(item.symbol) === String(stock.symbol)) || {};
  const metric = findMetric(stock.symbol);
  const relatedNews = news.filter((item) => item.stocks?.some((newsStock) => String(newsStock.code ?? newsStock.symbol) === String(stock.symbol)));
  const theme = score.theme || stock.theme || stock.supply_chain || stock.industry || "--";
  const supplyChain = stock.supply_chain || stock.industry || "--";
  const updatedAt = score.updated_at || score.market_date || metric.updated_at || stock.updated_at || metricsUpdatedAt || stockDataUpdatedAt;

  $("#stockUpdatedAt").textContent = `資料更新：${formatDateTime(updatedAt)}`;
  root.innerHTML = `
    <section class="panel battle-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">AI Battle Card</p>
          <h2>${escapeHtml(stock.name)} ${escapeHtml(stock.symbol)}</h2>
        </div>
        ${scoreBadge(score.total_score)}
      </div>
      <p>${escapeHtml(score.ai_summary || "尚未建立 AI 總評。")}</p>
      <div class="metric-grid">
        <article class="metric-card"><span>市場別</span><strong>${escapeHtml(stock.market || "--")}</strong></article>
        <article class="metric-card"><span>產業別</span><strong>${escapeHtml(stock.industry || "--")}</strong></article>
        <article class="metric-card"><span>題材</span><strong>${escapeHtml(theme)}</strong></article>
        <article class="metric-card"><span>供應鏈</span><strong>${escapeHtml(supplyChain)}</strong></article>
        <article class="metric-card"><span>資料來源</span><strong>${escapeHtml(stock.data_source || "樣本主檔")}</strong></article>
        <article class="metric-card"><span>風險</span><strong>${riskBadge(score.risk_level)}</strong></article>
      </div>
    </section>

    ${renderTradingRevenueSnapshot(metric)}

    <section class="panel">
      <div class="section-head"><h2>分數拆解</h2></div>
      <div class="score-breakdown">
        ${scoreLine("技術面", score.technical_score)}
        ${scoreLine("籌碼面", score.chip_score)}
        ${scoreLine("基本面", score.fundamental_score)}
        ${scoreLine("消息面", score.news_score)}
        ${scoreLine("風險調整", score.risk_adjustment)}
      </div>
    </section>

    <section class="panel">
      <div class="section-head"><h2>入選理由與風險</h2></div>
      <p><strong>入選理由：</strong>${escapeHtml(score.entry_reason || "未入選今日清單。")}</p>
      <p><strong>風險理由：</strong>${escapeHtml(score.risk_reason || "風險資料尚未建立。")}</p>
      <p><strong>續強條件：</strong>${escapeHtml(score.continuation_condition || "待觀察量價與題材延續。")}</p>
      <p><strong>降評條件：</strong>${escapeHtml(score.downgrade_condition || "若跌破關鍵支撐或題材退潮則降評。")}</p>
    </section>

    <section class="panel">
      <div class="section-head"><h2>新聞事件</h2></div>
      ${relatedNews.length ? relatedNews.map((item) => `
        <article class="news-card">
          <h3>${escapeHtml(item.title)}</h3>
          <div class="news-meta">
            <span>${formatDateTime(item.published_at)}</span>
            <span>${escapeHtml(item.source_name || "--")}</span>
            <span>${statusBadge(item.impact || "中性", item.impact === "偏空" ? "bad" : "good")}</span>
          </div>
          <p>${escapeHtml(item.ai_judgement || item.operation_meaning || "")}</p>
        </article>
      `).join("") : renderEmpty("目前沒有此個股新聞事件")}
    </section>
  `;
}

function bindSearch() {
  const input = $("#stockLookup");
  const search = () => {
    const stock = findStock(input.value);
    if (stock) {
      history.replaceState(null, "", `./stock.html?symbol=${encodeURIComponent(stock.symbol)}`);
      input.value = `${stock.symbol} ${stock.name}`;
    }
    renderStock(stock);
  };

  input.addEventListener("change", search);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      search();
    }
  });
}

async function initStockPage() {
  const loaded = await loadProcessedData(["stocks_master.json", "ai_scores_daily.json", "news_events.json", "stock_metrics_daily.json"]);
  stocks = getItems(loaded["stocks_master.json"].data);
  stockDataUpdatedAt = loaded["stocks_master.json"].data?.updated_at || "";
  scores = getItems(loaded["ai_scores_daily.json"].data);
  news = getItems(loaded["news_events.json"].data);
  metrics = getItems(loaded["stock_metrics_daily.json"].data);
  metricsUpdatedAt = loaded["stock_metrics_daily.json"].data?.updated_at || "";
  metricsRevenueMonth = loaded["stock_metrics_daily.json"].data?.revenue_month || "";

  renderStockOptions();
  bindSearch();
  const querySymbol = getSymbolFromUrl();
  const initialStock = querySymbol ? findStock(querySymbol) : null;
  $("#stockLookup").value = initialStock ? `${initialStock.symbol} ${initialStock.name}` : querySymbol;
  renderStock(initialStock);
}

initStockPage().catch((error) => {
  console.error(error);
  $("#stockDetail").innerHTML = renderEmpty("個股資料載入失敗");
});
