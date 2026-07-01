import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, renderEmpty, stockLink } from "./utils.js";
import { formatDateTime, formatNumber, formatSignedPercent, valueClass } from "./formatters.js";
import { scoreBadge, statusBadge } from "./scoring-ui.js";

function metric(label, value, className = "") {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong class="${className}">${value}</strong></article>`;
}

async function initBacktest() {
  const loaded = await loadProcessedData(["backtest_results.json"]);
  const payload = loaded["backtest_results.json"].data;
  const rows = getItems(payload);
  $("#backtestUpdatedAt").textContent = `資料更新：${formatDateTime(payload?.updated_at)}`;
  const summary = payload?.summary || {};
  $("#backtestSummary").innerHTML = [
    metric("5 日命中率", formatSignedPercent(summary.hit_rate_5d)),
    metric("10 日命中率", formatSignedPercent(summary.hit_rate_10d)),
    metric("20 日命中率", formatSignedPercent(summary.hit_rate_20d)),
    metric("平均最大回撤", formatSignedPercent(summary.avg_max_drawdown), valueClass(summary.avg_max_drawdown))
  ].join("");

  $("#backtestRows").innerHTML = rows.length
    ? rows.map((item) => `
      <tr>
        <td>${escapeHtml(item.date)}</td>
        <td>${escapeHtml(item.rank)}</td>
        <td>${stockLink(item.symbol, item.name)}</td>
        <td>${scoreBadge(item.ai_score)}</td>
        <td class="${valueClass(item.return_5d)}">${formatSignedPercent(item.return_5d)}</td>
        <td class="${valueClass(item.return_10d)}">${formatSignedPercent(item.return_10d)}</td>
        <td class="${valueClass(item.return_20d)}">${formatSignedPercent(item.return_20d)}</td>
        <td class="${valueClass(item.max_gain)}">${formatSignedPercent(item.max_gain)}</td>
        <td class="${valueClass(item.max_drawdown)}">${formatSignedPercent(item.max_drawdown)}</td>
        <td>${statusBadge(item.hit ? "命中" : "未命中", item.hit ? "good" : "warn")}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="10">${renderEmpty("回測資料尚未建立")}</td></tr>`;
}

if (document.body.dataset.page === "backtest") {
  initBacktest().catch((error) => {
    console.error(error);
    $("#backtestRows").innerHTML = `<tr><td colspan="10">${renderEmpty("回測資料載入失敗")}</td></tr>`;
  });
}
