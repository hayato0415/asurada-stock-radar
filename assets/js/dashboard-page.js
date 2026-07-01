import { loadProcessedData, getItems } from "./api.js";
import { $, bySymbol, escapeHtml, renderEmpty, stockChipList, stockLink } from "./utils.js";
import { formatNumber, formatSignedPercent, formatDateTime, valueClass } from "./formatters.js";
import { riskBadge, scoreBadge } from "./scoring-ui.js";

const FILES = [
  "stocks_master.json",
  "market_snapshot.json",
  "ai_scores_daily.json",
  "news_events.json",
  "theme_stats.json"
];

function metric(label, value, className = "") {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong class="${className}">${value}</strong></article>`;
}

function renderMarket(snapshot) {
  const root = $("#marketSnapshot");
  if (!root) return;
  if (!snapshot) {
    root.innerHTML = renderEmpty("市場快照資料尚未建立");
    return;
  }

  $("#dashboardUpdatedAt").textContent = `更新：${formatDateTime(snapshot.updated_at)}`;
  root.innerHTML = [
    metric("加權指數", formatNumber(snapshot.taiex_close, 2), valueClass(snapshot.taiex_change)),
    metric("漲跌", formatNumber(snapshot.taiex_change, 2), valueClass(snapshot.taiex_change)),
    metric("漲跌幅", formatSignedPercent(snapshot.taiex_change_pct), valueClass(snapshot.taiex_change_pct)),
    metric("成交金額", `${formatNumber(snapshot.turnover_billion, 0)} 億`),
    metric("市場溫度", `${formatNumber(snapshot.market_temperature, 0)} / 100`),
    metric("上漲家數", formatNumber(snapshot.up_count), "value-up"),
    metric("下跌家數", formatNumber(snapshot.down_count), "value-down"),
    metric("漲停 / 跌停", `${formatNumber(snapshot.limit_up_count)} / ${formatNumber(snapshot.limit_down_count)}`)
  ].join("");
}

function renderSummary(aiItems, newsItems, themeItems) {
  const root = $("#dashboardSummary");
  if (!root) return;
  const topStock = aiItems[0];
  const topTheme = themeItems[0];
  const highRiskNews = newsItems.filter((item) => item.impact === "偏空").length;
  root.innerHTML = [
    metric("最強題材", topTheme ? escapeHtml(topTheme.theme) : "--"),
    metric("AI 最高分", topStock ? `${stockLink(topStock.symbol, topStock.name)} ${scoreBadge(topStock.total_score)}` : "--"),
    metric("今日重大新聞", `${newsItems.length} 則`),
    metric("利空風險事件", `${highRiskNews} 則`, highRiskNews ? "value-down" : "value-flat")
  ].join("");
}

function renderRadarRows(aiItems) {
  const tbody = $("#dashboardRadarRows");
  if (!tbody) return;
  const topFive = aiItems.slice(0, 5);
  tbody.innerHTML = topFive.length
    ? topFive.map((item, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${stockLink(item.symbol, item.name)}</td>
        <td>${escapeHtml(item.theme)}</td>
        <td>${scoreBadge(item.total_score)}</td>
        <td>${escapeHtml(item.pattern)}</td>
        <td>${riskBadge(item.risk_level)}</td>
        <td>${escapeHtml(item.entry_reason)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="7">${renderEmpty("目前沒有 AI 選股資料")}</td></tr>`;
}

function renderNews(newsItems) {
  const root = $("#dashboardNewsList");
  if (!root) return;
  const topNews = newsItems
    .slice()
    .sort((a, b) => Number(b.news_score) - Number(a.news_score))
    .slice(0, 5);

  root.innerHTML = topNews.length
    ? topNews.map((item) => `
      <article class="news-compact-item">
        <small>${formatDateTime(item.published_at)}</small>
        <div>
          ${item.source_url
            ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>`
            : `<strong>${escapeHtml(item.title)}</strong>`}
          <small>${escapeHtml(item.theme)} · ${escapeHtml(item.source_name)} · 來源等級 ${escapeHtml(item.source_grade)}</small>
        </div>
        <span class="score-badge">${escapeHtml(item.news_score)}</span>
      </article>
    `).join("")
    : renderEmpty("重大新聞資料尚未建立");
}

async function initDashboard() {
  const loaded = await loadProcessedData(FILES);
  const stocks = getItems(loaded["stocks_master.json"].data);
  const stocksMap = bySymbol(stocks);
  const aiItems = getItems(loaded["ai_scores_daily.json"].data)
    .map((item) => ({ ...stocksMap.get(String(item.symbol)), ...item }))
    .sort((a, b) => Number(b.total_score) - Number(a.total_score));
  const newsItems = getItems(loaded["news_events.json"].data);
  const themeItems = getItems(loaded["theme_stats.json"].data)
    .sort((a, b) => Number(b.theme_score) - Number(a.theme_score));

  renderMarket(loaded["market_snapshot.json"].data);
  renderSummary(aiItems, newsItems, themeItems);
  renderRadarRows(aiItems);
  renderNews(newsItems);
}

initDashboard().catch((error) => {
  console.error(error);
  $("#marketSnapshot").innerHTML = renderEmpty("市場總覽載入失敗，請確認 data/processed JSON。");
});
