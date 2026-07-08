const DISPLAY_LIMIT = 100;
const RADAR_JSON_PATH = "./data/radar.json";
const STATUS_JSON_PATH = "./data/update_status.json";
const PROCESSED_PATH = "./data/processed";

const state = {
  rows: [],
  coverage: {
    stockMaster: 0,
    quoteMatched: 0,
    revenueMatched: 0,
  },
  status: null,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function cacheBust(path) {
  const joiner = path.includes("?") ? "&" : "?";
  return `${path}${joiner}t=${Date.now()}`;
}

async function fetchJson(path) {
  const response = await fetch(cacheBust(path), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} HTTP ${response.status}`);
  }
  return response.json();
}

async function safeFetchJson(label, path) {
  try {
    return {
      label,
      path,
      ok: true,
      payload: await fetchJson(path),
      error: null,
    };
  } catch (error) {
    console.warn(`Radar data not available: ${label}`, error);
    return {
      label,
      path,
      ok: false,
      payload: null,
      error: error?.message || String(error),
    };
  }
}

async function loadProcessedFile(fileName) {
  try {
    return await fetchJson(`${PROCESSED_PATH}/${fileName}`);
  } catch (error) {
    console.warn(`Processed data not available: ${fileName}`, error);
    return null;
  }
}

function getItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.scores)) return payload.scores;
  if (Array.isArray(payload?.stocks)) return payload.stocks;
  if (Array.isArray(payload?.rows)) return payload.rows;
  if (Array.isArray(payload?.rankings)) return payload.rankings;
  return [];
}

function formatFailureSummary(failures) {
  return failures
    .map((failure) => `${failure.label || failure.path}：${failure.error || "載入失敗"}`)
    .join("；");
}

function normalizeSymbol(value) {
  const match = String(value ?? "").match(/\d{4,6}/);
  return match ? match[0] : "";
}

function normalizeMarket(value) {
  const text = String(value ?? "").trim();
  if (/上市|TWSE|Listed/i.test(text)) return "上市";
  if (/上櫃|TPEx|OTC/i.test(text)) return "上櫃";
  return text || "--";
}

function numeric(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = String(value).trim();
  if (!text || ["-", "--", "N/A", "null", "None"].includes(text)) return null;
  const match = text.replaceAll(",", "").replace("%", "").match(/[-+]?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function firstValue(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== "") return value;
  }
  return null;
}

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function roundScore(value) {
  const number = numeric(value);
  return number === null ? null : Math.round(number * 10) / 10;
}

function formatNumber(value, digits = 0) {
  const number = numeric(value);
  if (number === null) return "--";
  return new Intl.NumberFormat("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(number);
}

function formatDecimal(value, digits = 2) {
  return formatNumber(value, digits);
}

function formatPercent(value, digits = 2) {
  const number = numeric(value);
  if (number === null) return "--";
  return `${formatNumber(number, digits)}%`;
}

function formatSignedPercent(value, digits = 2) {
  const number = numeric(value);
  if (number === null) return "--";
  const sign = number > 0 ? "+" : "";
  return `${sign}${formatNumber(number, digits)}%`;
}

function valueClass(value) {
  const number = numeric(value);
  if (number === null || number === 0) return "value-flat";
  return number > 0 ? "value-up" : "value-down";
}

function formatDateTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").replace(/\+08:00$/, "").slice(0, 19);
}

function scoreBadge(value) {
  const score = roundScore(value);
  if (score === null) return "--";
  const hot = score >= 70 ? " score-hot" : "";
  return `<span class="score-pill${hot}">${formatNumber(score, 1)}</span>`;
}

function riskBadge(value) {
  const label = String(value || "正常");
  const riskClass = /高|過熱|回檔|資料不足/.test(label) ? " risk-high" : /低|正常/.test(label) ? " risk-low" : "";
  return `<span class="risk-badge${riskClass}">${escapeHtml(label)}</span>`;
}

function stockLink(symbol, name) {
  const code = normalizeSymbol(symbol);
  const label = `${name || "--"} ${code}`.trim();
  if (!code) return escapeHtml(label || "--");
  return `<a class="stock-link" href="stock.html?symbol=${encodeURIComponent(code)}">${escapeHtml(label)}</a>`;
}

function toSymbolMap(items) {
  const map = new Map();
  for (const item of items || []) {
    const symbol = normalizeSymbol(item.symbol ?? item.code ?? item.stock_id ?? item.SecuritiesCompanyCode);
    if (symbol) map.set(symbol, item);
  }
  return map;
}

function normalizeRadarItem(item) {
  const symbol = normalizeSymbol(item.code ?? item.symbol);
  return {
    symbol,
    name: item.name ?? item.stock_name ?? "",
    market: normalizeMarket(item.market),
    trade_price: numeric(item.close ?? item.trade_price),
    close: numeric(item.close ?? item.trade_price),
    change_pct: numeric(item.change_percent ?? item.change_pct),
    volume: numeric(item.volume),
    trade_date: item.trade_date ?? "",
    updated_at: item.updated_at ?? "",
    source: item.source ?? "",
  };
}

function computeTechnical(row) {
  const change = numeric(row.change_pct);
  const turnover = numeric(row.turnover_rate_pct);
  let score = 45;
  if (change !== null) score += clamp(change * 4, -25, 35);
  if (turnover !== null) score += clamp(turnover * 2.2, 0, 20);
  return clamp(score);
}

function computeChip(row) {
  const turnover = numeric(row.turnover_rate_pct);
  const volume = numeric(row.volume);
  let score = 42;
  if (turnover !== null) score += clamp(turnover * 4, 0, 35);
  if (volume !== null) score += clamp(Math.log10(Math.max(volume, 1)) * 5, 0, 25);
  return clamp(score);
}

function computeFundamental(row) {
  const yoy = numeric(row.revenue_yoy_pct);
  const mom = numeric(row.revenue_mom_pct);
  const eps = numeric(row.eps);
  const gross = numeric(row.gross_margin_pct);
  let score = 38;
  if (yoy !== null) score += clamp(yoy * 0.32, -22, 32);
  if (mom !== null) score += clamp(mom * 0.18, -12, 18);
  if (eps !== null) score += clamp(eps * 4, -10, 22);
  if (gross !== null) score += clamp((gross - 15) * 0.55, -8, 22);
  return clamp(score);
}

function computeDataQuality(row) {
  const fields = [
    row.trade_price,
    row.change_pct,
    row.volume,
    row.revenue_million,
    row.revenue_yoy_pct,
    row.eps,
    row.gross_margin_pct,
  ];
  const filled = fields.filter((value) => numeric(value) !== null).length;
  return Math.round((filled / fields.length) * 100);
}

function inferPattern(row) {
  if (numeric(row.revenue_yoy_pct) >= 30) return "營收高成長";
  if (numeric(row.gross_margin_pct) >= 35) return "高毛利率";
  if (numeric(row.eps) > 0) return "獲利篩選";
  if (numeric(row.change_pct) > 0) return "量價轉強";
  return "全市場量化";
}

function inferRisk(row) {
  if (numeric(row.change_pct) >= 8) return "過熱";
  if (numeric(row.change_pct) <= -7) return "回檔";
  if (numeric(row.volume) !== null && numeric(row.volume) < 50000) return "低流動";
  if (numeric(row.trade_price) === null && numeric(row.revenue_million) === null) return "資料不足";
  return "正常";
}

function inferEntryReason(row) {
  const parts = [];
  if (numeric(row.revenue_yoy_pct) !== null) parts.push(`營收年增 ${formatSignedPercent(row.revenue_yoy_pct)}`);
  if (numeric(row.revenue_mom_pct) !== null) parts.push(`月增 ${formatSignedPercent(row.revenue_mom_pct)}`);
  if (numeric(row.eps) !== null) parts.push(`EPS ${formatDecimal(row.eps, 2)}`);
  if (numeric(row.gross_margin_pct) !== null) parts.push(`毛利率 ${formatPercent(row.gross_margin_pct)}`);
  if (numeric(row.turnover_rate_pct) !== null) parts.push(`週轉率 ${formatPercent(row.turnover_rate_pct)}`);
  if (numeric(row.change_pct) !== null) parts.push(`股價漲跌 ${formatSignedPercent(row.change_pct)}`);
  return parts.slice(0, 4).join("，") || "資料不足，保留於個股查詢檢視。";
}

function mergeRow(stock, score, metric, quote) {
  const symbol = normalizeSymbol(stock?.symbol ?? stock?.code ?? score?.symbol ?? score?.code ?? metric?.symbol ?? quote?.symbol);
  const market = normalizeMarket(firstValue(stock?.market, metric?.market, quote?.market, score?.market));
  const theme = firstValue(score?.theme, stock?.theme, stock?.supply_chain, stock?.industry, "未分類");
  const row = {
    symbol,
    name: firstValue(stock?.name, score?.name, metric?.name, quote?.name, "--"),
    market,
    industry: firstValue(stock?.industry, score?.industry, metric?.industry, "--"),
    theme,
    pattern: firstValue(score?.pattern, null),
    trade_price: numeric(firstValue(quote?.trade_price, quote?.close, metric?.trade_price, metric?.close, score?.trade_price, score?.close)),
    change_pct: numeric(firstValue(quote?.change_pct, quote?.change_percent, metric?.change_pct, metric?.change_percent, score?.change_pct, score?.change_percent)),
    volume: numeric(firstValue(quote?.volume, metric?.volume, score?.volume)),
    turnover_rate_pct: numeric(firstValue(metric?.turnover_rate_pct, score?.turnover_rate_pct, quote?.turnover_rate_pct)),
    revenue_million: numeric(firstValue(metric?.revenue_million, score?.revenue_million)),
    revenue_mom_pct: numeric(firstValue(metric?.revenue_mom_pct, score?.revenue_mom_pct)),
    revenue_yoy_pct: numeric(firstValue(metric?.revenue_yoy_pct, score?.revenue_yoy_pct)),
    eps: numeric(firstValue(metric?.eps, score?.eps)),
    gross_margin_pct: numeric(firstValue(metric?.gross_margin_pct, score?.gross_margin_pct)),
    updated_at: firstValue(score?.updated_at, metric?.updated_at, quote?.updated_at, ""),
    trade_date: firstValue(quote?.trade_date, metric?.date, score?.date, ""),
    entry_reason: firstValue(score?.entry_reason, score?.reason, null),
    risk_level: firstValue(score?.risk_level, score?.riskLabel, null),
  };

  row.technical_score = roundScore(firstValue(score?.technical_score, score?.technicalScore, computeTechnical(row)));
  row.chip_score = roundScore(firstValue(score?.chip_score, score?.chipScore, computeChip(row)));
  row.fundamental_score = roundScore(firstValue(score?.fundamental_score, score?.fundamentalScore, computeFundamental(row)));
  row.news_score = roundScore(firstValue(score?.news_score, 0)) ?? 0;
  row.data_quality_score = computeDataQuality(row);
  row.total_score = roundScore(firstValue(
    score?.total_score,
    score?.totalScore,
    score?.asuradaScore,
    row.technical_score * 0.22 +
      row.chip_score * 0.18 +
      row.fundamental_score * 0.45 +
      row.news_score * 0.05 +
      row.data_quality_score * 0.1,
  ));
  row.pattern = row.pattern || inferPattern(row);
  row.risk_level = row.risk_level || inferRisk(row);
  row.entry_reason = row.entry_reason || inferEntryReason(row);
  return row;
}

function buildRows({ stocks, scores, metrics, radarItems }) {
  const scoreMap = toSymbolMap(scores);
  const metricMap = toSymbolMap(metrics);
  const quoteMap = toSymbolMap(radarItems.map(normalizeRadarItem));
  const stockUniverse = (stocks || [])
    .map((stock) => ({ ...stock, symbol: normalizeSymbol(stock.symbol ?? stock.code), market: normalizeMarket(stock.market) }))
    .filter((stock) => stock.symbol && ["上市", "上櫃"].includes(stock.market));
  const universe = stockUniverse.length
    ? stockUniverse
    : radarItems.map(normalizeRadarItem).filter((item) => item.symbol);

  const rows = universe.map((stock) => {
    const symbol = normalizeSymbol(stock.symbol ?? stock.code);
    return mergeRow(stock, scoreMap.get(symbol), metricMap.get(symbol), quoteMap.get(symbol));
  });

  rows.sort((a, b) =>
    (numeric(b.total_score) ?? -1) - (numeric(a.total_score) ?? -1) ||
    (numeric(b.fundamental_score) ?? -1) - (numeric(a.fundamental_score) ?? -1) ||
    (numeric(b.revenue_yoy_pct) ?? -9999) - (numeric(a.revenue_yoy_pct) ?? -9999)
  );

  const coverage = {
    stockMaster: stockUniverse.length || universe.length,
    quoteMatched: rows.filter((row) => numeric(row.trade_price) !== null || numeric(row.volume) !== null).length,
    revenueMatched: rows.filter((row) => numeric(row.revenue_million) !== null || numeric(row.revenue_yoy_pct) !== null).length,
  };
  return { rows, coverage };
}

function buildRowsResilient({ stocks, scores, metrics, radarItems }) {
  const normalizedRadarItems = (radarItems || []).map(normalizeRadarItem).filter((item) => item.symbol);
  const normalizedScores = (scores || [])
    .map((score) => ({
      ...score,
      symbol: normalizeSymbol(score.symbol ?? score.code ?? score.stock_id),
      market: normalizeMarket(score.market),
    }))
    .filter((score) => score.symbol);
  const normalizedMetrics = (metrics || [])
    .map((metric) => ({
      ...metric,
      symbol: normalizeSymbol(metric.symbol ?? metric.code ?? metric.stock_id),
      market: normalizeMarket(metric.market),
    }))
    .filter((metric) => metric.symbol);

  const scoreMap = toSymbolMap(normalizedScores);
  const metricMap = toSymbolMap(normalizedMetrics);
  const quoteMap = toSymbolMap(normalizedRadarItems);
  const stockUniverse = (stocks || [])
    .map((stock) => ({
      ...stock,
      symbol: normalizeSymbol(stock.symbol ?? stock.code ?? stock.stock_id),
      market: normalizeMarket(stock.market),
    }))
    .filter((stock) => stock.symbol && ["上市", "上櫃"].includes(stock.market));

  const universe = stockUniverse.length
    ? stockUniverse
    : normalizedRadarItems.length
      ? normalizedRadarItems
      : normalizedScores.length
        ? normalizedScores
        : normalizedMetrics;

  const rows = universe
    .map((stock) => {
      const symbol = normalizeSymbol(stock.symbol ?? stock.code ?? stock.stock_id);
      return mergeRow(stock, scoreMap.get(symbol), metricMap.get(symbol), quoteMap.get(symbol));
    })
    .filter((row) => row.symbol);

  rows.sort((a, b) =>
    (numeric(b.total_score) ?? -1) - (numeric(a.total_score) ?? -1) ||
    (numeric(b.fundamental_score) ?? -1) - (numeric(a.fundamental_score) ?? -1) ||
    (numeric(b.revenue_yoy_pct) ?? -9999) - (numeric(a.revenue_yoy_pct) ?? -9999)
  );

  const coverage = {
    stockMaster: stockUniverse.length || universe.length,
    quoteMatched: rows.filter((row) => numeric(row.trade_price) !== null || numeric(row.volume) !== null).length,
    revenueMatched: rows.filter((row) => numeric(row.revenue_million) !== null || numeric(row.revenue_yoy_pct) !== null).length,
  };
  return { rows, coverage };
}

function fillSelect(selector, values) {
  const select = $(selector);
  if (!select) return;
  const first = select.querySelector("option")?.outerHTML || '<option value="">全部</option>';
  select.innerHTML = `${first}${[...values]
    .filter(Boolean)
    .sort((a, b) => String(a).localeCompare(String(b), "zh-Hant"))
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("")}`;
}

function renderStatus(status, radarPayload) {
  const statusValue = $("#statusValue");
  const tradeDate = $("#statusTradeDate");
  const updatedAt = $("#statusUpdatedAt");
  const source = $("#statusSource");
  const reason = $("#statusReason");
  const message = $("#radarStatusMessage");
  const pageUpdated = $("#radarUpdatedAt");

  const rawStatus = String(status?.status || radarPayload?.status || "failed").toLowerCase();
  const statusLabel = rawStatus === "success" ? "成功" : rawStatus === "partial" ? "部分成功" : rawStatus === "loading" ? "載入中" : "失敗";
  const sources = status?.sources ?? radarPayload?.source ?? [];
  const sourceText = Array.isArray(sources) ? sources.join("、") : typeof sources === "object" ? Object.values(sources).join("、") : String(sources || "--");
  const reasonText = status?.message || status?.stale_reason || status?.errors?.[0] || (rawStatus === "success" ? "資料已更新。" : "尚未取得資料。");

  if (statusValue) statusValue.textContent = statusLabel;
  if (tradeDate) tradeDate.textContent = status?.trade_date || radarPayload?.trade_date || "--";
  if (updatedAt) updatedAt.textContent = formatDateTime(status?.updated_at || radarPayload?.updated_at);
  if (source) source.textContent = sourceText || "--";
  if (reason) reason.textContent = reasonText;
  if (message) message.textContent = reasonText;
  if (pageUpdated) pageUpdated.textContent = `資料更新：${formatDateTime(status?.updated_at || radarPayload?.updated_at)}`;
}

function renderStatusResilient(status, radarPayload, failures = []) {
  const statusValue = $("#statusValue");
  const tradeDate = $("#statusTradeDate");
  const updatedAt = $("#statusUpdatedAt");
  const source = $("#statusSource");
  const reason = $("#statusReason");
  const message = $("#radarStatusMessage");
  const pageUpdated = $("#radarUpdatedAt");

  const rawStatus = String(status?.status || radarPayload?.status || (failures.length ? "partial" : "success")).toLowerCase();
  const statusLabel = ["success", "ok"].includes(rawStatus)
    ? "成功"
    : rawStatus === "partial"
      ? "部分成功"
      : rawStatus === "loading"
        ? "載入中"
        : "失敗";
  const dateText = status?.trade_date || radarPayload?.trade_date || radarPayload?.date || "--";
  const updatedText = status?.updated_at || radarPayload?.updated_at || "--";
  const sources = status?.sources ?? status?.source ?? radarPayload?.source ?? [];
  const sourceText = Array.isArray(sources)
    ? sources.filter(Boolean).join("、")
    : typeof sources === "object"
      ? Object.values(sources).filter(Boolean).join("、")
      : String(sources || "--");
  const failureText = failures.length ? `部分 JSON 載入失敗：${formatFailureSummary(failures)}` : "";
  const baseReason = status?.message || status?.stale_reason || status?.errors?.[0] || radarPayload?.message || "";
  const reasonText = [baseReason, failureText].filter(Boolean).join("；")
    || (["success", "ok"].includes(rawStatus) ? "資料已更新。" : "尚未取得資料。");

  if (statusValue) statusValue.textContent = statusLabel;
  if (tradeDate) tradeDate.textContent = dateText;
  if (updatedAt) updatedAt.textContent = formatDateTime(updatedText);
  if (source) source.textContent = sourceText || "--";
  if (reason) reason.textContent = reasonText;
  if (message) message.textContent = reasonText;
  if (pageUpdated) pageUpdated.textContent = `資料更新：${formatDateTime(updatedText)}`;
}

function passesFilters(row) {
  const search = ($("#stockSearch")?.value || "").trim().toLowerCase();
  if (search) {
    const haystack = [row.symbol, row.name, row.industry, row.theme].join(" ").toLowerCase();
    if (!haystack.includes(search)) return false;
  }

  const market = $("#marketFilter")?.value || "";
  if (market && row.market !== market) return false;

  const theme = $("#themeFilter")?.value || "";
  if (theme && row.theme !== theme) return false;

  const pattern = $("#patternFilter")?.value || "";
  if (pattern && row.pattern !== pattern) return false;

  const scoreMin = numeric($("#scoreFilter")?.value);
  if (scoreMin !== null && (numeric(row.total_score) ?? -1) < scoreMin) return false;

  const revenueYoyMin = numeric($("#revenueYoyFilter")?.value);
  if (revenueYoyMin !== null && ((numeric(row.revenue_yoy_pct) ?? -Infinity) < revenueYoyMin)) return false;

  const epsMin = numeric($("#epsFilter")?.value);
  if (epsMin !== null && ((numeric(row.eps) ?? -Infinity) < epsMin)) return false;

  const grossMin = numeric($("#grossMarginFilter")?.value);
  if (grossMin !== null && ((numeric(row.gross_margin_pct) ?? -Infinity) < grossMin)) return false;

  const risk = $("#riskFilter")?.value || "";
  if (risk && row.risk_level !== risk) return false;

  return true;
}

function renderCoverage(filteredCount, displayCount) {
  const coverage = $("#radarCoverage");
  const count = $("#radarCount");
  const hidden = Math.max(filteredCount - displayCount, 0);
  if (coverage) {
    coverage.textContent = `全市場 ${formatNumber(state.rows.length)} 檔；目前篩選符合 ${formatNumber(filteredCount)} 檔；畫面列出前 ${formatNumber(displayCount)} 檔；尚有 ${formatNumber(hidden)} 檔未列入畫面，可用個股查詢查看。資料覆蓋：主檔 ${formatNumber(state.coverage.stockMaster)} 檔、報價 ${formatNumber(state.coverage.quoteMatched)} 檔、營收 ${formatNumber(state.coverage.revenueMatched)} 檔。`;
  }
  if (count) count.textContent = `前 ${formatNumber(displayCount)} / ${formatNumber(filteredCount)} 檔`;
}

function renderTable(rows) {
  const tbody = $("#radarTableBody");
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="15" class="empty">目前沒有符合條件的股票。</td></tr>';
    return;
  }
  tbody.innerHTML = rows
    .map((row, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${stockLink(row.symbol, row.name)}</td>
        <td>${escapeHtml(row.market)}</td>
        <td>${escapeHtml(row.industry || "--")}</td>
        <td><span class="ranking-chip">${escapeHtml(row.theme || "未分類")}</span></td>
        <td>${scoreBadge(row.total_score)}</td>
        <td>${scoreBadge(row.fundamental_score)}</td>
        <td>${formatDecimal(row.trade_price, 2)}</td>
        <td class="${valueClass(row.change_pct)}">${formatSignedPercent(row.change_pct)}</td>
        <td>${formatDecimal(row.revenue_million, 2)}</td>
        <td class="${valueClass(row.revenue_yoy_pct)}">${formatSignedPercent(row.revenue_yoy_pct)}</td>
        <td>${formatDecimal(row.eps, 2)}</td>
        <td>${formatPercent(row.gross_margin_pct)}</td>
        <td>${riskBadge(row.risk_level)}</td>
        <td class="reason-cell">${escapeHtml(row.entry_reason)}</td>
      </tr>
    `)
    .join("");
}

function applyFilters() {
  const filtered = state.rows.filter(passesFilters);
  const displayRows = filtered.slice(0, DISPLAY_LIMIT);
  renderCoverage(filtered.length, displayRows.length);
  renderTable(displayRows);
}

function bindFilters() {
  if (document.body.dataset.radarFiltersBound === "true") return;
  document.body.dataset.radarFiltersBound = "true";
  [
    "stockSearch",
    "marketFilter",
    "themeFilter",
    "patternFilter",
    "scoreFilter",
    "revenueYoyFilter",
    "epsFilter",
    "grossMarginFilter",
    "riskFilter",
  ].forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.addEventListener(element.tagName === "INPUT" ? "input" : "change", applyFilters);
  });
  $("#reloadRadarData")?.addEventListener("click", () => loadAndRenderResilient());
}

function initTableFreezeToggles() {
  document.querySelectorAll("[data-table-freeze-toggle]").forEach((toggle) => {
    if (toggle.dataset.bound === "true") return;
    toggle.dataset.bound = "true";
    const selector = toggle.getAttribute("data-table-freeze-toggle");
    const label = toggle.getAttribute("data-freeze-label") || "凍結欄位";
    const sync = () => {
      const table = document.querySelector(selector);
      const enabled = table?.classList.contains("is-freeze-enabled");
      toggle.classList.toggle("is-active", Boolean(enabled));
      toggle.setAttribute("aria-pressed", enabled ? "true" : "false");
      toggle.textContent = `${label}：${enabled ? "開" : "關"}`;
    };
    toggle.addEventListener("click", () => {
      document.querySelector(selector)?.classList.toggle("is-freeze-enabled");
      sync();
    });
    sync();
  });
}

async function loadAndRender() {
  renderStatus({ status: "loading", message: "正在讀取最新雷達資料。" }, null);
  try {
    const [stocksPayload, scoresPayload, metricsPayload, radarPayload, statusPayload] = await Promise.all([
      loadProcessedFile("stocks_master.json"),
      loadProcessedFile("ai_scores_daily.json"),
      loadProcessedFile("stock_metrics_daily.json"),
      fetchJson(RADAR_JSON_PATH),
      fetchJson(STATUS_JSON_PATH),
    ]);

    const stocks = getItems(stocksPayload);
    const scores = getItems(scoresPayload);
    const metrics = getItems(metricsPayload);
    const radarItems = getItems(radarPayload);
    const built = buildRows({ stocks, scores, metrics, radarItems });
    state.rows = built.rows;
    state.coverage = built.coverage;
    state.status = statusPayload;

    fillSelect("#themeFilter", new Set(state.rows.map((row) => row.theme)));
    fillSelect("#patternFilter", new Set(state.rows.map((row) => row.pattern)));
    renderStatus(statusPayload, radarPayload);
    applyFilters();
  } catch (error) {
    console.error(error);
    state.rows = [];
    state.coverage = { stockMaster: 0, quoteMatched: 0, revenueMatched: 0 };
    renderStatus({ status: "failed", message: `JSON 載入失敗：${error.message}` }, null);
    renderCoverage(0, 0);
    renderTable([]);
  }
}

async function loadAndRenderResilient() {
  renderStatusResilient({ status: "loading", message: "正在讀取最新雷達資料。" }, null);
  try {
    const [stocksResult, scoresResult, metricsResult, radarResult, statusResult] = await Promise.all([
      safeFetchJson("stocks_master.json", `${PROCESSED_PATH}/stocks_master.json`),
      safeFetchJson("ai_scores_daily.json", `${PROCESSED_PATH}/ai_scores_daily.json`),
      safeFetchJson("stock_metrics_daily.json", `${PROCESSED_PATH}/stock_metrics_daily.json`),
      safeFetchJson("radar.json", RADAR_JSON_PATH),
      safeFetchJson("update_status.json", STATUS_JSON_PATH),
    ]);
    const results = [stocksResult, scoresResult, metricsResult, radarResult, statusResult];
    const failures = results.filter((result) => !result.ok);

    const stocks = getItems(stocksResult.payload);
    const scores = getItems(scoresResult.payload);
    const metrics = getItems(metricsResult.payload);
    const radarPayload = radarResult.payload;
    const radarItems = getItems(radarPayload);
    const built = buildRowsResilient({ stocks, scores, metrics, radarItems });
    state.rows = built.rows;
    state.coverage = built.coverage;
    const statusPayload = statusResult.payload || {
      status: failures.length ? "partial" : "success",
      message: failures.length ? `部分資料載入失敗：${formatFailureSummary(failures)}` : "資料載入完成。",
    };
    state.status = statusPayload;

    fillSelect("#themeFilter", new Set(state.rows.map((row) => row.theme)));
    fillSelect("#patternFilter", new Set(state.rows.map((row) => row.pattern)));

    if (!state.rows.length) {
      const failureMessage = failures.length
        ? formatFailureSummary(failures)
        : "所有 JSON 都可讀取，但沒有任何可用股票資料。";
      renderStatusResilient({ status: "failed", message: `沒有可用資料。${failureMessage}` }, radarPayload, failures);
    } else if (failures.length && ["success", "ok"].includes(String(statusPayload.status || "").toLowerCase())) {
      renderStatusResilient({
        ...statusPayload,
        status: "partial",
        message: `部分資料載入失敗，但已用可用資料恢復清單：${formatFailureSummary(failures)}`,
      }, radarPayload, failures);
    } else {
      renderStatusResilient(statusPayload, radarPayload, failures);
    }
    applyFilters();
  } catch (error) {
    console.error(error);
    state.rows = [];
    state.coverage = { stockMaster: 0, quoteMatched: 0, revenueMatched: 0 };
    renderStatusResilient({ status: "failed", message: `雷達資料處理失敗：${error.message}` }, null);
    renderCoverage(0, 0);
    renderTable([]);
  }
}

export function initRadarPage() {
  initTableFreezeToggles();
  bindFilters();
  loadAndRenderResilient();
}
