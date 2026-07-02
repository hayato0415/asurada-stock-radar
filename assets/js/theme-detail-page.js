import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, renderEmpty, stockLink, unique } from "./utils.js";
import { formatDateTime, formatNumber, formatPercent, formatSignedPercent, valueClass } from "./formatters.js";
import { scoreBadge } from "./scoring-ui.js";

function asNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replaceAll(",", "").replace("%", ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function sourceLabel(type) {
  return {
    manual: "手動題材對應",
    ai: "AI 題材標籤",
    news: "新聞事件",
    master: "主檔產業 / 供應鏈",
  }[type] ?? type;
}

function sourceBadges(types = []) {
  const labels = unique(types).map((type) => sourceLabel(type));
  return labels.length
    ? `<span class="source-badge-list">${labels.map((label) => `<span class="source-badge">${escapeHtml(label)}</span>`).join("")}</span>`
    : "--";
}

function findTheme(items, themeName) {
  const decoded = String(themeName ?? "").trim();
  return items.find((item) => item.theme === decoded)
    ?? items.find((item) => String(item.theme ?? "").toLowerCase() === decoded.toLowerCase())
    ?? null;
}

function metricCard(label, value) {
  return `
    <div class="theme-detail-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${value}</strong>
    </div>
  `;
}

function renderOverview(item, payload) {
  $("#themeDetailTitle").textContent = `${item.theme}｜受惠個股明細`;
  $("#themeDetailSummary").textContent = "獨立頁面顯示此題材所有受惠股，避免題材排名頁展開後占用過多版面。";
  $("#themeDetailUpdatedAt").textContent = `資料更新：${formatDateTime(payload?.updated_at)}`;
  $("#themeDetailCount").textContent = `${formatNumber(item.beneficiary_count)} 檔`;
  $("#themeDetailMetrics").innerHTML = [
    metricCard("題材強度", scoreBadge(item.theme_score)),
    metricCard("題材漲幅", `<span class="${valueClass(item.theme_change_pct)}">${formatSignedPercent(item.theme_change_pct)}</span>`),
    metricCard("成交金額", `${formatNumber(item.turnover_billion, 2)} 億`),
    metricCard("上漲家數", formatNumber(item.up_count)),
    metricCard("漲停家數", formatNumber(item.limit_up_count)),
    metricCard("新聞數", formatNumber(item.high_score_news_count)),
  ].join("");
}

function renderBeneficiaries(stocks = []) {
  const sorted = [...stocks].sort((a, b) => {
    return (asNumber(b.total_score) ?? 0) - (asNumber(a.total_score) ?? 0)
      || (asNumber(b.turnover_billion) ?? 0) - (asNumber(a.turnover_billion) ?? 0);
  });

  $("#themeBeneficiaryBody").innerHTML = sorted.length
    ? sorted.map((stock) => `
      <tr>
        <td>${stockLink(stock.symbol, stock.name)}</td>
        <td>${escapeHtml(stock.market ?? "--")}</td>
        <td>${escapeHtml(stock.industry ?? "--")}</td>
        <td>${formatNumber(stock.trade_price, 2)}</td>
        <td class="${valueClass(stock.change_pct)}">${formatSignedPercent(stock.change_pct)}</td>
        <td>${formatNumber(stock.turnover_billion, 2)}</td>
        <td class="${valueClass(stock.revenue_yoy_pct)}">${formatSignedPercent(stock.revenue_yoy_pct)}</td>
        <td>${formatNumber(stock.eps, 2)}</td>
        <td>${formatPercent(stock.gross_margin_pct, 2)}</td>
        <td>${formatNumber(stock.total_score, 1)}</td>
        <td>${sourceBadges(stock.source_types)}</td>
        <td class="reason-cell">${escapeHtml(stock.reason ?? "--")}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="12">${renderEmpty("此題材目前沒有可辨識受惠個股")}</td></tr>`;
}

async function initThemeDetail() {
  const params = new URLSearchParams(window.location.search);
  const themeName = params.get("theme");
  const loaded = await loadProcessedData(["theme_stats.json"]);
  const payload = loaded["theme_stats.json"].data;
  const items = getItems(payload);
  const item = findTheme(items, themeName);

  if (!item) {
    $("#themeDetailTitle").textContent = "找不到題材";
    $("#themeDetailSummary").textContent = "請回到題材資金輪動頁重新選擇題材。";
    $("#themeDetailUpdatedAt").textContent = `資料更新：${formatDateTime(payload?.updated_at)}`;
    $("#themeDetailMetrics").innerHTML = renderEmpty("找不到對應的題材資料");
    $("#themeBeneficiaryBody").innerHTML = `<tr><td colspan="12">${renderEmpty("沒有可顯示的受惠個股")}</td></tr>`;
    return;
  }

  renderOverview(item, payload);
  renderBeneficiaries(item.beneficiary_stocks ?? []);
}

initThemeDetail().catch((error) => {
  console.error(error);
  $("#themeDetailTitle").textContent = "題材明細載入失敗";
  $("#themeDetailSummary").textContent = "請確認 data/processed/theme_stats.json 是否存在。";
  $("#themeDetailMetrics").innerHTML = renderEmpty("題材資料載入失敗");
  $("#themeBeneficiaryBody").innerHTML = `<tr><td colspan="12">${renderEmpty("題材資料載入失敗")}</td></tr>`;
});
