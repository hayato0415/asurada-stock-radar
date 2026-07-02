import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, initTableFreezeToggles, renderEmpty, stockLink, normalizeText, unique } from "./utils.js";
import { formatDateTime, formatNumber, formatPercent, formatSignedPercent, valueClass } from "./formatters.js";
import { scoreBadge } from "./scoring-ui.js";

const THEME_DISPLAY_LIMIT = 20;
const DATA_FILES = [
  "theme_stats.json",
  "stocks_master.json",
  "stock_metrics_daily.json",
  "ai_scores_daily.json",
  "news_events.json",
];

let state = {
  payload: {},
  allThemes: [],
  filteredThemes: [],
};

function asNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replaceAll(",", "").replace("%", ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value, digits = 2) {
  const parsed = asNumber(value);
  if (parsed === null) return null;
  const factor = 10 ** digits;
  return Math.round(parsed * factor) / factor;
}

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function normalizeScore(value, min, max) {
  const parsed = asNumber(value);
  if (parsed === null || max === min) return 0;
  return clamp(((parsed - min) / (max - min)) * 100);
}

function buildMap(items, key = "symbol") {
  return new Map(items.map((item) => [String(item?.[key] ?? ""), item]).filter(([symbol]) => symbol));
}

function isValidMarket(stock) {
  return stock?.market === "上市" || stock?.market === "上櫃";
}

function normalizeThemeName(value) {
  const text = String(value ?? "").trim();
  if (!text || /^\d+$/.test(text)) return "";
  return text;
}

function sourceLabel(type) {
  return {
    manual: "手動題材對應",
    ai: "AI 題材標籤",
    news: "新聞事件",
    master: "主檔產業 / 供應鏈",
  }[type] ?? type;
}

function sourceBadges(types = []) {
  const labels = unique(types).map((type) => sourceLabel(type));
  return labels.length
    ? `<span class="source-badge-list">${labels.map((label) => `<span class="source-badge">${escapeHtml(label)}</span>`).join("")}</span>`
    : "--";
}

function metricReason(sourceTypes, metric) {
  const parts = [];
  if (sourceTypes.includes("news")) parts.push("新聞事件帶動");
  if (sourceTypes.includes("ai")) parts.push("AI 題材標籤");
  if (sourceTypes.includes("manual")) parts.push("手動題材對應");
  if (sourceTypes.includes("master")) parts.push("供應鏈 / 產業歸類");
  const yoy = asNumber(metric?.revenue_yoy_pct);
  const change = asNumber(metric?.change_pct);
  const turnover = asNumber(metric?.turnover_rate_pct);
  if (yoy !== null) parts.push(`營收年增 ${formatSignedPercent(yoy)}`);
  if (change !== null) parts.push(`漲跌 ${formatSignedPercent(change)}`);
  if (turnover !== null) parts.push(`週轉率 ${formatPercent(turnover, 2)}`);
  return parts.slice(0, 4).join("；") || "全市場主檔歸類";
}

function addThemeMember(themeMap, theme, stock, metric, score, sourceType, newsCount = 0) {
  const cleanTheme = normalizeThemeName(theme);
  if (!cleanTheme || cleanTheme === "未分類") return;
  const symbol = String(stock?.symbol ?? stock?.code ?? score?.symbol ?? "");
  if (!symbol || !stock?.name) return;

  if (!themeMap.has(cleanTheme)) {
    themeMap.set(cleanTheme, {
      theme: cleanTheme,
      beneficiaryMap: new Map(),
      high_score_news_count: 0,
      source_types: new Set(),
    });
  }

  const themeItem = themeMap.get(cleanTheme);
  const existing = themeItem.beneficiaryMap.get(symbol) ?? {
    symbol,
    name: stock.name,
    market: stock.market,
    industry: stock.industry,
    theme: cleanTheme,
    trade_price: metric?.trade_price ?? null,
    change_pct: metric?.change_pct ?? null,
    volume: metric?.volume ?? null,
    turnover_rate_pct: metric?.turnover_rate_pct ?? null,
    turnover_billion: turnoverBillion(metric),
    revenue_yoy_pct: metric?.revenue_yoy_pct ?? null,
    eps: metric?.eps ?? null,
    gross_margin_pct: metric?.gross_margin_pct ?? null,
    total_score: score?.total_score ?? null,
    source_types: [],
    source_labels: [],
    reason: "",
  };

  existing.source_types = unique([...existing.source_types, sourceType]);
  existing.source_labels = unique([...existing.source_labels, sourceLabel(sourceType)]);
  existing.reason = metricReason(existing.source_types, metric);
  themeItem.source_types.add(sourceType);
  themeItem.high_score_news_count += newsCount;
  themeItem.beneficiaryMap.set(symbol, existing);
}

function turnoverBillion(metric) {
  const price = asNumber(metric?.trade_price);
  const volume = asNumber(metric?.volume);
  if (price === null || volume === null) return null;
  return round((price * volume) / 100000000, 3);
}

function buildThemesFromUniverse({ stocks, metrics, scores, news }) {
  const metricMap = buildMap(metrics);
  const scoreMap = buildMap(scores);
  const stockMap = buildMap(stocks);
  const themeMap = new Map();

  for (const stock of stocks.filter(isValidMarket)) {
    const symbol = String(stock.symbol);
    const metric = metricMap.get(symbol) ?? {};
    const score = scoreMap.get(symbol) ?? {};
    const scoreTheme = normalizeThemeName(score.theme);
    const stockTheme = normalizeThemeName(stock.theme);
    const supplyChain = normalizeThemeName(stock.supply_chain);
    const industry = normalizeThemeName(stock.industry);

    if (scoreTheme) addThemeMember(themeMap, scoreTheme, stock, metric, score, "ai");
    addThemeMember(themeMap, stockTheme || supplyChain || industry || "未分類", stock, metric, score, "master");
  }

  for (const event of news) {
    const eventTheme = normalizeThemeName(event.theme || event.category || event.impact_theme);
    const stocksInNews = Array.isArray(event.stocks) ? event.stocks : Array.isArray(event.related_stocks) ? event.related_stocks : [];
    const newsScore = asNumber(event.news_score) ?? asNumber(event.event_score) ?? 0;
    const newsCount = newsScore >= 70 ? 1 : 0;
    for (const newsStock of stocksInNews) {
      const symbol = String(newsStock.symbol ?? newsStock.code ?? "");
      const stock = stockMap.get(symbol);
      if (!stock || !isValidMarket(stock)) continue;
      addThemeMember(themeMap, eventTheme, stock, metricMap.get(symbol) ?? {}, scoreMap.get(symbol) ?? {}, "news", newsCount);
    }
  }

  return aggregateThemeMap(themeMap);
}

function aggregateThemeMap(themeMap) {
  const rawThemes = Array.from(themeMap.values()).map((themeItem) => {
    const beneficiaries = Array.from(themeItem.beneficiaryMap.values());
    const changeValues = beneficiaries.map((item) => asNumber(item.change_pct)).filter((value) => value !== null);
    const scoreValues = beneficiaries.map((item) => asNumber(item.total_score)).filter((value) => value !== null);
    const turnoverValues = beneficiaries.map((item) => asNumber(item.turnover_billion)).filter((value) => value !== null);
    const upCount = beneficiaries.filter((item) => (asNumber(item.change_pct) ?? 0) > 0).length;
    const limitUpCount = beneficiaries.filter((item) => (asNumber(item.change_pct) ?? 0) >= 9.5).length;
    const turnover = turnoverValues.reduce((sum, value) => sum + value, 0);
    const themeChange = changeValues.length
      ? changeValues.reduce((sum, value) => sum + value, 0) / changeValues.length
      : null;
    const avgScore = scoreValues.length
      ? scoreValues.reduce((sum, value) => sum + value, 0) / scoreValues.length
      : 0;

    return {
      theme: themeItem.theme,
      theme_change_pct: themeChange === null ? null : round(themeChange, 2),
      turnover_billion: round(turnover, 2),
      up_count: upCount,
      limit_up_count: limitUpCount,
      beneficiary_count: beneficiaries.length,
      high_score_news_count: themeItem.high_score_news_count,
      avg_ai_score: round(avgScore, 1),
      source_types: Array.from(themeItem.source_types),
      beneficiary_stocks: beneficiaries.sort((a, b) => (asNumber(b.total_score) ?? 0) - (asNumber(a.total_score) ?? 0)),
    };
  });

  const maxTurnover = Math.max(1, ...rawThemes.map((item) => asNumber(item.turnover_billion) ?? 0));
  const maxLimitUp = Math.max(1, ...rawThemes.map((item) => asNumber(item.limit_up_count) ?? 0));
  const maxNews = Math.max(1, ...rawThemes.map((item) => asNumber(item.high_score_news_count) ?? 0));

  return rawThemes.map((item) => {
    const upRatio = item.beneficiary_count ? item.up_count / item.beneficiary_count : 0;
    const themeScore =
      normalizeScore(item.theme_change_pct, -5, 10) * 0.25 +
      normalizeScore(item.turnover_billion, 0, maxTurnover) * 0.25 +
      upRatio * 100 * 0.20 +
      normalizeScore(item.limit_up_count, 0, maxLimitUp) * 0.10 +
      normalizeScore(item.avg_ai_score, 0, 100) * 0.10 +
      normalizeScore(item.high_score_news_count, 0, maxNews) * 0.10;

    const leaderStocks = item.beneficiary_stocks.slice(0, 5).map((stock) => ({ symbol: stock.symbol, name: stock.name }));
    return {
      ...item,
      theme_score: round(themeScore, 1),
      source_labels: item.source_types.map(sourceLabel),
      leader_stocks: leaderStocks,
    };
  }).sort(sortThemes).map((item, index) => ({ ...item, rank: index + 1 }));
}

function normalizeThemeStats(payload) {
  const items = getItems(payload);
  if (!items.length) return [];
  return items.map((item) => ({
    ...item,
    beneficiary_stocks: Array.isArray(item.beneficiary_stocks) ? item.beneficiary_stocks : [],
    source_types: Array.isArray(item.source_types) ? item.source_types : [],
    source_labels: Array.isArray(item.source_labels) ? item.source_labels : (item.source_types ?? []).map(sourceLabel),
  })).filter((item) => item.theme && item.theme !== "未分類");
}

function shouldUseThemeStats(payload) {
  const items = getItems(payload);
  if (!items.length) return false;
  if (items.length <= 3) return false;
  return items.some((item) => Array.isArray(item.beneficiary_stocks) && item.beneficiary_stocks.length);
}

function sortThemes(a, b) {
  return (asNumber(b.theme_score) ?? 0) - (asNumber(a.theme_score) ?? 0)
    || (asNumber(b.turnover_billion) ?? 0) - (asNumber(a.turnover_billion) ?? 0)
    || (asNumber(b.theme_change_pct) ?? -999) - (asNumber(a.theme_change_pct) ?? -999)
    || (asNumber(b.beneficiary_count) ?? 0) - (asNumber(a.beneficiary_count) ?? 0);
}

function recalcTheme(theme, marketFilter = "") {
  const beneficiaries = (theme.beneficiary_stocks ?? []).filter((stock) => !marketFilter || stock.market === marketFilter);
  if (!beneficiaries.length) return null;
  const sourceTypes = unique(beneficiaries.flatMap((stock) => stock.source_types ?? theme.source_types ?? []));
  const changeValues = beneficiaries.map((item) => asNumber(item.change_pct)).filter((value) => value !== null);
  const turnover = beneficiaries.map((item) => asNumber(item.turnover_billion)).filter((value) => value !== null).reduce((sum, value) => sum + value, 0);
  const upCount = beneficiaries.filter((item) => (asNumber(item.change_pct) ?? 0) > 0).length;
  const limitUpCount = beneficiaries.filter((item) => (asNumber(item.change_pct) ?? 0) >= 9.5).length;
  return {
    ...theme,
    beneficiary_stocks: beneficiaries,
    beneficiary_count: beneficiaries.length,
    theme_change_pct: changeValues.length ? round(changeValues.reduce((sum, value) => sum + value, 0) / changeValues.length, 2) : null,
    turnover_billion: round(turnover, 2),
    up_count: upCount,
    limit_up_count: limitUpCount,
    source_types: sourceTypes,
    source_labels: sourceTypes.map(sourceLabel),
  };
}

function applyFilters() {
  const keyword = normalizeText($("#themeSearch")?.value);
  const market = $("#marketFilter")?.value ?? "";
  const source = $("#sourceFilter")?.value ?? "";
  const minScore = Number($("#scoreFilter")?.value ?? 0);

  const filtered = state.allThemes
    .map((theme) => recalcTheme(theme, market))
    .filter(Boolean)
    .filter((theme) => (asNumber(theme.theme_score) ?? 0) >= minScore)
    .filter((theme) => !source || (theme.source_types ?? []).includes(source))
    .filter((theme) => {
      if (!keyword) return true;
      const haystack = [
        theme.theme,
        ...(theme.beneficiary_stocks ?? []).flatMap((stock) => [stock.symbol, stock.name, stock.industry]),
      ].map(normalizeText).join(" ");
      return haystack.includes(keyword);
    })
    .sort(sortThemes)
    .map((theme, index) => ({ ...theme, rank: index + 1 }));

  state.filteredThemes = filtered;
  renderCoverage({
    ...state.coverage,
    filteredCount: filtered.length,
  });
  renderThemes(filtered);
}

function renderBeneficiaryTable(stocks = []) {
  if (!stocks.length) return renderEmpty("此題材目前沒有可辨識受惠個股");
  return `
    <div class="beneficiary-table-wrap">
      <table class="beneficiary-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>市場</th>
            <th>產業</th>
            <th>股價</th>
            <th>漲跌%</th>
            <th>成交金額(億)</th>
            <th>營收YoY</th>
            <th>EPS</th>
            <th>毛利率</th>
            <th>AI分數</th>
            <th>來源</th>
            <th>說明</th>
          </tr>
        </thead>
        <tbody>
          ${stocks.map((stock) => `
            <tr>
              <td>${stockLink(stock.symbol, stock.name)}</td>
              <td>${escapeHtml(stock.market ?? "--")}</td>
              <td>${escapeHtml(stock.industry ?? "--")}</td>
              <td>${formatNumber(stock.trade_price, 2)}</td>
              <td class="${valueClass(stock.change_pct)}">${formatSignedPercent(stock.change_pct)}</td>
              <td>${formatNumber(stock.turnover_billion, 2)}</td>
              <td class="${valueClass(stock.revenue_yoy_pct)}">${formatSignedPercent(stock.revenue_yoy_pct)}</td>
              <td>${formatNumber(stock.eps, 2)}</td>
              <td>${formatPercent(stock.gross_margin_pct, 2)}</td>
              <td>${formatNumber(stock.total_score, 1)}</td>
              <td>${sourceBadges(stock.source_types)}</td>
              <td class="reason-cell">${escapeHtml(stock.reason ?? "--")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function themeDetailLink(item) {
  const params = new URLSearchParams({ theme: item.theme ?? "" });
  return `
    <a class="theme-detail-link" href="./theme-detail.html?${params.toString()}">
      查看 ${formatNumber(item.beneficiary_count)} 檔
    </a>
  `;
}

function renderThemes(themes) {
  const displayRows = themes.slice(0, THEME_DISPLAY_LIMIT);
  $("#themesCount").textContent = `前 ${displayRows.length} / ${themes.length} 個題材`;
  $("#themesTableBody").innerHTML = displayRows.length
    ? displayRows.map((item) => `
      <tr>
        <td>${item.rank}</td>
        <td><span class="theme-name">${escapeHtml(item.theme)}</span></td>
        <td>${scoreBadge(item.theme_score)}</td>
        <td class="${valueClass(item.theme_change_pct)}">${formatSignedPercent(item.theme_change_pct)}</td>
        <td>${formatNumber(item.turnover_billion, 2)} 億</td>
        <td>${formatNumber(item.up_count)}</td>
        <td>${formatNumber(item.limit_up_count)}</td>
        <td>${formatNumber(item.beneficiary_count)}</td>
        <td>${formatNumber(item.high_score_news_count)}</td>
        <td>${sourceBadges(item.source_types)}</td>
        <td>${themeDetailLink(item)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="11">${renderEmpty("目前沒有符合條件的題材資料")}</td></tr>`;
}

function renderCoverage({ stocks = [], metrics = [], news = [], themes = [], payload = {}, filteredCount = null }) {
  const metricItems = metrics ?? [];
  const quoteCount = metricItems.filter((item) => asNumber(item.trade_price) !== null).length;
  const revenueCount = metricItems.filter((item) => asNumber(item.revenue_million) !== null).length;
  const manualCount = payload?.quality?.manual_membership_count ?? 0;
  const matchedCount = filteredCount ?? state.filteredThemes.length;
  const displayed = Math.min(matchedCount, THEME_DISPLAY_LIMIT);
  $("#themesCoverage").textContent =
    `全市場 ${formatNumber(stocks.length)} 檔；有效題材 ${formatNumber(themes.length)} 個；目前符合 ${formatNumber(matchedCount)} 個；` +
    `畫面列出前 ${formatNumber(displayed)} 個；資料來源：主檔 ${formatNumber(stocks.length)} 檔、行情 ${formatNumber(quoteCount)} 檔、` +
    `營收 ${formatNumber(revenueCount)} 檔、新聞 ${formatNumber(news.length)} 筆、手動題材 ${formatNumber(manualCount)} 筆。`;
}

function bindFilters() {
  ["themeSearch", "marketFilter", "sourceFilter", "scoreFilter"].forEach((id) => {
    const node = $(`#${id}`);
    if (node) node.addEventListener(id === "themeSearch" ? "input" : "change", applyFilters);
  });
}

async function initThemes() {
  initTableFreezeToggles();

  const loaded = await loadProcessedData(DATA_FILES);
  const themePayload = loaded["theme_stats.json"].data;
  const stocks = getItems(loaded["stocks_master.json"].data).filter(isValidMarket);
  const metrics = getItems(loaded["stock_metrics_daily.json"].data);
  const scores = getItems(loaded["ai_scores_daily.json"].data);
  const news = getItems(loaded["news_events.json"].data);

  const themes = shouldUseThemeStats(themePayload)
    ? normalizeThemeStats(themePayload).sort(sortThemes).map((item, index) => ({ ...item, rank: index + 1 }))
    : buildThemesFromUniverse({ stocks, metrics, scores, news });

  state = {
    payload: themePayload ?? {},
    allThemes: themes,
    filteredThemes: themes,
    coverage: { stocks, metrics, scores, news, themes, payload: themePayload },
  };

  $("#themesUpdatedAt").textContent = `資料更新：${formatDateTime(themePayload?.updated_at || loaded["stock_metrics_daily.json"].data?.updated_at)}`;
  bindFilters();
  renderCoverage({ stocks, metrics, scores, news, themes, payload: themePayload });
  renderThemes(themes);
}

initThemes().catch((error) => {
  console.error(error);
  $("#themesTableBody").innerHTML = `<tr><td colspan="11">${renderEmpty("題材資料載入失敗")}</td></tr>`;
});
