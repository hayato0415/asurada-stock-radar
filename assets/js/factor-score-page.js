import { loadProcessedData } from "./api.js?v=20260723-top10";
import { formatDateTime } from "./formatters.js";
import { $, escapeHtml } from "./utils.js";

function metric(label, value) {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`;
}

function renderFailure(message) {
  const panel = $("#factorStatusPanel");
  panel?.classList.add("status-warning");
  if ($("#factorStatusBadge")) $("#factorStatusBadge").textContent = "載入失敗";
  if ($("#factorStatusText")) {
    $("#factorStatusText").textContent = "正式多因子評分資料載入失敗，保留上一版或停止更新。";
  }
  if ($("#factorStatusGrid")) $("#factorStatusGrid").innerHTML = "";
  if ($("#factorSourceList")) {
    $("#factorSourceList").innerHTML = `<div class="tracking-alert tracking-alert-bad">${escapeHtml(message)}</div>`;
  }
}

async function init() {
  const loaded = await loadProcessedData([
    "factor-scores.meta.json",
    "factor-scores.status.json",
  ]);
  const metaResult = loaded["factor-scores.meta.json"];
  const statusResult = loaded["factor-scores.status.json"];
  if (metaResult.error || statusResult.error || !metaResult.data || !statusResult.data) {
    console.error(metaResult.error || statusResult.error);
    renderFailure(metaResult.error?.message || statusResult.error?.message || "正式評分資料不存在");
    return;
  }

  const meta = metaResult.data;
  const status = statusResult.data;
  const persistence = status.persistence_status || {};
  const ok = status.ok === true && persistence.ok === true;
  const panel = $("#factorStatusPanel");
  panel?.classList.add(ok ? "status-ok" : "status-warning");
  if ($("#factorStatusBadge")) $("#factorStatusBadge").textContent = ok ? "同步成功" : "狀態異常";
  if ($("#factorStatusText")) {
    $("#factorStatusText").textContent = ok
      ? "正式四因子評分、每日 Top 10 與歷史快照已同步。"
      : "正式多因子評分資料載入失敗，保留上一版或停止更新。";
  }

  const quality = status.quality || {};
  if ($("#factorStatusGrid")) {
    $("#factorStatusGrid").innerHTML = [
      metric("最新交易日", status.latest_trade_date || "--"),
      metric("評分版本", meta.score_version || "--"),
      metric("有效評分檔數", `${Number(quality.score_candidates || status.items_count || 0).toLocaleString("zh-TW")} 檔`),
      metric("Top 10 歷史交易日", `${Number(persistence.history_trading_days || 0)} 日`),
      metric("最後更新時間", formatDateTime(meta.generated_at || meta.updated_at)),
      metric("新聞權重", "0%"),
    ].join("");
  }

  const sources = meta.sources || {};
  if ($("#factorSourceList")) {
    $("#factorSourceList").innerHTML = Object.entries(sources)
      .map(([name, values]) => `
        <article class="method-card">
          <h3>${escapeHtml(name)}</h3>
          <p>${escapeHtml((Array.isArray(values) ? values : [values]).join("、"))}</p>
        </article>
      `)
      .join("");
  }
}

init();
