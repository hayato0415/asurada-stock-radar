import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, renderEmpty, stockChipList } from "./utils.js";
import { formatDateTime, formatNumber, formatSignedPercent } from "./formatters.js";
import { scoreBadge } from "./scoring-ui.js";

async function initThemes() {
  const loaded = await loadProcessedData(["theme_stats.json"]);
  const payload = loaded["theme_stats.json"].data;
  const rows = getItems(payload).sort((a, b) => Number(b.theme_score) - Number(a.theme_score));
  $("#themesUpdatedAt").textContent = `資料更新：${formatDateTime(payload?.updated_at)}`;
  $("#themesTableBody").innerHTML = rows.length
    ? rows.map((item, index) => `
      <tr>
        <td>${index + 1}</td>
        <td><span class="theme-name">${escapeHtml(item.theme)}</span></td>
        <td>${scoreBadge(item.theme_score)}</td>
        <td>${formatSignedPercent(item.theme_change_pct)}</td>
        <td>${formatNumber(item.turnover_billion, 1)} 億</td>
        <td>${formatNumber(item.up_count)}</td>
        <td>${formatNumber(item.limit_up_count)}</td>
        <td>${formatNumber(item.high_score_news_count)}</td>
        <td><div class="stock-chip-list">${stockChipList(item.leader_stocks)}</div></td>
        <td><div class="stock-chip-list">${stockChipList(item.low_base_stocks)}</div></td>
      </tr>
    `).join("")
    : `<tr><td colspan="10">${renderEmpty("題材資料尚未建立")}</td></tr>`;
}

initThemes().catch((error) => {
  console.error(error);
  $("#themesTableBody").innerHTML = `<tr><td colspan="10">${renderEmpty("題材資料載入失敗")}</td></tr>`;
});
