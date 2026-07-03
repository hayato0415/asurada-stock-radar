import { loadProcessedData, getItems } from "./api.js";
import { $, bySymbol, escapeHtml, initTableFreezeToggles, renderEmpty, stockLink } from "./utils.js";
import { formatDateTime, formatNumber, formatPercent, formatSignedPercent, valueClass } from "./formatters.js";
import { populateSelect, textMatches, minScoreMatches } from "./filters.js";
import { riskBadge, scoreBadge } from "./scoring-ui.js";

const DISPLAY_LIMIT = 100;
const VALID_MARKETS = new Set(["上市", "上櫃"]);

let rows = [];
let coverage = {
  universe: 0,
  stocksMaster: 0,
  quoteMatched: 0,
  revenueMatched: 0,
};

function numeric(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function roundScore(value) {
  return Math.round(clamp(value) * 10) / 10;
}

function normalizeScore(value) {
  const number = numeric(value);
  return number === null ? null : roundScore(number);
}

function scoreFromRange(value, min, max, fallback = 42) {
  const number = numeric(value);
  if (number === null) return fallback;
  if (max === min) return fallback;
  return clamp(((number - min) / (max - min)) * 100);
}

function hasValue(value) {
  return numeric(value) !== null;
}

function firstValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "");
}

function getTheme(stock, score) {
  return firstValue(score.theme, stock.theme, stock.supply_chain, stock.industry, "未分類");
}

function getPattern(row) {
  if (row.pattern) return row.pattern;
  if (numeric(row.revenue_yoy_pct) >= 30) return "營收高成長";
  if (numeric(row.gross_margin_pct) >= 35) return "高毛利率";
  if (numeric(row.eps) > 0) return "獲利篩選";
  if (numeric(row.change_pct) > 0) return "量價轉強";
  return "全市場量化";
}

function inferRisk(row) {
  if (row.risk_level) return row.risk_level;
  const change = numeric(row.change_pct);
  const turnover = numeric(row.turnover_rate_pct);
  const volume = numeric(row.volume);
  if ((change !== null && change >= 7) || (turnover !== null && turnover >= 10)) return "高";
  if ((change !== null && change <= -5) || !volume) return "中";
  return "低";
}

function inferTechnicalScore(metric) {
  const changeScore = scoreFromRange(metric.change_pct, -8, 8, 42);
  const turnoverScore = scoreFromRange(metric.turnover_rate_pct, 0, 8, 38);
  return roundScore(changeScore * 0.65 + turnoverScore * 0.35);
}

function inferChipScore(metric) {
  const turnoverScore = scoreFromRange(metric.turnover_rate_pct, 0, 10, 38);
  const volumeScore = scoreFromRange(metric.volume, 0, 20000000, 35);
  return roundScore(turnoverScore * 0.55 + volumeScore * 0.45);
}

function inferTurnoverScore(metric) {
  return roundScore(scoreFromRange(metric.turnover_rate_pct, 0, 12, 38));
}

function inferFundamentalScore(metric) {
  const yoyScore = scoreFromRange(metric.revenue_yoy_pct, -30, 80, 38);
  const momScore = scoreFromRange(metric.revenue_mom_pct, -20, 50, 40);
  const epsScore = scoreFromRange(metric.eps, -2, 8, 38);
  const marginScore = scoreFromRange(metric.gross_margin_pct, 0, 50, 38);
  return roundScore(yoyScore * 0.35 + momScore * 0.2 + epsScore * 0.25 + marginScore * 0.2);
}

function inferDataQualityScore(metric) {
  const fields = [
    "trade_price",
    "change_pct",
    "volume",
    "revenue_million",
    "revenue_yoy_pct",
    "eps",
    "gross_margin_pct",
  ];
  const covered = fields.filter((field) => hasValue(metric[field])).length;
  return roundScore((covered / fields.length) * 100);
}

function inferEntryReason(row) {
  if (row.entry_reason) return row.entry_reason;
  const reasons = [];
  if (hasValue(row.revenue_yoy_pct)) reasons.push(`營收年增 ${formatSignedPercent(row.revenue_yoy_pct, 2)}`);
  if (hasValue(row.revenue_mom_pct)) reasons.push(`月增 ${formatSignedPercent(row.revenue_mom_pct, 2)}`);
  if (hasValue(row.eps)) reasons.push(`EPS ${formatNumber(row.eps, 2)}`);
  if (hasValue(row.gross_margin_pct)) reasons.push(`毛利率 ${formatPercent(row.gross_margin_pct, 2)}`);
  if (hasValue(row.turnover_rate_pct)) reasons.push(`週轉率 ${formatPercent(row.turnover_rate_pct, 2)}`);
  return reasons.length ? reasons.slice(0, 4).join("，") : "資料不足，保留於個股查詢檢視。";
}

function buildRow(stock, score = {}, metric = {}) {
  const merged = {
    ...stock,
    ...metric,
    ...score,
    name: firstValue(stock.name, metric.name, score.name, ""),
    market: firstValue(stock.market, score.market, ""),
    industry: firstValue(stock.industry, score.industry, ""),
  };
  merged.theme = getTheme(stock, score);

  const technical = normalizeScore(score.technical_score) ?? inferTechnicalScore(merged);
  const chip = normalizeScore(score.chip_score) ?? inferChipScore(merged);
  const fundamental = normalizeScore(score.fundamental_score) ?? inferFundamentalScore(merged);
  const turnover = normalizeScore(score.turnover_score) ?? inferTurnoverScore(merged);
  const dataQuality = inferDataQualityScore(merged);

  merged.technical_score = technical;
  merged.chip_score = chip;
  merged.fundamental_score = fundamental;
  merged.turnover_score = turnover;
  merged.news_score = null;
  merged.news_scoring_included = false;
  merged.theme_scoring_included = false;
  merged.data_quality_score = dataQuality;
  merged.total_score = normalizeScore(score.total_score) ?? roundScore(
    fundamental * 0.30 +
    technical * 0.30 +
    chip * 0.25 +
    turnover * 0.15
  );
  merged.pattern = getPattern(merged);
  merged.risk_level = inferRisk(merged);
  merged.entry_reason = inferEntryReason(merged);
  return merged;
}

function minNumberMatches(value, threshold) {
  if (threshold === "" || threshold === null || threshold === undefined) return true;
  const number = numeric(value);
  return number !== null && number >= Number(threshold);
}

function applyFilters() {
  const query = $("#stockSearch").value;
  const market = $("#marketFilter").value;
  const theme = $("#themeFilter").value;
  const pattern = $("#patternFilter").value;
  const minScore = $("#scoreFilter").value;
  const risk = $("#riskFilter").value;
  const revenueYoy = $("#revenueYoyFilter").value;
  const eps = $("#epsFilter").value;
  const grossMargin = $("#grossMarginFilter").value;

  return rows.filter((item) => {
    return textMatches(item, query, ["symbol", "name", "industry", "theme"]) &&
      (!market || item.market === market) &&
      (!theme || item.theme === theme) &&
      (!pattern || item.pattern === pattern) &&
      (!risk || item.risk_level === risk) &&
      minScoreMatches(item.total_score, minScore) &&
      minNumberMatches(item.revenue_yoy_pct, revenueYoy) &&
      minNumberMatches(item.eps, eps) &&
      minNumberMatches(item.gross_margin_pct, grossMargin);
  });
}

function renderCoverage(filteredRows, displayRows) {
  const hidden = Math.max(0, filteredRows.length - displayRows.length);
  $("#radarCoverage").textContent =
    `全市場 ${coverage.universe} 檔；目前篩選符合 ${filteredRows.length} 檔；畫面列出前 ${displayRows.length} 檔；尚有 ${hidden} 檔未列入畫面，可用個股查詢查看。` +
    `資料覆蓋：主檔 ${coverage.stocksMaster} 檔、報價 ${coverage.quoteMatched} 檔、營收 ${coverage.revenueMatched} 檔。`;
}

function formatMaybeNumber(value, digits = 2) {
  return hasValue(value) ? formatNumber(value, digits) : "--";
}

function formatMaybePercent(value, digits = 2) {
  return hasValue(value) ? formatPercent(value, digits) : "--";
}

function formatMaybeSignedPercent(value, digits = 2) {
  return hasValue(value) ? formatSignedPercent(value, digits) : "--";
}

function detailMetric(label, value, extraClass = "") {
  return `
    <div class="radar-detail-item ${extraClass}">
      <span>${escapeHtml(label)}</span>
      <strong>${value}</strong>
    </div>
  `;
}

function renderRowDetails(item) {
  return `
    <details class="radar-row-details">
      <summary>展開</summary>
      <div class="radar-detail-grid">
        ${detailMetric("成交量", formatMaybeNumber(item.volume, 0))}
        ${detailMetric("週轉率", formatMaybePercent(item.turnover_rate_pct, 2))}
        ${detailMetric("營收(百萬)", formatMaybeNumber(item.revenue_million, 2))}
        ${detailMetric("EPS", formatMaybeNumber(item.eps, 2))}
        ${detailMetric("毛利率", formatMaybePercent(item.gross_margin_pct, 2))}
        ${detailMetric("技術面", scoreBadge(item.technical_score))}
        ${detailMetric("籌碼", scoreBadge(item.chip_score))}
        ${detailMetric("週轉率分數", scoreBadge(item.turnover_score))}
        ${detailMetric("入選理由", escapeHtml(item.entry_reason), "radar-detail-wide")}
      </div>
    </details>
  `;
}

function renderTable(filteredRows) {
  const tbody = $("#radarTableBody");
  const displayRows = filteredRows.slice(0, DISPLAY_LIMIT);
  $("#radarCount").textContent = `前 ${displayRows.length} / ${filteredRows.length} 檔`;
  renderCoverage(filteredRows, displayRows);
  tbody.innerHTML = displayRows.length
    ? displayRows.map((item, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${stockLink(item.symbol, item.name)}</td>
        <td>${escapeHtml(item.market || "--")}</td>
        <td>${escapeHtml(item.industry || "--")}</td>
        <td>${escapeHtml(item.theme || "未分類")}</td>
        <td>${scoreBadge(item.total_score)}</td>
        <td>${scoreBadge(item.fundamental_score)}</td>
        <td>${formatMaybeNumber(item.trade_price, 2)}</td>
        <td class="${valueClass(item.change_pct)}">${formatMaybeSignedPercent(item.change_pct, 2)}</td>
        <td class="${valueClass(item.revenue_yoy_pct)}">${formatMaybeSignedPercent(item.revenue_yoy_pct, 2)}</td>
        <td>${riskBadge(item.risk_level)}</td>
        <td class="detail-cell">${renderRowDetails(item)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="12">${renderEmpty("沒有符合條件的股票")}</td></tr>`;
}

function bindFilters() {
  [
    "stockSearch",
    "marketFilter",
    "themeFilter",
    "patternFilter",
    "scoreFilter",
    "revenueYoyFilter",
    "epsFilter",
    "grossMarginFilter",
    "riskFilter",
  ].forEach((id) => {
    const element = $(`#${id}`);
    element.addEventListener("input", () => renderTable(applyFilters()));
    element.addEventListener("change", () => renderTable(applyFilters()));
  });
}

function sortRows(a, b) {
  return Number(b.total_score || 0) - Number(a.total_score || 0) ||
    Number(b.fundamental_score || 0) - Number(a.fundamental_score || 0) ||
    Number(b.revenue_yoy_pct ?? -999999) - Number(a.revenue_yoy_pct ?? -999999);
}

async function initRadar() {
  initTableFreezeToggles();

  const loaded = await loadProcessedData(["stocks_master.json", "ai_scores_daily.json", "stock_metrics_daily.json"]);
  const stocks = getItems(loaded["stocks_master.json"].data).filter((stock) => VALID_MARKETS.has(stock.market));
  const scores = getItems(loaded["ai_scores_daily.json"].data);
  const metrics = getItems(loaded["stock_metrics_daily.json"].data);
  const scoresMap = bySymbol(scores);
  const metricsMap = bySymbol(metrics);
  const quality = loaded["stock_metrics_daily.json"].data?.quality || {};

  coverage = {
    universe: stocks.length,
    stocksMaster: stocks.length,
    quoteMatched: Number(quality.daily_quote_matched || metrics.filter((item) => hasValue(item.trade_price)).length),
    revenueMatched: Number(quality.revenue_matched || metrics.filter((item) => hasValue(item.revenue_million)).length),
  };

  rows = stocks
    .map((stock) => buildRow(stock, scoresMap.get(String(stock.symbol)) || {}, metricsMap.get(String(stock.symbol)) || {}))
    .sort(sortRows);

  $("#radarUpdatedAt").textContent = `資料更新：${formatDateTime(loaded["stock_metrics_daily.json"].data?.updated_at || loaded["ai_scores_daily.json"].data?.updated_at)}`;
  populateSelect($("#themeFilter"), rows.map((item) => item.theme), "全部題材");
  populateSelect($("#patternFilter"), rows.map((item) => item.pattern), "全部型態");
  populateSelect($("#riskFilter"), rows.map((item) => item.risk_level), "全部風險");
  bindFilters();
  renderTable(rows);
}

initRadar().catch((error) => {
  console.error(error);
  $("#radarTableBody").innerHTML = `<tr><td colspan="12">${renderEmpty("AI 選股清單載入失敗")}</td></tr>`;
});
