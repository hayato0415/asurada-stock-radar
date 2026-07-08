const STATUS_FILES = [
  { key: "updateLog", label: "全市場更新紀錄", path: "./data/update_status.json" },
  { key: "radarStatus", label: "雷達收盤狀態", path: "./data/update_status.json" },
  { key: "factorStatus", label: "多因子狀態", path: "./data/processed/factor-scores.status.json" },
  { key: "factorMeta", label: "多因子中繼資料", path: "./data/processed/factor-scores.meta.json" },
];

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toArray(value) {
  if (Array.isArray(value)) return value;
  if (value == null || value === "") return [];
  return [value];
}

function formatDateTime(value) {
  if (!value) return "--";
  const text = String(value);
  const normalized = text.replace("T", " ").replace(/\+08:00$/, "");
  return normalized.slice(0, 19);
}

function formatNumber(value) {
  if (value == null || value === "") return "--";
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-TW") : escapeHtml(value);
}

function getItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of ["items", "data", "scores", "stocks", "rows", "rankings", "events", "files"]) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

function getCount(payload) {
  if (!payload || typeof payload !== "object") return getItems(payload).length;
  return payload.items_count ?? payload.count ?? getItems(payload).length;
}

function statusText(status, ok) {
  if (ok === true) return "OK";
  if (ok === false) return "FAILED";
  const normalized = String(status || "").toLowerCase();
  if (["ok", "success"].includes(normalized)) return "OK";
  if (["failed", "error", "partial_failed"].includes(normalized)) return "FAILED";
  if (["stale", "warning"].includes(normalized)) return "STALE";
  if (!normalized) return "UNKNOWN";
  return normalized.toUpperCase();
}

function statusClass(status, ok) {
  const text = statusText(status, ok);
  if (text === "OK") return "ok";
  if (text === "STALE" || text === "WARNING") return "warn";
  if (text === "FAILED") return "bad";
  return "muted";
}

function renderBadge(status, ok) {
  const text = statusText(status, ok);
  return `<span class="status-badge status-${statusClass(status, ok)}">${escapeHtml(text)}</span>`;
}

async function fetchJson(config) {
  const separator = config.path.includes("?") ? "&" : "?";
  const url = `${config.path}${separator}t=${Date.now()}`;
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return { ...config, ok: true, data: await response.json(), error: "" };
  } catch (error) {
    return { ...config, ok: false, data: null, error: error instanceof Error ? error.message : String(error) };
  }
}

function renderSummary(results) {
  const updateLog = results.updateLog?.data || {};
  const radarStatus = results.radarStatus?.data || {};
  const factorStatus = results.factorStatus?.data || {};
  const factorMeta = results.factorMeta?.data || {};

  const summaryItems = [
    {
      label: "全市場資料最後更新",
      value: formatDateTime(updateLog.updated_at),
      status: updateLog.status,
      ok: updateLog.status === "ok",
    },
    {
      label: "雷達收盤資料 trade_date",
      value: radarStatus.trade_date || radarStatus.latest_trade_date || "--",
      status: radarStatus.status,
      ok: radarStatus.status === "ok",
    },
    {
      label: "多因子分數 latest_trade_date",
      value: factorStatus.latest_trade_date || factorMeta.latest_trade_date || "--",
      status: factorStatus.ok === false ? "failed" : "ok",
      ok: factorStatus.ok,
    },
    {
      label: "整體最新交易日",
      value: updateLog.latest_trade_date || "--",
      status: (updateLog.stale_files || []).length ? "stale" : updateLog.status,
      ok: updateLog.status === "ok" && !(updateLog.stale_files || []).length,
    },
  ];

  const summaryRoot = $("#dataStatusSummary");
  if (summaryRoot) {
    summaryRoot.innerHTML = summaryItems.map((item) => `
      <article class="status-summary-card">
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.value)}</strong>
        ${renderBadge(item.status, item.ok)}
      </article>
    `).join("");
  }

  const updatedAt = $("#dataStatusUpdatedAt");
  if (updatedAt) {
    updatedAt.textContent = `狀態整理：${formatDateTime(updateLog.updated_at || radarStatus.updated_at || factorStatus.updated_at)}`;
  }
}

function renderAlerts(results) {
  const updateLog = results.updateLog?.data || {};
  const factorStatus = results.factorStatus?.data || {};
  const alerts = [];

  for (const message of toArray(updateLog.warning)) {
    alerts.push({ type: "warn", message });
  }
  for (const reason of toArray(updateLog.failed_reasons)) {
    alerts.push({ type: "bad", message: reason });
  }
  if (factorStatus.ok === false) {
    for (const reason of toArray(factorStatus.failed_reasons)) {
      alerts.push({ type: "bad", message: `多因子分數：${reason}` });
    }
  }
  if (factorStatus.previous_data_preserved) {
    alerts.push({ type: "warn", message: "本次更新失敗，已保留前次可用資料。" });
  }
  for (const file of toArray(updateLog.stale_files)) {
    alerts.push({ type: "bad", message: `資料落後：${file}` });
  }

  if (!alerts.length) {
    alerts.push({ type: "ok", message: "目前狀態正常，主要資料來源同步完成。" });
  }

  const root = $("#dataStatusAlerts");
  if (root) {
    root.innerHTML = alerts.map((alert) => `
      <div class="status-alert status-alert-${alert.type}">${escapeHtml(alert.message)}</div>
    `).join("");
  }
}

function rowFromFetched(result) {
  const payload = result.data || {};
  return {
    file: result.path.replace(/^\.\//, ""),
    updated_at: payload.updated_at || payload.generated_at || payload.unified_update_at || "",
    content_latest_at: payload.latest_trade_date || payload.trade_date || payload.content_latest_at || "",
    items_count: getCount(payload),
    status: result.ok ? (payload.status || (payload.ok === false ? "failed" : "ok")) : "failed",
    ok: result.ok && payload.ok !== false,
    failed_reasons: result.ok ? toArray(payload.failed_reasons || payload.errors || payload.warning) : [result.error],
    previous_data_preserved: Boolean(payload.previous_data_preserved),
  };
}

function renderFileRows(results) {
  const updateRows = Array.isArray(results.updateLog?.data?.each_file_status)
    ? results.updateLog.data.each_file_status
    : STATUS_FILES.map((config) => rowFromFetched(results[config.key]));

  const root = $("#dataStatusRows");
  if (!root) return;
  root.innerHTML = updateRows.map((item) => {
    const reasons = toArray(item.failed_reasons).join("；");
    const note = reasons || (item.previous_data_preserved ? "本次更新失敗，已保留前次可用資料。" : "--");
    return `
      <tr class="${statusClass(item.status, item.ok) === "bad" ? "is-bad" : ""}">
        <td><code>${escapeHtml(item.file)}</code></td>
        <td>${formatDateTime(item.updated_at)}</td>
        <td>${escapeHtml(item.content_latest_at || "--")}</td>
        <td>${formatNumber(item.items_count)}</td>
        <td>${renderBadge(item.status, item.ok)}</td>
        <td>${escapeHtml(note)}</td>
      </tr>
    `;
  }).join("");
}

function renderSourceRows(results) {
  const sourceStatus = results.updateLog?.data?.source_status || [];
  const root = $("#sourceStatusRows");
  if (!root) return;
  root.innerHTML = sourceStatus.length
    ? sourceStatus.map((step) => `
      <tr>
        <td>${escapeHtml(step.name)}</td>
        <td><code>${escapeHtml(step.script)}</code></td>
        <td>${formatDateTime(step.started_at)}</td>
        <td>${formatDateTime(step.finished_at)}</td>
        <td>${renderBadge(step.ok ? "ok" : "failed", step.ok)}</td>
        <td>${escapeHtml(step.error || "--")}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="6"><div class="empty-state">尚未有統一更新步驟紀錄，請先執行 scripts/update_all_data.py。</div></td></tr>`;
}

async function initDataStatus() {
  const fetched = await Promise.all(STATUS_FILES.map(fetchJson));
  const results = Object.fromEntries(fetched.map((item) => [item.key, item]));

  renderSummary(results);
  renderAlerts(results);
  renderFileRows(results);
  renderSourceRows(results);
}

initDataStatus().catch((error) => {
  console.error(error);
  const root = $("#dataStatusRows");
  if (root) {
    root.innerHTML = `<tr><td colspan="6"><div class="empty-state">資料狀態讀取失敗：${escapeHtml(error.message || error)}</div></td></tr>`;
  }
});
