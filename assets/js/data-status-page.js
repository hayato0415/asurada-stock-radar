import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, renderEmpty } from "./utils.js";
import { formatDateTime, formatNumber } from "./formatters.js";
import { statusBadge } from "./scoring-ui.js";

async function initDataStatus() {
  const loaded = await loadProcessedData(["update_log.json"]);
  const payload = loaded["update_log.json"].data;
  const rows = getItems(payload);
  $("#dataStatusUpdatedAt").textContent = `資料更新：${formatDateTime(payload?.updated_at)}`;
  $("#dataStatusRows").innerHTML = rows.length
    ? rows.map((item) => `
      <tr>
        <td><code>${escapeHtml(item.file)}</code></td>
        <td>${formatDateTime(item.updated_at)}</td>
        <td>${formatNumber(item.count)}</td>
        <td>${statusBadge(item.status, item.status === "ok" ? "good" : "bad")}</td>
        <td>${escapeHtml(item.error || "-")}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="5">${renderEmpty("資料更新紀錄尚未建立")}</td></tr>`;
}

initDataStatus().catch((error) => {
  console.error(error);
  $("#dataStatusRows").innerHTML = `<tr><td colspan="5">${renderEmpty("資料狀態載入失敗")}</td></tr>`;
});
