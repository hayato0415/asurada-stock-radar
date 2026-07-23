import { loadProcessedData } from "./api.js?v=20260723-top10";
import { formatDateTime, formatNumber } from "./formatters.js";
import { $, escapeHtml, stockLink } from "./utils.js";

function renderFailure(message) {
  if ($("#themesUpdatedAt")) $("#themesUpdatedAt").textContent = "資料載入失敗";
  if ($("#themesWarning")) {
    $("#themesWarning").innerHTML = `
      <div class="tracking-alert tracking-alert-bad">
        正式多因子評分資料載入失敗，保留上一版或停止更新。${escapeHtml(message ? ` ${message}` : "")}
      </div>
    `;
  }
  ["#industryConcentration", "#themeConcentration"].forEach((selector) => {
    if ($(selector)) $(selector).innerHTML = `<div class="empty-state">目前沒有可用的正式 Top 10 集中度。</div>`;
  });
  if ($("#themeTop10Body")) {
    $("#themeTop10Body").innerHTML = `<tr><td colspan="6"><div class="empty-state">目前沒有可用資料。</div></td></tr>`;
  }
}

function concentrationRows(rows = []) {
  if (!rows.length) return `<div class="empty-state">目前沒有分類資料。</div>`;
  const max = Math.max(...rows.map((row) => Number(row.count || 0)), 1);
  return rows.map((row) => `
    <article class="concentration-item">
      <div class="concentration-head">
        <strong>${escapeHtml(row.name)}</strong>
        <span>${row.count} 檔</span>
      </div>
      <div class="concentration-bar"><span style="width:${(Number(row.count || 0) / max) * 100}%"></span></div>
      <div class="concentration-stocks">
        ${(row.stocks || []).map((stock) => stockLink(stock.code, stock.name)).join("")}
      </div>
    </article>
  `).join("");
}

async function init() {
  const loaded = await loadProcessedData(["ai-top10-daily.json"]);
  const result = loaded["ai-top10-daily.json"];
  if (result.error || !result.data || result.data.ok !== true) {
    console.error(result.error || result.data);
    renderFailure(result.error?.message || "");
    return;
  }

  const daily = result.data;
  const items = Array.isArray(daily.items) ? daily.items : [];
  const industries = Array.isArray(daily.industryConcentration) ? daily.industryConcentration : [];
  const themes = Array.isArray(daily.themeConcentration) ? daily.themeConcentration : [];

  if ($("#themesUpdatedAt")) $("#themesUpdatedAt").textContent = `資料更新：${formatDateTime(daily.generatedAt)}`;
  if ($("#themeTradeDate")) $("#themeTradeDate").textContent = daily.latestTradeDate || "--";
  if ($("#themeTop10Count")) $("#themeTop10Count").textContent = `${items.length} 檔`;
  if ($("#industryGroupCount")) $("#industryGroupCount").textContent = `${industries.length} 類`;
  if ($("#themeGroupCount")) $("#themeGroupCount").textContent = `${themes.length} 類`;
  if ($("#industryConcentration")) $("#industryConcentration").innerHTML = concentrationRows(industries);
  if ($("#themeConcentration")) $("#themeConcentration").innerHTML = concentrationRows(themes);

  if ($("#themesWarning")) {
    $("#themesWarning").innerHTML = `
      <div class="tracking-alert tracking-alert-ok">
        本頁分類來自今日正式 Top 10；題材與產業不參與總分計算。
      </div>
    `;
  }

  if ($("#themeTop10Body")) {
    $("#themeTop10Body").innerHTML = items.length
      ? items.map((item) => `
          <tr>
            <td>#${item.rank}</td>
            <td>${stockLink(item.code, item.name)}</td>
            <td>${escapeHtml(item.market || "--")}</td>
            <td>${escapeHtml(item.industry || "未分類")}</td>
            <td>${escapeHtml((item.concepts || []).join("／") || "未分類")}</td>
            <td><span class="score-badge">${formatNumber(item.totalScore, 1)}</span></td>
          </tr>
        `).join("")
      : `<tr><td colspan="6"><div class="empty-state">今日沒有正式 Top 10。</div></td></tr>`;
  }
}

init();
