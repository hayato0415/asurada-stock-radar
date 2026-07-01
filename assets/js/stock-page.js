import { loadProcessedData, getItems } from "./api.js";
import { $, bySymbol, escapeHtml, renderEmpty, stockChipList } from "./utils.js";
import { formatDateTime } from "./formatters.js";
import { riskBadge, scoreBadge, statusBadge } from "./scoring-ui.js";

let stocks = [];
let scores = [];
let news = [];

function getSymbolFromUrl() {
  return new URLSearchParams(window.location.search).get("symbol") || "";
}

function findStock(query) {
  const value = String(query || "").trim().toLowerCase();
  return stocks.find((stock) => stock.symbol === value || stock.name.toLowerCase().includes(value));
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

function renderStock(stock) {
  const root = $("#stockDetail");
  if (!stock) {
    root.innerHTML = renderEmpty("請輸入股票代號或名稱查詢個股 AI 分析");
    return;
  }

  const score = scores.find((item) => item.symbol === stock.symbol) || {};
  const relatedNews = news.filter((item) => item.stocks?.some((newsStock) => String(newsStock.code ?? newsStock.symbol) === stock.symbol));

  $("#stockUpdatedAt").textContent = `資料更新：${formatDateTime(score.updated_at || score.market_date)}`;
  root.innerHTML = `
    <section class="panel battle-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">AI Battle Card</p>
          <h2>${escapeHtml(stock.name)} ${escapeHtml(stock.symbol)}</h2>
        </div>
        ${scoreBadge(score.total_score)}
      </div>
      <p>${escapeHtml(score.ai_summary || "尚無 AI 總評。")}</p>
      <div class="metric-grid">
        <article class="metric-card"><span>市場</span><strong>${escapeHtml(stock.market)}</strong></article>
        <article class="metric-card"><span>產業</span><strong>${escapeHtml(stock.industry)}</strong></article>
        <article class="metric-card"><span>題材</span><strong>${escapeHtml(score.theme || stock.theme)}</strong></article>
        <article class="metric-card"><span>風險</span><strong>${riskBadge(score.risk_level)}</strong></article>
      </div>
    </section>

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
            <span>${escapeHtml(item.source_name)}</span>
            <span>${statusBadge(item.impact, item.impact === "偏空" ? "bad" : "good")}</span>
          </div>
          <p>${escapeHtml(item.ai_judgement)}</p>
        </article>
      `).join("") : renderEmpty("目前沒有此個股新聞事件")}
    </section>
  `;
}

function bindSearch() {
  const input = $("#stockLookup");
  input.addEventListener("change", () => {
    const stock = findStock(input.value);
    if (stock) {
      history.replaceState(null, "", `./stock.html?symbol=${encodeURIComponent(stock.symbol)}`);
    }
    renderStock(stock);
  });
}

async function initStockPage() {
  const loaded = await loadProcessedData(["stocks_master.json", "ai_scores_daily.json", "news_events.json"]);
  stocks = getItems(loaded["stocks_master.json"].data);
  scores = getItems(loaded["ai_scores_daily.json"].data);
  news = getItems(loaded["news_events.json"].data);

  bindSearch();
  const querySymbol = getSymbolFromUrl();
  const initialStock = querySymbol ? findStock(querySymbol) : stocks[0];
  $("#stockLookup").value = initialStock ? `${initialStock.symbol} ${initialStock.name}` : "";
  renderStock(initialStock);
}

initStockPage().catch((error) => {
  console.error(error);
  $("#stockDetail").innerHTML = renderEmpty("個股資料載入失敗");
});
