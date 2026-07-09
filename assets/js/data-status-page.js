const STATUS_FILES = [
  { key: "siteMeta", label: "全站中繼資料", path: "./data/site_meta.json", primary: true },
  { key: "dataStatus", label: "統一資料狀態", path: "./data/data_status.json" },
  { key: "updateStatus", label: "雷達收盤狀態", path: "./data/update_status.json" },
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
  const text = String(value).replace("T", " ").replace(/\+08:00$/, "");
  return text.slice(0, 19);
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
  return payload.items_count ?? payload.rows ?? payload.count ?? getItems(payload).length;
}

function normalizeDate(value) {
  if (!value) return "";
  const text = String(value);
  return text.includes("T") ? text.split("T", 1)[0] : text.slice(0, 10);
}

function latestDateOf(payload) {
  if (!payload) return "";
  if (Array.isArray(payload)) {
    const first = payload.find((item) => item && typeof item === "object");
    return first ? latestDateOf(first) : "";
  }
  if (typeof payload !== "object") return "";
  return payload.latest_trade_date
    || payload.trade_date
    || payload.content_latest_at
    || payload.market_date
    || payload.dataDate
    || payload.data_date
    || payload.date
    || payload.updated_at
    || payload.updatedAt
    || "";
}

function statusText(status, ok) {
  if (ok === true) return "OK";
  if (ok === false) return "FAILED";
  const normalized = String(status || "").toLowerCase();
  if (["ok", "success"].includes(normalized)) return "OK";
  if (["failed", "error", "partial_failed", "missing"].includes(normalized)) return "FAILED";
  if (["stale", "warning", "partial"].includes(normalized)) return "STALE";
  return normalized ? normalized.toUpperCase() : "UNKNOWN";
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

function versionedPath(path, version) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}v=${encodeURIComponent(version || Date.now())}`;
}

async function fetchJson(config, version) {
  const url = config.primary ? versionedPath(config.path, Date.now()) : versionedPath(config.path, version);
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return { ...config, ok: true, data: await response.json(), error: "" };
  } catch (error) {
    return { ...config, ok: false, data: null, error: error instanceof Error ? error.message : String(error) };
  }
}

function getStatusPayload(results) {
  return results.dataStatus?.data || results.updateStatus?.data || {};
}

function renderSummary(results) {
  const siteMeta = results.siteMeta?.data || {};
  const dataStatus = getStatusPayload(results);
  const updateStatus = results.updateStatus?.data || {};
  const factorStatus = results.factorStatus?.data || {};
  const factorMeta = results.factorMeta?.data || {};
  const siteDate = siteMeta.latest_trade_date || dataStatus.latest_trade_date || "";
  const radarDate = updateStatus.trade_date || updateStatus.latest_trade_date || "";
  const factorDate = factorStatus.latest_trade_date || factorMeta.latest_trade_date || "";

  const summaryItems = [
    {
      label: "全市場資料最後更新時間",
      value: formatDateTime(siteMeta.generated_at || dataStatus.generated_at || dataStatus.updated_at),
      status: dataStatus.status || siteMeta.status || "ok",
      ok: dataStatus.ok !== false && siteMeta.ok !== false,
    },
    {
      label: "雷達收盤資料 trade_date",
      value: radarDate || "--",
      status: normalizeDate(radarDate) === normalizeDate(siteDate) ? "ok" : "stale",
      ok: normalizeDate(radarDate) === normalizeDate(siteDate),
    },
    {
      label: "多因子分數 latest_trade_date",
      value: factorDate || "--",
      status: factorStatus.ok === false ? "failed" : (normalizeDate(factorDate) === normalizeDate(siteDate) ? "ok" : "stale"),
      ok: factorStatus.ok !== false && normalizeDate(factorDate) === normalizeDate(siteDate),
    },
    {
      label: "整體最新交易日",
      value: siteDate || "--",
      status: toArray(dataStatus.stale_files).length ? "stale" : (siteMeta.status || "ok"),
      ok: !toArray(dataStatus.stale_files).length && siteMeta.status !== "failed",
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
    updatedAt.textContent = `全站更新：${formatDateTime(siteMeta.generated_at || dataStatus.generated_at || dataStatus.updated_at)}｜交易日：${siteDate || "--"}`;
  }
}

function collectMismatches(results) {
  const siteMeta = results.siteMeta?.data || {};
  const dataStatus = getStatusPayload(results);
  const siteDate = normalizeDate(siteMeta.latest_trade_date || dataStatus.latest_trade_date);
  if (!siteDate) return [];

  const mismatches = [];
  const rows = Array.isArray(dataStatus.each_file_status) ? dataStatus.each_file_status : [];
  for (const row of rows) {
    const rowDate = normalizeDate(row.latest_trade_date || row.content_latest_at || row.trade_date);
    if (rowDate && rowDate !== siteDate) {
      mismatches.push(`${row.file || row.label || "資料檔"}：${rowDate} 不同於全站 ${siteDate}`);
    }
  }

  const factorDate = normalizeDate(results.factorStatus?.data?.latest_trade_date || results.factorMeta?.data?.latest_trade_date);
  if (factorDate && factorDate !== siteDate) {
    mismatches.push(`多因子資料：${factorDate} 不同於全站 ${siteDate}`);
  }

  const radarDate = normalizeDate(results.updateStatus?.data?.trade_date || results.updateStatus?.data?.latest_trade_date);
  if (radarDate && radarDate !== siteDate) {
    mismatches.push(`雷達資料：${radarDate} 不同於全站 ${siteDate}`);
  }

  return mismatches;
}

function renderAlerts(results) {
  const dataStatus = getStatusPayload(results);
  const factorStatus = results.factorStatus?.data || {};
  const alerts = [];

  for (const message of toArray(dataStatus.warning)) alerts.push({ type: "warn", message });
  for (const reason of toArray(dataStatus.failed_reasons)) alerts.push({ type: "bad", message: reason });
  for (const file of toArray(dataStatus.stale_files)) alerts.push({ type: "bad", message: `資料落後：${file}` });

  if (factorStatus.ok === false) {
    for (const reason of toArray(factorStatus.failed_reasons)) {
      alerts.push({ type: "bad", message: `多因子分數：${reason}` });
    }
  }
  if (factorStatus.previous_data_preserved) {
    alerts.push({ type: "warn", message: "本次更新失敗，已保留前次可用資料。" });
  }
  for (const mismatch of collectMismatches(results)) {
    alerts.push({ type: "bad", message: `不同步：${mismatch}` });
  }
  if (!alerts.length) {
    alerts.push({ type: "ok", message: "目前資料日期一致，主要來源流程同步完成。" });
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
    label: result.label,
    updated_at: payload.updated_at || payload.generated_at || payload.unified_update_at || "",
    content_latest_at: latestDateOf(payload),
    items_count: getCount(payload),
    status: result.ok ? (payload.status || (payload.ok === false ? "failed" : "ok")) : "failed",
    ok: result.ok && payload.ok !== false,
    failed_reasons: result.ok ? toArray(payload.failed_reasons || payload.errors || payload.warning) : [result.error],
    previous_data_preserved: Boolean(payload.previous_data_preserved),
  };
}

function renderFileRows(results) {
  const dataStatus = getStatusPayload(results);
  const updateRows = Array.isArray(dataStatus.each_file_status)
    ? dataStatus.each_file_status
    : STATUS_FILES.map((config) => rowFromFetched(results[config.key]));

  const root = $("#dataStatusRows");
  if (!root) return;
  root.innerHTML = updateRows.map((item) => {
    const reasons = toArray(item.failed_reasons).join("；");
    const note = reasons || (item.previous_data_preserved ? "本次更新失敗，已保留前次可用資料。" : "--");
    const status = item.status || (item.ok === false ? "failed" : "ok");
    return `
      <tr class="${statusClass(status, item.ok) === "bad" ? "is-bad" : ""}">
        <td><code>${escapeHtml(item.file || item.label || "--")}</code></td>
        <td>${formatDateTime(item.updated_at || item.generated_at)}</td>
        <td>${escapeHtml(item.content_latest_at || item.latest_trade_date || item.trade_date || "--")}</td>
        <td>${formatNumber(item.items_count ?? item.rows)}</td>
        <td>${renderBadge(status, item.ok)}</td>
        <td>${escapeHtml(note)}</td>
      </tr>
    `;
  }).join("");
}

function renderSourceRows(results) {
  const dataStatus = getStatusPayload(results);
  const sourceStatus = Array.isArray(dataStatus.source_status) ? dataStatus.source_status : [];
  const root = $("#sourceStatusRows");
  if (!root) return;
  if (!sourceStatus.length) {
    root.innerHTML = `<tr><td colspan="5" class="muted">目前沒有來源流程紀錄。</td></tr>`;
    return;
  }
  root.innerHTML = sourceStatus.map((source) => {
    const status = source.ok === false ? "failed" : (source.status || "ok");
    const reason = source.error || source.stderr_tail || source.message || "";
    return `
      <tr class="${statusClass(status, source.ok) === "bad" ? "is-bad" : ""}">
        <td>${escapeHtml(source.name || source.source || source.script || "--")}</td>
        <td>${escapeHtml(source.script || source.source || "--")}</td>
        <td>${formatDateTime(source.finished_at || source.updated_at || source.generated_at)}</td>
        <td>${renderBadge(status, source.ok !== false)}</td>
        <td>${escapeHtml(reason || "--")}</td>
      </tr>
    `;
  }).join("");
}

function renderFetchFailures(results) {
  const failed = Object.values(results).filter((result) => !result.ok);
  if (!failed.length) return;
  const root = $("#dataStatusAlerts");
  if (!root) return;
  root.insertAdjacentHTML("beforeend", failed.map((result) => `
    <div class="status-alert status-alert-bad">讀取失敗：${escapeHtml(result.label)} (${escapeHtml(result.error)})</div>
  `).join(""));
}

export async function initDataStatusPage() {
  const siteMetaResult = await fetchJson(STATUS_FILES[0], Date.now());
  const version = siteMetaResult.data?.data_version || siteMetaResult.data?.run_id || Date.now();
  const fetched = await Promise.all(STATUS_FILES.slice(1).map((config) => fetchJson(config, version)));
  const results = {
    siteMeta: siteMetaResult,
    ...Object.fromEntries(fetched.map((result) => [result.key, result])),
  };

  renderSummary(results);
  renderAlerts(results);
  renderFileRows(results);
  renderSourceRows(results);
  renderFetchFailures(results);
}
