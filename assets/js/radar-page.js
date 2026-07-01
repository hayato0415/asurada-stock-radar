import { loadProcessedData, getItems } from "./api.js";
import { $, bySymbol, escapeHtml, renderEmpty, stockLink } from "./utils.js";
import { formatDateTime } from "./formatters.js";
import { populateSelect, textMatches, minScoreMatches } from "./filters.js";
import { riskBadge, scoreBadge } from "./scoring-ui.js";

let rows = [];

function applyFilters() {
  const query = $("#stockSearch").value;
  const theme = $("#themeFilter").value;
  const pattern = $("#patternFilter").value;
  const minScore = $("#scoreFilter").value;
  const risk = $("#riskFilter").value;

  return rows.filter((item) => {
    return textMatches(item, query, ["symbol", "name"]) &&
      (!theme || item.theme === theme) &&
      (!pattern || item.pattern === pattern) &&
      (!risk || item.risk_level === risk) &&
      minScoreMatches(item.total_score, minScore);
  });
}

function renderTable(filteredRows) {
  const tbody = $("#radarTableBody");
  $("#radarCount").textContent = `${filteredRows.length} 檔`;
  tbody.innerHTML = filteredRows.length
    ? filteredRows.map((item, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${stockLink(item.symbol, item.name)}</td>
        <td>${escapeHtml(item.theme)}</td>
        <td>${escapeHtml(item.pattern)}</td>
        <td>${scoreBadge(item.total_score)}</td>
        <td>${escapeHtml(item.technical_score)}</td>
        <td>${escapeHtml(item.chip_score)}</td>
        <td>${escapeHtml(item.fundamental_score)}</td>
        <td>${escapeHtml(item.news_score)}</td>
        <td>${riskBadge(item.risk_level)}</td>
        <td>${escapeHtml(item.entry_reason)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="11">${renderEmpty("沒有符合條件的股票")}</td></tr>`;
}

function bindFilters() {
  ["stockSearch", "themeFilter", "patternFilter", "scoreFilter", "riskFilter"].forEach((id) => {
    $(`#${id}`).addEventListener("input", () => renderTable(applyFilters()));
    $(`#${id}`).addEventListener("change", () => renderTable(applyFilters()));
  });
}

async function initRadar() {
  const loaded = await loadProcessedData(["stocks_master.json", "ai_scores_daily.json"]);
  const stocks = getItems(loaded["stocks_master.json"].data);
  const scores = getItems(loaded["ai_scores_daily.json"].data);
  const stocksMap = bySymbol(stocks);
  rows = scores
    .map((item) => ({ ...stocksMap.get(String(item.symbol)), ...item }))
    .sort((a, b) => Number(b.total_score) - Number(a.total_score));

  $("#radarUpdatedAt").textContent = `資料更新：${formatDateTime(loaded["ai_scores_daily.json"].data?.updated_at)}`;
  populateSelect($("#themeFilter"), rows.map((item) => item.theme), "全部題材");
  populateSelect($("#patternFilter"), rows.map((item) => item.pattern), "全部型態");
  populateSelect($("#riskFilter"), rows.map((item) => item.risk_level), "全部風險");
  bindFilters();
  renderTable(rows);
}

initRadar().catch((error) => {
  console.error(error);
  $("#radarTableBody").innerHTML = `<tr><td colspan="11">${renderEmpty("AI 選股清單載入失敗")}</td></tr>`;
});
