import { loadProcessedData } from "./api.js?v=20260723-validation";
import { formatDateTime, formatNumber, formatPercent, formatSignedPercent, valueClass } from "./formatters.js";
import { $, escapeHtml, stockLink } from "./utils.js";

const VALIDATION_FILES = [
  "ai-validation-detail.json",
  "ai-validation-summary.json",
  "ai-validation-portfolio.json",
  "ai-factor-performance.json",
  "ai-validation-status.json",
];

const FILES = [
  "ai-top10-daily.json",
  "ai-persistence-weekly.json",
  "ai-persistence-monthly.json",
  ...VALIDATION_FILES,
];

const VALIDATION_PERIODS = ["d1", "d3", "d5", "d10", "d20"];
const VALIDATION_DETAIL_LIMIT = 50;
const validationState = {
  detail: null,
  portfolio: null,
};

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function emptyRow(colspan, message) {
  return `<tr><td colspan="${colspan}"><div class="empty-state">${escapeHtml(message)}</div></td></tr>`;
}

function rankChange(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return `<span class="rank-flat">--</span>`;
  if (number > 0) return `<span class="value-up">↑${number}</span>`;
  if (number < 0) return `<span class="value-down">↓${Math.abs(number)}</span>`;
  return `<span class="rank-flat">—</span>`;
}

function trendBadge(value) {
  const text = String(value || "資料不足");
  const className = text === "上升" ? "good" : text === "下降" ? "bad" : "warn";
  return `<span class="badge ${className}">${escapeHtml(text)}</span>`;
}

function statusBadges(labels = []) {
  if (!labels.length) return `<span class="badge">持續觀察</span>`;
  return labels
    .map((label) => {
      const className = ["新進榜", "重返榜", "排名上升", "月度常駐"].includes(label)
        ? "good"
        : ["排名下降", "分數轉弱", "單日爆發"].includes(label)
          ? "warn"
          : "";
      return `<span class="badge ${className}">${escapeHtml(label)}</span>`;
    })
    .join("");
}

function conceptsText(item) {
  const values = [item.industry, ...(Array.isArray(item.concepts) ? item.concepts : [])].filter(Boolean);
  return [...new Set(values)].join("／") || "未分類";
}

function isMissing(value) {
  return value === null || value === undefined || value === "";
}

function firstValue(source, keys, fallback = null) {
  if (!source || typeof source !== "object") return fallback;
  for (const key of keys) {
    if (!isMissing(source[key])) return source[key];
  }
  return fallback;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asBoolean(value) {
  if (value === true || value === false) return value;
  if (value === 1 || value === "1" || value === "true") return true;
  if (value === 0 || value === "0" || value === "false") return false;
  return null;
}

function formatValidationNumber(value, digits = 2) {
  return isMissing(value) ? "--" : formatNumber(value, digits);
}

function formatValidationPercent(value, digits = 2) {
  return isMissing(value) ? "--" : formatSignedPercent(value, digits);
}

function formatValidationDateTime(value) {
  return isMissing(value) ? "--" : formatDateTime(value);
}

function formatPlainValue(value) {
  if (isMissing(value)) return "--";
  if (Array.isArray(value)) return value.filter((item) => !isMissing(item)).join("、") || "--";
  if (typeof value === "object") {
    const pairs = Object.entries(value)
      .filter(([, item]) => !isMissing(item))
      .map(([key, item]) => `${key}：${item}`);
    return pairs.join("；") || "--";
  }
  return String(value);
}

function validationStatusLabel(status) {
  const labels = {
    waiting_entry: "等待進場",
    entry_ready: "已取得進場價",
    tracking: "追蹤中",
    partially_completed: "部分完成",
    completed: "D+20 已完成",
    entry_price_unavailable: "無有效進場價",
    price_data_incomplete: "行情不完整",
    benchmark_unavailable: "大盤資料不足",
    suspended: "停牌",
    delisted: "下市櫃",
    error: "錯誤",
  };
  return labels[String(status || "")] || String(status || "狀態未標示");
}

function validationStatusGroup(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "completed") return "completed";
  if (["entry_ready", "tracking", "partially_completed"].includes(normalized)) return "tracking";
  if (normalized === "waiting_entry") return "pending";
  return "invalid";
}

function validationStatusBadge(status) {
  const group = validationStatusGroup(status);
  const className = group === "completed" ? "good" : group === "invalid" ? "bad" : "warn";
  return `<span class="badge ${className}">${escapeHtml(validationStatusLabel(status))}</span>`;
}

function summaryPayload(payload) {
  return payload?.all || payload?.overall || payload?.fullPeriod || {};
}

function periodPayload(payload, period) {
  const periods = payload?.periods;
  if (Array.isArray(periods)) {
    return periods.find((item) => (
      String(item?.period || item?.horizon || "")
        .toLowerCase()
        .replace("+", "") === period
    )) || {};
  }
  if (periods && typeof periods === "object") {
    return periods[period] || periods[period.toUpperCase()] || {};
  }
  const all = summaryPayload(payload);
  const suffix = period.slice(1);
  const titleSuffix = `D${suffix}`;
  return {
    completedSamples: firstValue(all, [`completed${titleSuffix}Signals`, `completed${titleSuffix}`, `sampleCount${titleSuffix}`]),
    averageReturn: firstValue(all, [`average${titleSuffix}Return`]),
    medianReturn: firstValue(all, [`median${titleSuffix}Return`]),
    winRate: firstValue(all, [`winRate${titleSuffix}`]),
    averageExcessReturn: firstValue(all, [`averageExcessReturn${titleSuffix}`]),
    averageMfe: firstValue(all, [`averageMfe${suffix}`, `averageMfe${titleSuffix}`]),
    averageMae: firstValue(all, [`averageMae${suffix}`, `averageMae${titleSuffix}`]),
  };
}

function renderValidationSummary(payload) {
  const root = $("#validationSummary");
  if (!root) return;
  const all = summaryPayload(payload);
  const cards = [
    ["已完成樣本數", firstValue(all, ["completedSignals", "completedSignalCount"]), "count"],
    ["正在追蹤樣本數", firstValue(all, ["trackingSignals", "trackingSignalCount"]), "count"],
    ["D+5 平均報酬", firstValue(all, ["averageD5Return"]), "percent"],
    ["D+5 中位數報酬", firstValue(all, ["medianD5Return"]), "percent"],
    ["D+5 上漲勝率", firstValue(all, ["winRateD5"]), "percent"],
    ["D+5 跑贏大盤", firstValue(all, ["benchmarkWinRateD5"]), "percent"],
    ["D+20 平均報酬", firstValue(all, ["averageD20Return"]), "percent"],
    ["D+20 中位數報酬", firstValue(all, ["medianD20Return"]), "percent"],
    ["D+20 上漲勝率", firstValue(all, ["winRateD20"]), "percent"],
    ["最大回撤", firstValue(all, ["worstDrawdown", "maxDrawdown"]), "percent"],
  ];
  root.innerHTML = cards.map(([label, value, kind]) => {
    const formatted = kind === "percent"
      ? formatValidationPercent(value)
      : isMissing(value) ? "--" : Number(value).toLocaleString("zh-TW");
    const className = kind === "percent" && !isMissing(value) ? valueClass(value) : "value-flat";
    return `
      <article class="status-summary-card validation-summary-card">
        <span>${escapeHtml(label)}</span>
        <strong class="${className}">${escapeHtml(formatted)}</strong>
      </article>
    `;
  }).join("");
}

function renderHoldingComparison(payload) {
  const body = $("#validationPeriodBody");
  const cards = $("#validationPeriodCards");
  if (!body || !cards) return;
  const rows = VALIDATION_PERIODS.map((period) => {
    const item = periodPayload(payload, period);
    return {
      period: period.toUpperCase().replace("D", "D+"),
      completed: firstValue(item, ["completedSamples", "completedSignals", "sampleCount", "count"]),
      averageReturn: firstValue(item, ["averageReturn", "average"]),
      medianReturn: firstValue(item, ["medianReturn", "median"]),
      winRate: firstValue(item, ["winRate", "absoluteWinRate"]),
      averageExcessReturn: firstValue(item, ["averageExcessReturn", "excessReturn"]),
      averageMfe: firstValue(item, ["averageMfe", "mfe"]),
      averageMae: firstValue(item, ["averageMae", "mae"]),
    };
  });
  body.innerHTML = rows.map((item) => `
    <tr>
      <td><strong>${escapeHtml(item.period)}</strong></td>
      <td>${isMissing(item.completed) ? "--" : Number(item.completed).toLocaleString("zh-TW")}</td>
      <td class="${valueClass(item.averageReturn)}">${formatValidationPercent(item.averageReturn)}</td>
      <td class="${valueClass(item.medianReturn)}">${formatValidationPercent(item.medianReturn)}</td>
      <td>${formatValidationPercent(item.winRate)}</td>
      <td class="${valueClass(item.averageExcessReturn)}">${formatValidationPercent(item.averageExcessReturn)}</td>
      <td class="${valueClass(item.averageMfe)}">${formatValidationPercent(item.averageMfe)}</td>
      <td class="${valueClass(item.averageMae)}">${formatValidationPercent(item.averageMae)}</td>
    </tr>
  `).join("");
  cards.innerHTML = rows.map((item) => `
    <article class="validation-period-card">
      <div class="validation-card-title">
        <strong>${escapeHtml(item.period)}</strong>
        <span>${isMissing(item.completed) ? "--" : Number(item.completed).toLocaleString("zh-TW")} 筆完成</span>
      </div>
      <dl class="validation-metric-list">
        <div><dt>平均</dt><dd class="${valueClass(item.averageReturn)}">${formatValidationPercent(item.averageReturn)}</dd></div>
        <div><dt>中位數</dt><dd class="${valueClass(item.medianReturn)}">${formatValidationPercent(item.medianReturn)}</dd></div>
        <div><dt>勝率</dt><dd>${formatValidationPercent(item.winRate)}</dd></div>
        <div><dt>超額</dt><dd class="${valueClass(item.averageExcessReturn)}">${formatValidationPercent(item.averageExcessReturn)}</dd></div>
        <div><dt>MFE</dt><dd class="${valueClass(item.averageMfe)}">${formatValidationPercent(item.averageMfe)}</dd></div>
        <div><dt>MAE</dt><dd class="${valueClass(item.averageMae)}">${formatValidationPercent(item.averageMae)}</dd></div>
      </dl>
    </article>
  `).join("");
}

function detailModeItems() {
  const payload = validationState.detail || {};
  const mode = $("#validationModeFilter")?.value || "firstEntry";
  return mode === "dailyObservation"
    ? asArray(payload.dailyObservations)
    : asArray(payload.items);
}

function uniqueDetailValues(items, key) {
  return [...new Set(items.map((item) => item?.[key]).filter((value) => !isMissing(value)))]
    .map(String)
    .sort((left, right) => left.localeCompare(right, "zh-Hant"));
}

function populateSelect(selector, values) {
  const select = $(selector);
  if (!select) return;
  const previous = select.value;
  const first = select.options[0]?.outerHTML || `<option value="">全部</option>`;
  select.innerHTML = first + values
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("");
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

function populateValidationFilters(items) {
  populateSelect("#validationTradeTypeFilter", uniqueDetailValues(items, "tradeType"));
  populateSelect("#validationRiskFilter", uniqueDetailValues(items, "riskLabel"));
  populateSelect("#validationVersionFilter", uniqueDetailValues(items, "scoreVersion"));
}

function eventAbsoluteSuccess(item) {
  return asBoolean(firstValue(item, [
    "absoluteSuccessD20",
    "d20AbsoluteSuccess",
    "absoluteSuccessD5",
    "d5AbsoluteSuccess",
  ]));
}

function eventBenchmarkSuccess(item) {
  return asBoolean(firstValue(item, [
    "outperformedBenchmarkD20",
    "outperformedBenchmarkD5",
  ]));
}

function filteredValidationItems(items) {
  const dateValue = $("#validationDateFilter")?.value || "";
  const stockValue = ($("#validationStockFilter")?.value || "").trim().toLowerCase();
  const outcomeValue = $("#validationOutcomeFilter")?.value || "";
  const statusValue = $("#validationStatusFilter")?.value || "";
  const tradeTypeValue = $("#validationTradeTypeFilter")?.value || "";
  const riskValue = $("#validationRiskFilter")?.value || "";
  const versionValue = $("#validationVersionFilter")?.value || "";
  const consecutiveValue = $("#validationConsecutiveFilter")?.value || "";

  return items.filter((item) => {
    if (dateValue && String(item.signalDate || item.dataDate || "") !== dateValue) return false;
    if (stockValue) {
      const haystack = `${item.code || item.symbol || ""} ${item.name || ""}`.toLowerCase();
      if (!haystack.includes(stockValue)) return false;
    }
    if (outcomeValue) {
      const absoluteSuccess = eventAbsoluteSuccess(item);
      const benchmarkSuccess = eventBenchmarkSuccess(item);
      if (outcomeValue === "success" && absoluteSuccess !== true) return false;
      if (outcomeValue === "failure" && absoluteSuccess !== false) return false;
      if (outcomeValue === "outperformed" && benchmarkSuccess !== true) return false;
      if (outcomeValue === "underperformed" && benchmarkSuccess !== false) return false;
    }
    if (statusValue && validationStatusGroup(item.validationStatus) !== statusValue) return false;
    if (tradeTypeValue && String(item.tradeType || "") !== tradeTypeValue) return false;
    if (riskValue && String(item.riskLabel || "") !== riskValue) return false;
    if (versionValue && String(item.scoreVersion || "") !== versionValue) return false;
    const consecutiveDays = Number(item.consecutiveDays || 0);
    if (consecutiveValue === "1" && consecutiveDays !== 1) return false;
    if (consecutiveValue === "2" && consecutiveDays !== 2) return false;
    if (consecutiveValue === "3" && consecutiveDays < 3) return false;
    return true;
  });
}

function entryTypeText(item) {
  const explicit = firstValue(item, ["entryType", "entryStatus", "signalType"]);
  if (!isMissing(explicit)) return String(explicit);
  const labels = asArray(item.statusLabels);
  return labels.join("、") || "--";
}

function renderValidationDetails() {
  const body = $("#validationDetailBody");
  const cards = $("#validationDetailCards");
  if (!body || !cards) return;
  const allItems = detailModeItems();
  populateValidationFilters(allItems);
  const filtered = filteredValidationItems(allItems);
  const visible = filtered.slice(0, VALIDATION_DETAIL_LIMIT);
  const count = $("#validationDetailCount");
  if (count) {
    count.textContent = filtered.length > visible.length
      ? `${filtered.length.toLocaleString("zh-TW")} 筆（顯示前 ${visible.length} 筆）`
      : `${filtered.length.toLocaleString("zh-TW")} 筆`;
  }
  if (!visible.length) {
    const message = allItems.length ? "沒有符合目前篩選條件的訊號。" : "目前沒有可顯示的正式訊號事件。";
    body.innerHTML = emptyRow(16, message);
    cards.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
    return;
  }

  body.innerHTML = visible.map((item) => `
    <tr>
      <td>${escapeHtml(item.signalDate || item.dataDate || "--")}</td>
      <td>${stockLink(item.code || item.symbol, item.name)}</td>
      <td>${formatValidationNumber(item.signalRank, 0)}</td>
      <td>${formatValidationNumber(item.signalScore, 1)}</td>
      <td>${escapeHtml(entryTypeText(item))}</td>
      <td>${formatValidationNumber(item.consecutiveDays, 0)}</td>
      <td>${escapeHtml(item.entryTradeDate || "--")}</td>
      <td>${formatValidationNumber(item.entryOpen, 2)}</td>
      <td class="${valueClass(item.d1Return)}">${formatValidationPercent(item.d1Return)}</td>
      <td class="${valueClass(item.d5Return)}">${formatValidationPercent(item.d5Return)}</td>
      <td class="${valueClass(item.d20Return)}">${formatValidationPercent(item.d20Return)}</td>
      <td class="${valueClass(item.mfe20)}">${formatValidationPercent(item.mfe20)}</td>
      <td class="${valueClass(item.mae20)}">${formatValidationPercent(item.mae20)}</td>
      <td class="${valueClass(item.excessReturnD20)}">${formatValidationPercent(item.excessReturnD20)}</td>
      <td>${validationStatusBadge(item.validationStatus)}</td>
      <td>${escapeHtml(item.scoreVersion || "--")}</td>
    </tr>
  `).join("");

  cards.innerHTML = visible.map((item) => `
    <article class="validation-detail-card">
      <div class="validation-card-title">
        <div>
          <span class="tracking-rank">#${formatValidationNumber(item.signalRank, 0)}</span>
          ${stockLink(item.code || item.symbol, item.name)}
        </div>
        ${validationStatusBadge(item.validationStatus)}
      </div>
      <p>${escapeHtml(item.signalDate || item.dataDate || "--")}・${escapeHtml(entryTypeText(item))}・連續 ${formatValidationNumber(item.consecutiveDays, 0)} 日</p>
      <dl class="validation-metric-list">
        <div><dt>當時總分</dt><dd>${formatValidationNumber(item.signalScore, 1)}</dd></div>
        <div><dt>進場日</dt><dd>${escapeHtml(item.entryTradeDate || "--")}</dd></div>
        <div><dt>進場價</dt><dd>${formatValidationNumber(item.entryOpen, 2)}</dd></div>
        <div><dt>D+1</dt><dd class="${valueClass(item.d1Return)}">${formatValidationPercent(item.d1Return)}</dd></div>
        <div><dt>D+5</dt><dd class="${valueClass(item.d5Return)}">${formatValidationPercent(item.d5Return)}</dd></div>
        <div><dt>D+20</dt><dd class="${valueClass(item.d20Return)}">${formatValidationPercent(item.d20Return)}</dd></div>
        <div><dt>MFE20</dt><dd class="${valueClass(item.mfe20)}">${formatValidationPercent(item.mfe20)}</dd></div>
        <div><dt>MAE20</dt><dd class="${valueClass(item.mae20)}">${formatValidationPercent(item.mae20)}</dd></div>
        <div><dt>D+20 超額</dt><dd class="${valueClass(item.excessReturnD20)}">${formatValidationPercent(item.excessReturnD20)}</dd></div>
        <div><dt>版本</dt><dd>${escapeHtml(item.scoreVersion || "--")}</dd></div>
      </dl>
    </article>
  `).join("");
}

function flattenFactorGroups(groups, prefix = "") {
  if (Array.isArray(groups)) {
    return groups.flatMap((item, index) => {
      if (!item || typeof item !== "object") return [];
      const label = firstValue(item, ["label", "groupLabel", "name", "group"], `${prefix || "分組"} ${index + 1}`);
      return [{ ...item, _groupLabel: String(label) }];
    });
  }
  if (!groups || typeof groups !== "object") return [];
  const rows = [];
  for (const [key, value] of Object.entries(groups)) {
    if (!value || typeof value !== "object") continue;
    const label = prefix ? `${prefix}／${key}` : key;
    const looksLikeMetric = [
      "sampleCount",
      "count",
      "averageD5Return",
      "medianD5Return",
      "winRateD5",
      "averageD20Return",
    ].some((metric) => Object.hasOwn(value, metric));
    if (looksLikeMetric) {
      rows.push({ ...value, _groupLabel: String(firstValue(value, ["label", "groupLabel", "name"], label)) });
    } else {
      rows.push(...flattenFactorGroups(value, label));
    }
  }
  return rows;
}

function insightLabel(key) {
  const labels = {
    mostEffectiveFactor: "近期最有效因子",
    weakestFactor: "近期最弱因子",
    strongestFactor: "近期最有效因子",
    sampleAssessment: "樣本判讀",
    sampleLabel: "樣本判讀",
    window: "觀察期間",
    signalDateCount: "涵蓋榜單日",
  };
  return labels[key] || key;
}

function formatFactorInsight(value) {
  if (!value || typeof value !== "object") return formatPlainValue(value);
  const label = firstValue(value, ["factorLabel", "label", "name"], "--");
  const winRateD5 = firstValue(value, ["winRateD5"]);
  const winRateD20 = firstValue(value, ["winRateD20"]);
  const samples = firstValue(value, ["completedD5", "sampleCount"], 0);
  return `${label}｜D+5 勝率 ${formatValidationPercent(winRateD5)}｜D+20 勝率 ${formatValidationPercent(winRateD20)}｜完成樣本 ${formatValidationNumber(samples, 0)}`;
}

function renderFactorPerformance(payload) {
  const firstEntry = payload?.firstEntry || {};
  const groups = flattenFactorGroups(firstEntry.groups);
  const body = $("#validationFactorBody");
  const cards = $("#validationFactorCards");
  const warningRoot = $("#validationFactorWarning");
  if (!body || !cards || !warningRoot) return;

  const insights = firstEntry.insights || {};
  const insightRows = Array.isArray(insights)
    ? insights.map((value, index) => [`觀察 ${index + 1}`, value])
    : insights && typeof insights === "object"
      ? Object.entries(insights).filter(([key]) => key !== "warning")
      : [];
  cards.innerHTML = insightRows.length
    ? insightRows.map(([key, value]) => `
        <article class="validation-insight-card">
          <span>${escapeHtml(insightLabel(key))}</span>
          <strong>${escapeHtml(formatFactorInsight(value))}</strong>
        </article>
      `).join("")
    : `<div class="empty-state">目前尚無足夠樣本可產生因子結論。</div>`;

  const warnings = [
    insights?.warning,
    ...asArray(firstEntry.warnings),
    ...asArray(payload?.warnings),
  ].filter(Boolean);
  warningRoot.innerHTML = warnings.length
    ? warnings.map((warning) => `<div class="tracking-alert tracking-alert-warn">${escapeHtml(warning)}</div>`).join("")
    : `<div class="tracking-alert tracking-alert-ok">因子結論依後端樣本門檻呈現，不在瀏覽器推定。</div>`;

  body.innerHTML = groups.length
    ? groups.map((item) => `
        <tr>
          <td>${escapeHtml(item._groupLabel || "--")}<br><small>${escapeHtml(item.sampleLabel || "")}</small></td>
          <td>${formatValidationNumber(firstValue(item, ["sampleCount", "count"]), 0)}</td>
          <td class="${valueClass(item.averageD5Return)}">${formatValidationPercent(item.averageD5Return)}</td>
          <td class="${valueClass(item.medianD5Return)}">${formatValidationPercent(item.medianD5Return)}</td>
          <td>${formatValidationPercent(item.winRateD5)}</td>
          <td class="${valueClass(item.averageD20Return)}">${formatValidationPercent(item.averageD20Return)}</td>
          <td class="${valueClass(item.medianD20Return)}">${formatValidationPercent(item.medianD20Return)}</td>
          <td>${formatValidationPercent(item.winRateD20)}</td>
          <td class="${valueClass(firstValue(item, ["averageMae20", "averageMae"]))}">${formatValidationPercent(firstValue(item, ["averageMae20", "averageMae"]))}</td>
          <td>${formatValidationPercent(firstValue(item, ["benchmarkOutperformanceRateD20", "benchmarkOutperformanceRateD5", "benchmarkWinRateD20", "benchmarkWinRate", "outperformanceRate"]))}</td>
        </tr>
      `).join("")
    : emptyRow(10, "目前沒有可顯示的首次入榜因子分組績效。");
}

function portfolioRowValue(row, keys) {
  return firstValue(row, keys);
}

function portfolioChartSeries(rows, keys) {
  return rows
    .map((row, index) => {
      const value = portfolioRowValue(row, keys);
      const number = Number(value);
      return isMissing(value) || !Number.isFinite(number) ? null : { index, value: number };
    })
    .filter(Boolean);
}

function chartPolyline(series, rowCount, minValue, maxValue) {
  const width = 680;
  const height = 200;
  const range = maxValue - minValue || 1;
  return series.map((point) => {
    const x = 20 + (rowCount <= 1 ? 0 : point.index / (rowCount - 1)) * width;
    const y = 20 + (1 - (point.value - minValue) / range) * height;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
}

function renderPortfolioChart(rows) {
  const root = $("#portfolioCurve");
  if (!root) return;
  const ai = portfolioChartSeries(rows, ["cumulativeReturn", "grossCumulativeReturn", "grossReturn"]);
  const benchmark = portfolioChartSeries(rows, ["benchmarkCumulativeReturn", "benchmarkReturn"]);
  const excess = portfolioChartSeries(rows, ["excessCumulativeReturn", "excessReturn"]);
  const allPoints = [...ai, ...benchmark, ...excess];
  if (rows.length < 2 || allPoints.length < 2) {
    root.innerHTML = `<div class="empty-state">累積績效資料尚不足，暫不繪製曲線。</div>`;
    return;
  }
  const values = allPoints.map((point) => point.value);
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values, 0);
  const firstDate = firstValue(rows[0], ["date", "tradeDate"], "--");
  const lastDate = firstValue(rows.at(-1), ["date", "tradeDate"], "--");
  const line = (series, className) => series.length > 1
    ? `<polyline class="${className}" points="${chartPolyline(series, rows.length, minValue, maxValue)}"></polyline>`
    : "";
  root.innerHTML = `
    <div class="portfolio-chart-legend">
      <span><i class="portfolio-legend-ai"></i>AI 組合</span>
      <span><i class="portfolio-legend-benchmark"></i>大盤</span>
      <span><i class="portfolio-legend-excess"></i>超額</span>
    </div>
    <svg viewBox="0 0 720 260" role="img" aria-label="AI 組合、大盤與超額累積績效曲線">
      <line class="portfolio-zero-line" x1="20" x2="700" y1="${(20 + (1 - (0 - minValue) / (maxValue - minValue || 1)) * 200).toFixed(2)}" y2="${(20 + (1 - (0 - minValue) / (maxValue - minValue || 1)) * 200).toFixed(2)}"></line>
      ${line(ai, "portfolio-line portfolio-line-ai")}
      ${line(benchmark, "portfolio-line portfolio-line-benchmark")}
      ${line(excess, "portfolio-line portfolio-line-excess")}
      <text x="20" y="246">${escapeHtml(firstDate)}</text>
      <text x="700" y="246" text-anchor="end">${escapeHtml(lastDate)}</text>
      <text x="20" y="14">${escapeHtml(formatValidationPercent(maxValue))}</text>
      <text x="20" y="236">${escapeHtml(formatValidationPercent(minValue))}</text>
    </svg>
  `;
}

function renderPortfolio() {
  const payload = validationState.portfolio || {};
  const horizon = $("#portfolioRangeFilter")?.value || "holding5";
  const selected = payload[horizon] || {};
  const summary = selected.summary || {};
  const rows = asArray(selected.rows);
  const summaryRoot = $("#portfolioSummary");
  const tableBody = $("#portfolioRows");
  if (!summaryRoot || !tableBody) return;
  const cards = [
    ["全期間毛報酬", firstValue(summary, ["grossReturn", "cumulativeGrossReturn"]), "percent"],
    ["全期間淨報酬", firstValue(summary, ["netReturn", "cumulativeNetReturn"]), "percent"],
    ["大盤同期績效", firstValue(summary, ["benchmarkReturn", "benchmarkCumulativeReturn"]), "percent"],
    ["超額績效", firstValue(summary, ["excessReturn", "excessCumulativeReturn"]), "percent"],
    ["最大回撤", firstValue(summary, ["maxDrawdown", "worstDrawdown"]), "percent"],
    ["最近一週", firstValue(summary, ["recent5", "recent5Return", "latestWeekReturn"]), "percent"],
    ["最近一月", firstValue(summary, ["recent20", "recent20Return", "latestMonthReturn"]), "percent"],
    ["交易成本假設", firstValue(summary, ["costAssumption"], payload.costAssumption), "text"],
  ];
  summaryRoot.innerHTML = cards.map(([label, value, kind]) => `
    <article class="status-summary-card">
      <span>${escapeHtml(label)}</span>
      <strong class="${kind === "percent" && !isMissing(value) ? valueClass(value) : "value-flat"}">
        ${escapeHtml(kind === "percent" ? formatValidationPercent(value) : formatPlainValue(value))}
      </strong>
    </article>
  `).join("");
  renderPortfolioChart(rows);
  tableBody.innerHTML = rows.length
    ? rows.slice(-50).map((row) => {
        const dailyReturn = portfolioRowValue(row, ["grossReturn", "dailyReturn", "portfolioDailyReturn"]);
        const grossCumulative = portfolioRowValue(row, ["cumulativeReturn", "grossCumulativeReturn"]);
        const netCumulative = portfolioRowValue(row, ["netCumulativeReturn", "cumulativeNetReturn"]);
        const benchmarkCumulative = portfolioRowValue(row, ["benchmarkCumulativeReturn"]);
        const excessCumulative = portfolioRowValue(row, ["excessCumulativeReturn"]);
        const drawdown = portfolioRowValue(row, ["portfolioMaxDrawdown", "maxDrawdown", "drawdown"]);
        return `
          <tr>
            <td>${escapeHtml(firstValue(row, ["date", "tradeDate"], "--"))}</td>
            <td class="${valueClass(dailyReturn)}">${formatValidationPercent(dailyReturn)}</td>
            <td class="${valueClass(grossCumulative)}">${formatValidationPercent(grossCumulative)}</td>
            <td class="${valueClass(netCumulative)}">${formatValidationPercent(netCumulative)}</td>
            <td class="${valueClass(benchmarkCumulative)}">${formatValidationPercent(benchmarkCumulative)}</td>
            <td class="${valueClass(excessCumulative)}">${formatValidationPercent(excessCumulative)}</td>
            <td class="${valueClass(drawdown)}">${formatValidationPercent(drawdown)}</td>
            <td>${formatValidationNumber(firstValue(row, ["holdingsCount", "holdingCount"]), 0)}</td>
            <td>${formatValidationNumber(firstValue(row, ["newEntries", "newEntryCount"]), 0)}</td>
            <td>${formatValidationNumber(firstValue(row, ["expiredPositions", "expired", "expiredCount", "exitCount"]), 0)}</td>
            <td>${formatValidationPercent(firstValue(row, ["themeConcentration"]))}</td>
            <td>${formatValidationPercent(firstValue(row, ["maxThemeWeight", "largestThemeWeight"]))}</td>
          </tr>
        `;
      }).join("")
    : emptyRow(12, "目前沒有可顯示的等權組合交易日資料。");
}

function renderValidationWarnings(status, loaded) {
  const root = $("#validationWarnings");
  if (!root) return;
  const messages = [];
  for (const fileName of VALIDATION_FILES) {
    const result = loaded[fileName];
    if (result?.error) messages.push({ type: "bad", text: `${fileName} 載入失敗：${result.error.message || result.error}` });
  }
  for (const warning of asArray(status?.warnings)) {
    messages.push({ type: "warn", text: warning });
  }
  if (status?.previousDataPreserved) {
    messages.push({ type: "warn", text: "本次驗證更新未完成，畫面保留上一版可用資料。" });
  }
  if (status?.lastError) {
    messages.push({ type: "bad", text: `最近一次錯誤：${status.lastError}` });
  }
  if (status?.pipelineIntegrated === false) {
    messages.push({ type: "bad", text: "績效驗證尚未成功接入全站更新流程。" });
  }
  if (!messages.length) {
    messages.push({ type: "ok", text: "績效驗證資料已載入；未到期週期維持空值，不列入勝率分母。" });
  }
  root.innerHTML = messages.map((item) => `
    <div class="tracking-alert tracking-alert-${item.type}">${escapeHtml(item.text)}</div>
  `).join("");
}

function renderValidationFailureBlock(selector, message, colspan = null) {
  const root = $(selector);
  if (!root) return;
  root.innerHTML = colspan
    ? emptyRow(colspan, message)
    : `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderValidation(loaded) {
  const detailResult = loaded["ai-validation-detail.json"];
  const summaryResult = loaded["ai-validation-summary.json"];
  const portfolioResult = loaded["ai-validation-portfolio.json"];
  const factorResult = loaded["ai-factor-performance.json"];
  const statusResult = loaded["ai-validation-status.json"];
  const status = statusResult?.data || {};

  setText("#validationUpdatedAt", `驗證更新：${formatValidationDateTime(status.generatedAt || status.generated_at)}`);
  renderValidationWarnings(status, loaded);

  if (summaryResult?.data) {
    renderValidationSummary(summaryResult.data);
    renderHoldingComparison(summaryResult.data);
  } else {
    renderValidationFailureBlock("#validationSummary", "績效摘要載入失敗。");
    renderValidationFailureBlock("#validationPeriodBody", "持有期間比較載入失敗。", 8);
    renderValidationFailureBlock("#validationPeriodCards", "持有期間比較載入失敗。");
  }

  if (detailResult?.data) {
    validationState.detail = detailResult.data;
    renderValidationDetails();
  } else {
    validationState.detail = null;
    setText("#validationDetailCount", "0 筆");
    renderValidationFailureBlock("#validationDetailBody", "個股驗證明細載入失敗。", 16);
    renderValidationFailureBlock("#validationDetailCards", "個股驗證明細載入失敗。");
  }

  if (factorResult?.data) {
    renderFactorPerformance(factorResult.data);
  } else {
    renderValidationFailureBlock("#validationFactorCards", "因子績效載入失敗。");
    renderValidationFailureBlock("#validationFactorBody", "因子績效載入失敗。", 10);
    renderValidationFailureBlock("#validationFactorWarning", "因子績效載入失敗。");
  }

  if (portfolioResult?.data) {
    validationState.portfolio = portfolioResult.data;
    renderPortfolio();
  } else {
    validationState.portfolio = null;
    renderValidationFailureBlock("#portfolioSummary", "等權組合績效載入失敗。");
    renderValidationFailureBlock("#portfolioCurve", "等權組合績效載入失敗。");
    renderValidationFailureBlock("#portfolioRows", "等權組合績效載入失敗。", 12);
  }
}

function bindValidationControls() {
  [
    "#validationModeFilter",
    "#validationDateFilter",
    "#validationStockFilter",
    "#validationOutcomeFilter",
    "#validationStatusFilter",
    "#validationTradeTypeFilter",
    "#validationRiskFilter",
    "#validationVersionFilter",
    "#validationConsecutiveFilter",
  ].forEach((selector) => {
    const element = $(selector);
    if (!element) return;
    const eventName = element.matches('input[type="search"]') ? "input" : "change";
    element.addEventListener(eventName, renderValidationDetails);
  });
  $("#portfolioRangeFilter")?.addEventListener("change", renderPortfolio);
}

function renderStatus(daily, extraWarnings = []) {
  setText("#latestTradeDate", daily.latestTradeDate || daily.latest_trade_date || "--");
  setText("#siteGeneratedAt", formatDateTime(daily.generatedAt || daily.generated_at));
  setText("#scoreVersion", daily.scoreVersion || "--");
  setText("#validScoreCount", `${Number(daily.validScoreCount || 0).toLocaleString("zh-TW")} 檔`);
  setText("#top10Status", daily.ok === true && daily.items?.length === 10 ? "成功" : "異常");
  setText("#historyTradingDays", `${Number(daily.historyTradingDays || 0)} 日`);
  setText("#radarUpdatedAt", `資料更新：${formatDateTime(daily.generatedAt || daily.generated_at)}`);

  const warnings = [...(daily.warnings || []), ...extraWarnings].filter(Boolean);
  const root = $("#radarWarnings");
  if (!root) return;
  root.innerHTML = warnings.length
    ? warnings.map((warning) => `<div class="tracking-alert tracking-alert-warn">${escapeHtml(warning)}</div>`).join("")
    : `<div class="tracking-alert tracking-alert-ok">正式評分、Top 10 與歷史快照日期同步。</div>`;
}

function renderToday(daily) {
  const items = Array.isArray(daily.items) ? daily.items : [];
  setText("#todayCount", `${items.length} / 10`);
  const body = $("#todayTop10Body");
  const cards = $("#todayTop10Cards");
  if (!items.length) {
    if (body) body.innerHTML = emptyRow(19, "今日沒有可用的正式 Top 10。");
    if (cards) cards.innerHTML = `<div class="empty-state">今日沒有可用的正式 Top 10。</div>`;
    return;
  }

  if (body) {
    body.innerHTML = items.map((item) => `
      <tr>
        <td><strong>#${item.rank}</strong></td>
        <td>${rankChange(item.rankChange)}</td>
        <td>${stockLink(item.code, item.name)}</td>
        <td>${escapeHtml(item.market || "--")}</td>
        <td class="tracking-concepts">${escapeHtml(conceptsText(item))}</td>
        <td><span class="score-badge">${formatNumber(item.totalScore, 1)}</span></td>
        <td>${formatNumber(item.fundamentalScore, 1)}</td>
        <td>${formatNumber(item.technicalScore, 1)}</td>
        <td>${formatNumber(item.chipScore, 1)}</td>
        <td>${formatNumber(item.turnoverScore, 1)}</td>
        <td>${formatPercent(item.turnoverRate, 2)}</td>
        <td>${item.appearances5d ?? "--"}</td>
        <td>${item.appearances20d ?? "--"}</td>
        <td>${item.consecutiveDays ?? "--"}</td>
        <td>${trendBadge(item.scoreTrend)}</td>
        <td>${escapeHtml(item.tradeType || "--")}</td>
        <td><span class="badge ${item.riskLabel === "過熱" ? "warn" : ""}">${escapeHtml(item.riskLabel || "--")}</span></td>
        <td><div class="status-badge-list">${statusBadges(item.statusLabels)}</div></td>
        <td>${escapeHtml(item.dataDate || "--")}</td>
      </tr>
    `).join("");
  }

  if (cards) {
    cards.innerHTML = items.map((item) => `
      <article class="tracking-stock-card">
        <div class="tracking-card-head">
          <span class="tracking-rank">#${item.rank}</span>
          ${stockLink(item.code, item.name)}
          ${rankChange(item.rankChange)}
        </div>
        <p>${escapeHtml(item.market || "--")}・${escapeHtml(conceptsText(item))}</p>
        <div class="tracking-card-score">
          <strong>${formatNumber(item.totalScore, 1)}</strong>
          <span>基本 ${formatNumber(item.fundamentalScore, 1)}</span>
          <span>技術 ${formatNumber(item.technicalScore, 1)}</span>
          <span>籌碼 ${formatNumber(item.chipScore, 1)}</span>
          <span>熱度 ${formatNumber(item.turnoverScore, 1)}</span>
        </div>
        <div class="tracking-card-meta">
          <span>週轉率 ${formatPercent(item.turnoverRate, 2)}</span>
          <span>5 日 ${item.appearances5d ?? "--"} 次</span>
          <span>20 日 ${item.appearances20d ?? "--"} 次</span>
          <span>連續 ${item.consecutiveDays ?? "--"} 日</span>
          <span>${escapeHtml(item.scoreTrend || "資料不足")}</span>
        </div>
        <div class="status-badge-list">${statusBadges(item.statusLabels)}</div>
      </article>
    `).join("");
  }
}

function renderContinuous(daily) {
  const items = Array.isArray(daily.continuous) ? daily.continuous : [];
  setText("#continuousCount", `${items.length} 檔`);
  const root = $("#continuousList");
  if (!root) return;
  root.innerHTML = items.length
    ? items.map((item) => `
        <article class="persistence-card">
          <div class="tracking-card-head">
            ${stockLink(item.code, item.name)}
            <span class="score-badge">${formatNumber(item.totalScore, 1)}</span>
          </div>
          <strong>連續 ${item.consecutiveDays} 個交易日</strong>
          <p>近 5 日 ${item.appearances5d} 次・近 20 日 ${item.appearances20d} 次・目前第 ${item.rank} 名</p>
          <div class="status-badge-list">${statusBadges(item.statusLabels)}</div>
        </article>
      `).join("")
    : `<div class="empty-state">目前沒有連續 2 日以上入榜的股票。</div>`;
}

function renderWeekly(payload) {
  const body = $("#weeklyBody");
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const dates = Array.isArray(payload?.tradingDates) ? payload.tradingDates : [];
  setText(
    "#weeklyWindow",
    dates.length ? `使用 ${dates.length} 個有效交易日：${dates.join("、")}` : "尚無週榜交易日。",
  );
  if (!body) return;
  body.innerHTML = items.length
    ? items.map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${stockLink(item.code, item.name)}</td>
          <td><strong>${item.appearances5d}</strong></td>
          <td>${formatNumber(item.averageRank5d, 2)}</td>
          <td>${item.bestRank5d}</td>
          <td>${item.latestRank ?? "--"}</td>
          <td>${rankChange(item.rankChange)}</td>
          <td>${item.consecutiveDays}</td>
          <td>${formatNumber(item.averageScore5d, 2)}</td>
          <td>${formatNumber(item.latestScore, 1)}</td>
          <td>${trendBadge(item.scoreTrend)}</td>
          <td>${escapeHtml(item.firstSeenDate)}<br>${escapeHtml(item.lastSeenDate)}</td>
        </tr>
      `).join("")
    : emptyRow(12, "歷史快照不足，尚無近 5 日週榜。");
}

function renderMonthly(payload) {
  const body = $("#monthlyBody");
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const dates = Array.isArray(payload?.tradingDates) ? payload.tradingDates : [];
  setText(
    "#monthlyWindow",
    dates.length ? `使用 ${dates.length} 個有效交易日：${dates.join("、")}` : "尚無月榜交易日。",
  );
  if (!body) return;
  body.innerHTML = items.length
    ? items.map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${stockLink(item.code, item.name)}</td>
          <td><strong>${item.appearances20d}</strong></td>
          <td>${formatPercent(Number(item.appearanceRate20d || 0) * 100, 1)}</td>
          <td>${formatNumber(item.averageRank20d, 2)}</td>
          <td>${item.bestRank20d}</td>
          <td>${item.consecutiveDays}</td>
          <td>${formatNumber(item.averageScore20d, 2)}</td>
          <td>${formatNumber(item.latestScore, 1)}</td>
          <td>${trendBadge(item.scoreTrend20d)}</td>
          <td>${escapeHtml(item.firstSeenDate)}<br>${escapeHtml(item.lastSeenDate)}</td>
        </tr>
      `).join("")
    : emptyRow(11, "歷史快照不足，尚無近 20 日月榜。");
}

function renderChangeList(selector, items, emptyMessage) {
  const root = $(selector);
  if (!root) return;
  root.innerHTML = items.length
    ? items.map((item) => {
        const currentRank = item.latestRank ?? item.rank;
        const rankText = currentRank
          ? `今日第 ${currentRank} 名`
          : `昨日第 ${item.previousRank ?? "--"} 名`;
        return `
          <article class="change-item">
            <div>${stockLink(item.code, item.name)} <span class="badge">${escapeHtml(item.entryStatus)}</span></div>
            <span>${rankText}</span>
          </article>
        `;
      }).join("")
    : `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
}

function renderFailure(message) {
  setText("#top10Status", "失敗");
  setText("#radarUpdatedAt", "資料載入失敗");
  const warning = $("#radarWarnings");
  if (warning) {
    warning.innerHTML = `<div class="tracking-alert tracking-alert-bad">${escapeHtml(message)}</div>`;
  }
  const tables = [
    ["#todayTop10Body", 19],
    ["#weeklyBody", 12],
    ["#monthlyBody", 11],
  ];
  tables.forEach(([selector, colspan]) => {
    const body = $(selector);
    if (body) body.innerHTML = emptyRow(colspan, message);
  });
  ["#todayTop10Cards", "#continuousList", "#newEntrantsList", "#droppedList"].forEach((selector) => {
    const root = $(selector);
    if (root) root.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
  });
}

async function loadAndRender() {
  setText("#top10Status", "讀取中");
  setText("#validationUpdatedAt", "驗證資料載入中");
  const loaded = await loadProcessedData(FILES);
  const dailyResult = loaded["ai-top10-daily.json"];
  const weeklyResult = loaded["ai-persistence-weekly.json"];
  const monthlyResult = loaded["ai-persistence-monthly.json"];

  if (dailyResult.error || !dailyResult.data || dailyResult.data.ok !== true) {
    console.error(dailyResult.error || dailyResult.data);
    renderFailure("正式多因子評分資料載入失敗，保留上一版或停止更新。");
  } else {
    const daily = dailyResult.data;
    const extraWarnings = [];
    if (weeklyResult.error || !weeklyResult.data?.ok) {
      extraWarnings.push(`近 5 日週榜載入失敗：${weeklyResult.error?.message || "資料狀態異常"}`);
    }
    if (monthlyResult.error || !monthlyResult.data?.ok) {
      extraWarnings.push(`近 20 日月榜載入失敗：${monthlyResult.error?.message || "資料狀態異常"}`);
    }

    renderStatus(daily, extraWarnings);
    renderToday(daily);
    renderContinuous(daily);
    renderWeekly(weeklyResult.data);
    renderMonthly(monthlyResult.data);
    renderChangeList("#newEntrantsList", daily.newEntrants || [], "今日沒有新進榜或重返榜股票。");
    renderChangeList("#droppedList", daily.dropped || [], "今日沒有跌出榜股票。");
  }

  renderValidation(loaded);
}

export function initRadarPage() {
  bindValidationControls();
  $("#reloadRadarData")?.addEventListener("click", loadAndRender);
  loadAndRender();
}

initRadarPage();
