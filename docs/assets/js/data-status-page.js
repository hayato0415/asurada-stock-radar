import { loadProcessedData } from "./api.js?v=20260723-validation";
import { formatDateTime } from "./formatters.js";
import { $, escapeHtml } from "./utils.js";

const STATUS_FILE = "ai-validation-status.json";
const STALE_AFTER_HOURS = 30;

function isMissing(value) {
  return value === null || value === undefined || value === "";
}

function displayValue(value) {
  if (isMissing(value)) return "--";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.join("、") || "--";
  if (typeof value === "number") return value.toLocaleString("zh-TW");
  return String(value);
}

function displayDateTime(value) {
  return isMissing(value) ? "--" : formatDateTime(value);
}

function freshness(status) {
  const raw = status?.latestValidationUpdateTime || status?.generatedAt || status?.generated_at;
  const timestamp = Date.parse(raw);
  if (!Number.isFinite(timestamp)) {
    return {
      stale: true,
      label: "無法判定",
      note: "驗證狀態沒有可解析的更新時間。",
    };
  }
  const ageHours = Math.max(0, (Date.now() - timestamp) / 3_600_000);
  const roundedHours = Math.round(ageHours * 10) / 10;
  return {
    stale: ageHours > STALE_AFTER_HOURS,
    label: ageHours > STALE_AFTER_HOURS ? "可能停更" : "更新正常",
    note: `距今約 ${roundedHours.toLocaleString("zh-TW")} 小時；超過 ${STALE_AFTER_HOURS} 小時視為可能停更。`,
  };
}

function statusBadge(type, text) {
  return `<span class="status-badge status-${type}">${escapeHtml(text)}</span>`;
}

function metricAssessment(type, text, note) {
  return { type, text, note };
}

function assessmentFor(field, value, status) {
  if (field === "updateFreshness") {
    const health = freshness(status);
    return health.stale
      ? metricAssessment("bad", health.label, health.note)
      : metricAssessment("ok", health.label, health.note);
  }
  if (field === "pipelineIntegrated") {
    return value === true
      ? metricAssessment("ok", "已接入", "績效驗證已由全站更新流程執行。")
      : metricAssessment("bad", "未接入", "全站更新流程尚未確認績效驗證步驟。");
  }
  if (field === "missingPriceCount" || field === "missingBenchmarkCount") {
    if (isMissing(value)) return metricAssessment("muted", "未知", "狀態檔沒有提供缺失筆數。");
    return Number(value) === 0
      ? metricAssessment("ok", "完整", "目前沒有記錄缺失資料。")
      : metricAssessment("warn", "待補資料", "缺失資料保留空值，不會以 0 補入。");
  }
  if (field === "lastError") {
    return isMissing(value)
      ? metricAssessment("ok", "無錯誤", "最近一次更新沒有記錄錯誤。")
      : metricAssessment("bad", "有錯誤", "上一版正常資料應保持不被覆蓋。");
  }
  if (isMissing(value)) {
    return metricAssessment("warn", "未提供", "狀態檔尚未提供這個欄位。");
  }
  if (status?.ok === false) {
    return metricAssessment("warn", "保留資料", "整體更新未完成，目前可能顯示上一版資料。");
  }
  return metricAssessment("ok", "已記錄", "欄位已由正式驗證流程寫入。");
}

function renderSummary(status) {
  const root = $("#validationStatusSummary");
  if (!root) return;
  const metrics = [
    ["更新健康度", freshness(status).label, "health"],
    ["最新訊號日期", status.latestSignalDate, "text"],
    ["最新進場日期", status.latestEntryDate, "text"],
    ["最新驗證時間", status.latestValidationUpdateTime || status.generatedAt || status.generated_at, "datetime"],
    ["完成樣本數", status.completedSignals, "count"],
    ["追蹤中樣本數", status.trackingSignals, "count"],
    ["D+20 完成樣本", status.d20CompletedSignals, "count"],
    ["缺少行情筆數", status.missingPriceCount, "count"],
    ["缺少大盤筆數", status.missingBenchmarkCount, "count"],
    ["驗證版本", status.validationVersion, "text"],
    ["全站流程接入", status.pipelineIntegrated, "boolean"],
  ];
  root.innerHTML = metrics.map(([label, value, kind]) => {
    const display = kind === "datetime" ? displayDateTime(value) : displayValue(value);
    const attention = kind === "health"
      ? freshness(status).stale
      : (label.includes("缺少") && Number(value) > 0) || (kind === "boolean" && value !== true);
    return `
      <article class="status-summary-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(display)}</strong>
        ${statusBadge(attention ? "warn" : isMissing(value) ? "muted" : "ok", attention ? "需注意" : isMissing(value) ? "未提供" : "已記錄")}
      </article>
    `;
  }).join("");
}

function renderAlerts(status) {
  const root = $("#validationStatusAlerts");
  if (!root) return;
  const alerts = [];
  const updateFreshness = freshness(status);
  if (updateFreshness.stale) {
    alerts.push({ type: "bad", text: `績效驗證可能停更：${updateFreshness.note}` });
  }
  if (status.ok === false) {
    alerts.push({ type: "bad", text: "最近一次績效驗證更新未成功完成。" });
  }
  if (status.previousDataPreserved) {
    alerts.push({ type: "warn", text: "更新失敗時已保留上一版正常驗證資料。" });
  }
  if (status.pipelineIntegrated === false) {
    alerts.push({ type: "bad", text: "績效驗證尚未成功接入全站更新流程。" });
  }
  if (Number(status.missingPriceCount || 0) > 0) {
    alerts.push({ type: "warn", text: `缺少個股行情 ${Number(status.missingPriceCount).toLocaleString("zh-TW")} 筆；缺失值未被補成 0。` });
  }
  if (Number(status.missingBenchmarkCount || 0) > 0) {
    alerts.push({ type: "warn", text: `缺少大盤資料 ${Number(status.missingBenchmarkCount).toLocaleString("zh-TW")} 筆；缺失值未被視為 0%。` });
  }
  for (const warning of Array.isArray(status.warnings) ? status.warnings : []) {
    alerts.push({ type: "warn", text: warning });
  }
  if (status.lastError) {
    alerts.push({ type: "bad", text: `最近一次錯誤：${status.lastError}` });
  }
  if (!alerts.length) {
    alerts.push({ type: "ok", text: "驗證狀態檔已載入，流程沒有記錄缺失或錯誤。" });
  }
  root.innerHTML = alerts.map((alert) => `
    <div class="status-alert status-alert-${alert.type}">${escapeHtml(alert.text)}</div>
  `).join("");
}

function renderRows(status) {
  const root = $("#validationStatusRows");
  if (!root) return;
  const metrics = [
    ["updateFreshness", "更新健康度", freshness(status).label],
    ["latestSignalDate", "最新訊號日期", status.latestSignalDate],
    ["latestEntryDate", "最新進場日期", status.latestEntryDate],
    ["generatedAt", "最新驗證更新時間", status.latestValidationUpdateTime || status.generatedAt || status.generated_at],
    ["completedSignals", "完成樣本數", status.completedSignals],
    ["trackingSignals", "追蹤中樣本數", status.trackingSignals],
    ["d20CompletedSignals", "D+20 完成樣本數", status.d20CompletedSignals],
    ["missingPriceCount", "缺少行情筆數", status.missingPriceCount],
    ["missingBenchmarkCount", "缺少大盤資料筆數", status.missingBenchmarkCount],
    ["validationVersion", "驗證版本", status.validationVersion],
    ["pipelineIntegrated", "全站更新流程接入", status.pipelineIntegrated],
    ["previousDataPreserved", "失敗時保留上一版", status.previousDataPreserved],
    ["lastError", "最近一次錯誤", status.lastError],
  ];
  root.innerHTML = metrics.map(([field, label, value]) => {
    const assessment = assessmentFor(field, value, status);
    const shown = field === "generatedAt" ? displayDateTime(value) : displayValue(value);
    return `
      <tr class="${assessment.type === "bad" ? "is-bad" : ""}">
        <td><strong>${escapeHtml(label)}</strong><br><code>${escapeHtml(field)}</code></td>
        <td>${escapeHtml(shown)}</td>
        <td>${statusBadge(assessment.type, assessment.text)}</td>
        <td>${escapeHtml(assessment.note)}</td>
      </tr>
    `;
  }).join("");
}

function renderFailure(message) {
  const updatedAt = $("#validationStatusUpdatedAt");
  const summary = $("#validationStatusSummary");
  const alerts = $("#validationStatusAlerts");
  const rows = $("#validationStatusRows");
  if (updatedAt) updatedAt.textContent = "資料載入失敗";
  if (summary) summary.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
  if (alerts) alerts.innerHTML = `<div class="status-alert status-alert-bad">${escapeHtml(message)}</div>`;
  if (rows) rows.innerHTML = `<tr class="is-bad"><td colspan="4">${escapeHtml(message)}</td></tr>`;
}

async function loadAndRender() {
  const button = $("#reloadValidationStatus");
  if (button) {
    button.disabled = true;
    button.textContent = "載入中";
  }
  const updatedAt = $("#validationStatusUpdatedAt");
  if (updatedAt) updatedAt.textContent = "資料載入中";
  try {
    const loaded = await loadProcessedData([STATUS_FILE]);
    const result = loaded[STATUS_FILE];
    if (result?.error || !result?.data) {
      throw result?.error || new Error("驗證狀態檔內容為空");
    }
    const status = result.data;
    renderSummary(status);
    renderAlerts(status);
    renderRows(status);
    if (updatedAt) updatedAt.textContent = `驗證更新：${displayDateTime(status.latestValidationUpdateTime || status.generatedAt || status.generated_at)}`;
  } catch (error) {
    console.error(error);
    renderFailure(`績效驗證狀態載入失敗：${error?.message || error}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "重新載入";
    }
  }
}

export function initDataStatusPage() {
  $("#reloadValidationStatus")?.addEventListener("click", loadAndRender);
  loadAndRender();
}

initDataStatusPage();
