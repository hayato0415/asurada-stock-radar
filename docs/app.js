const HOLDINGS_KEY = "asurada_holdings";
const WATCHLIST_KEY = "asurada_watchlist";
const PORTFOLIO_STORAGE_KEY = "asuradaPortfolioDraft";
const BUILD_VERSION = "20260629-portfolio-live";
const APP_VERSION = "20260629-portfolio-live";

const state = {
  stocks: [],
  news: [],
  themes: {},
  concepts: {},
  themeCandidates: [],
  technical: {},
  profiles: {},
  master: {},
  stockConcepts: {},
  hotThemes: { date: "", updated_at: "", items: [], available: false },
  themeTop5: { date: "", updated_at: "", items: [], available: false },
  newsThemeRanking: { generated_at: "", items: [], available: false },
  lowBaseRanking: { generated_at: "", items: [], available: false },
  latestUpdate: { updated_at: "", stage: "", stage_label: "", schedule_time: "", data_version: "" },
  newsLatestMeta: { updated_at: "", stage: "", stage_label: "", schedule_time: "", data_version: "" },
  updateLog: { entries: [], available: false },
  universeCount: 0,
  monthlyRevenue: [],
  quarterlyRevenue: [],
  revenueLoaded: false,
  revenueError: "",
  stockConceptsLoaded: false,
};

let revenueLoadPromise = null;
let stockConceptLoadPromise = null;
let rankingAccordionsReady = false;
let siteVersionPromise = null;
let siteVersionState = {
  build_id: "",
  updated_at: "",
  status: "",
  mode: "",
  schedule_time: "",
  slot_label: "",
  datasets: {},
  warnings: [],
};

const TECH_THEMES = [
  "AI伺服器", "AI PC", "AI手機", "AI智慧型眼鏡", "智慧眼鏡", "PCB", "CPO", "光通訊", "矽光子", "記憶體", "半導體", "半導體設備", "玻璃基板",
  "低軌衛星", "重電", "散熱", "電源", "被動元件", "IC設計", "封測", "材料",
  "機器人", "智慧眼鏡", "無人機", "軍工電子",
];

const NON_TECH_THEMES = [
  "營建", "資產", "都更", "金融", "壽險", "銀行", "生醫", "生技", "觀光", "食品", "航運", "鋼鐵", "塑化", "原物料", "傳產",
];

const themeTaxonomy = globalThis.AsuradaThemeTaxonomy?.themeTaxonomy || {};

const constructionThemes = ["營建", "資產", "都更"];
const financeThemes = ["金融", "壽險", "銀行"];
const newsFilterAliases = {
  "利率匯率": ["利率匯率", "Fed", "美債", "利率", "匯率", "美元", "台幣", "金融壽險"],
  "原物料": ["原物料", "油價", "銅價", "黃金", "能源"],
  "AI": ["AI", "AI伺服器", "AI伺服器 + PCB"],
  "PCB": ["PCB", "AI伺服器 + PCB"],
};

function $(selector) {
  return document.querySelector(selector);
}

function $all(selector) {
  return Array.from(document.querySelectorAll(selector));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toNumber(value) {
  if (value === null || value === undefined) return NaN;
  const text = String(value).replace(/[,%+張億元萬元]/g, "").trim();
  const number = Number(text);
  return Number.isFinite(number) ? number : NaN;
}

function normalizeCode(value) {
  return String(value || "").trim().toUpperCase().replace(/\.(TW|TWO)$/i, "");
}

function parseCodes(text) {
  const seen = new Set();
  return String(text || "")
    .split(/[\s,\uFF0C\u3001]+/)
    .map(normalizeCode)
    .filter((code) => {
      if (!code || seen.has(code)) return false;
      seen.add(code);
      return true;
    });
}

function readStoredCodes(key) {
  const raw = localStorage.getItem(key);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map(normalizeCode).filter(Boolean);
    if (Array.isArray(parsed.codes)) return parsed.codes.map(normalizeCode).filter(Boolean);
  } catch {
    return parseCodes(raw);
  }
  return [];
}

function writeStoredCodes(key, codes) {
  localStorage.setItem(key, JSON.stringify({ codes }));
}

function shouldVersionDataPath(path) {
  const text = String(path || "");
  return text.includes("data/") && !text.includes("site-version.json") && !text.includes("?") && !/^https?:/i.test(text);
}

function withBuildVersion(path) {
  if (!shouldVersionDataPath(path) || !siteVersionState.build_id) return path;
  return `${path}?v=${encodeURIComponent(siteVersionState.build_id)}`;
}

async function loadSiteVersion() {
  if (siteVersionPromise) return siteVersionPromise;
  siteVersionPromise = (async () => {
    try {
      const response = await fetch("data/site-version.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      siteVersionState = data && typeof data === "object" ? { ...siteVersionState, ...data } : siteVersionState;
      return siteVersionState;
    } catch (error) {
      console.warn("Failed to load data/site-version.json", error);
      return siteVersionState;
    }
  })();
  return siteVersionPromise;
}

async function loadJson(path, fallback) {
  try {
    if (shouldVersionDataPath(path)) await loadSiteVersion();
    const response = await fetch(withBuildVersion(path), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    console.warn(`Failed to load ${path}`, error);
    return fallback;
  }
}

async function loadText(path) {
  if (shouldVersionDataPath(path)) await loadSiteVersion();
  const response = await fetch(withBuildVersion(path), { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.text();
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  const source = String(text || "").replace(/^\uFEFF/, "");
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    const next = source[i + 1];
    if (inQuotes) {
      if (char === '"' && next === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  const headers = (rows.shift() || []).map((header) => header.trim());
  return rows
    .filter((items) => items.some((item) => String(item || "").trim()))
    .map((items) => Object.fromEntries(headers.map((header, index) => [header, items[index] ?? ""])));
}

async function loadCsv(path) {
  return parseCsv(await loadText(path));
}

async function loadRevenueHistory() {
  if (state.revenueLoaded) return;
  if (revenueLoadPromise) return revenueLoadPromise;
  revenueLoadPromise = (async () => {
    try {
      const [monthly, quarterly] = await Promise.all([
        loadCsv("data/monthly_revenue_from_112.csv"),
        loadCsv("data/quarterly_revenue_from_112.csv"),
      ]);
      state.monthlyRevenue = monthly;
      state.quarterlyRevenue = quarterly;
      state.revenueError = "";
    } catch (error) {
      console.warn("Failed to load revenue history", error);
      state.monthlyRevenue = [];
      state.quarterlyRevenue = [];
      state.revenueError = "營收資料載入失敗，請稍後再試。";
    } finally {
      state.revenueLoaded = true;
    }
  })();
  return revenueLoadPromise;
}

async function loadStockConceptsIndex() {
  if (state.stockConceptsLoaded) return;
  if (stockConceptLoadPromise) return stockConceptLoadPromise;
  stockConceptLoadPromise = (async () => {
    try {
      const stockConcepts = await loadJson("data/stock-concepts-index.json", {});
      state.stockConcepts = stockConcepts && typeof stockConcepts === "object" ? stockConcepts : {};
    } catch (error) {
      console.warn("Failed to load stock concept index", error);
      state.stockConcepts = {};
    } finally {
      state.stockConceptsLoaded = true;
    }
  })();
  return stockConceptLoadPromise;
}

async function loadAllData() {
  const [stocks, radarLatest, news, themes, concepts, themeCandidates, technical, profiles, master, dailyHotThemes, themeTop5, updateReport, stockDataMeta, newsLatest] = await Promise.all([
    loadJson("data/stocks-latest.json", []),
    loadJson("data/radar-latest.json", null),
    loadJson("data/news-events.json", []),
    loadJson("data/themes-map.json", {}),
    loadJson("data/concepts-map.json", {}),
    loadJson("data/theme-candidates.json", []),
    loadJson("data/technical-latest.json", {}),
    loadJson("data/stock-profiles.json", {}),
    loadJson("data/stock-master.json", {}),
    loadJson("data/daily_hot_themes.json", null),
    loadJson("data/theme-top5.json", null),
    loadJson("data/update_report.json", null),
    loadJson("data/stock-data-meta.json", null),
    loadJson("data/news-latest.json", null),
  ]);
  const radarItems = latestItems(radarLatest);
  state.stocks = radarItems.length ? radarItems : (Array.isArray(stocks) ? stocks : latestItems(stocks));
  state.latestUpdate = latestMeta(radarLatest);
  const latestNewsItems = latestItems(newsLatest);
  state.news = latestNewsItems.length ? latestNewsItems : (Array.isArray(news) ? news : []);
  state.newsLatestMeta = latestMeta(newsLatest);
  state.themes = Array.isArray(themes)
    ? Object.fromEntries(themes.map((theme) => [theme.name || theme.theme_name, theme]))
    : (themes && typeof themes === "object" ? themes : {});
  state.concepts = concepts && typeof concepts === "object" ? concepts : {};
  state.themeCandidates = Array.isArray(themeCandidates) ? themeCandidates : [];
  state.technical = technical && typeof technical === "object" ? technical : {};
  state.profiles = profiles && typeof profiles === "object" ? profiles : {};
  state.master = master && typeof master === "object" ? master : {};
  state.hotThemes = normalizeDashboardData(dailyHotThemes);
  state.themeTop5 = normalizeDashboardData(themeTop5);
  if (!state.themeTop5.updated_at) {
    state.themeTop5.updated_at = updateReport?.updated_at || stockDataMeta?.updated_at || "";
  }
  if (!state.themeTop5.date) {
    state.themeTop5.date = updateReport?.date || stockDataMeta?.date || "";
  }
}

async function loadRadarData() {
  const [radarLatest, marketLatest, themesLatest, newsLatest, updateLog] = await Promise.all([
    loadJson("data/radar-latest.json", null),
    loadJson("data/market-latest.json", null),
    loadJson("data/themes-latest.json", null),
    loadJson("data/news-latest.json", null),
    loadJson("data/update-log.json", null),
  ]);
  let radarItems = latestItems(radarLatest);
  if (!radarItems.length) {
    const stocksLegacy = await loadJson("data/stocks-latest.json", []);
    radarItems = Array.isArray(stocksLegacy) ? stocksLegacy : latestItems(stocksLegacy);
  }
  state.stocks = radarItems;
  state.news = latestItems(newsLatest);
  state.newsLatestMeta = latestMeta(newsLatest);
  state.hotThemes = normalizeDashboardData(themesLatest);
  if (themesLatest?.items?.length) {
    state.themeTop5 = normalizeDashboardData(themesLatest);
  } else {
    state.themeTop5 = normalizeDashboardData(await loadJson("data/theme-top5.json", null));
  }
  state.updateLog = updateLog && typeof updateLog === "object" ? { ...updateLog, available: true } : { entries: [], available: false };
  state.latestUpdate = latestMeta(radarLatest);
  state.universeCount = Number(radarLatest?.universe_count || 0);
  mergeLatestMeta(radarLatest, marketLatest, themesLatest, newsLatest, updateLog);
}

function stockByCode(code) {
  return state.stocks.find((stock) => normalizeCode(stock.code) === normalizeCode(code));
}

function masterRecord(code) {
  const record = state.master[normalizeCode(code)];
  if (!record) return null;
  if (typeof record === "string") {
    return { name: record, market: "", industry: "" };
  }
  return {
    name: record.name || record.stock_name || record["股票名稱"] || "",
    market: record.market || record["市場"] || "",
    industry: record.industry || record.industry_code || record["產業別"] || "",
    source_date: record.source_date || record.updated_at || record.date || "",
  };
}

function masterName(code) {
  return masterRecord(code)?.name || "";
}

function knownStock(code) {
  return Boolean(masterName(code));
}

function displayStockName(code) {
  const normalized = normalizeCode(code);
  return masterName(normalized) || "名稱待補";
}

function resolveStockQuery(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const codeCandidate = normalizeCode(raw);
  if (/^\d{4}$/.test(codeCandidate)) return codeCandidate;
  const embeddedCode = raw.match(/(\d{4})/);
  if (embeddedCode) return embeddedCode[1];
  const normalizedName = raw.toLowerCase();
  const masterEntries = Object.keys(state.master || {}).map((code) => {
    const record = masterRecord(code);
    return { code: normalizeCode(code), name: String(record?.name || "").trim() };
  }).filter((item) => item.code && item.name);
  const exact = masterEntries.find((item) => item.name.toLowerCase() === normalizedName);
  if (exact) return exact.code;
  const starts = masterEntries.find((item) => item.name.toLowerCase().startsWith(normalizedName));
  if (starts) return starts.code;
  const partial = masterEntries.find((item) => item.name.toLowerCase().includes(normalizedName));
  if (partial) return partial.code;
  const stockMatch = state.stocks.find((stock) => String(stock.name || "").toLowerCase().includes(normalizedName));
  return stockMatch ? normalizeCode(stockMatch.code) : "";
}

function industryLabel(value) {
  const raw = cleanDisplay(value);
  if (raw === "—") return "產業待補";
  const code = /^\d+$/.test(raw) ? raw.padStart(2, "0") : "";
  if (code && TWSE_INDUSTRY_LABELS[code]) return TWSE_INDUSTRY_LABELS[code];
  return raw;
}

function formatMasterDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const roc = raw.match(/^(\d{3})(\d{2})(\d{2})$/);
  if (roc) return `${Number(roc[1]) + 1911}-${roc[2]}-${roc[3]}`;
  return raw;
}

function stockUpdateText(stock, record) {
  return cleanDisplay(stock?.updated_at || stock?.data_version || stock?.market_date || formatMasterDate(record?.source_date));
}

function stockMarketTradeDate(stock) {
  return cleanDisplay(stock?.market_date || stock?.quote_date || stock?.date);
}

function stockMarketUpdateText(stock) {
  const meta = state.latestUpdate || {};
  const updated = formatDashboardTime(meta.updated_at || stock?.updated_at || "");
  const stage = meta.stage_label || meta.stage || "";
  const schedule = meta.schedule_time || "";
  const parts = [];
  if (updated) parts.push(updated);
  if (stage) parts.push(stage);
  if (schedule) parts.push(`排程 ${schedule}`);
  return parts.length ? parts.join("｜") : stockMarketTradeDate(stock);
}

function stockDataVersionText(stock) {
  const revenueMonth = String(stock?.revenue_month || "").trim();
  if (revenueMonth) return `營收 ${revenueMonth}`;
  const dataVersion = cleanDisplay(stock?.data_version);
  return dataVersion === "—" ? "資料版本待補" : dataVersion.replace(/｜行情.*$/, "");
}

function stockLabel(code) {
  const normalized = normalizeCode(code);
  return `${normalized} ${displayStockName(normalized)}`;
}

function conceptIncludes(stock, keywords) {
  const text = `${stock?.concept || ""} ${stock?.business || ""} ${stock?.reason || ""}`.toUpperCase();
  return keywords.some((keyword) => text.includes(String(keyword).toUpperCase()));
}

function isTechStock(stock) {
  return conceptIncludes(stock, TECH_THEMES);
}

function isNonTechStock(stock) {
  return conceptIncludes(stock, NON_TECH_THEMES) && !isTechStock(stock);
}

let radarClassifierInstance = null;

function radarClassifier() {
  if (!radarClassifierInstance) {
    const factory = globalThis.AsuradaStockClassifier?.createStockClassifier;
    if (!factory) throw new Error("stockClassifier.js 尚未載入");
    radarClassifierInstance = factory({
      getMasterRecord: masterRecord,
      getStockName: displayStockName,
      themeTaxonomy,
    });
  }
  return radarClassifierInstance;
}

function getIndustryName(stock) {
  return radarClassifier().getIndustryName(stock);
}

function getRadarPool(stock) {
  return radarClassifier().getRadarPool(stock);
}

function inferThemeTags(stock) {
  return radarClassifier().inferThemeTags(stock);
}

function radarScoreValue(stock) {
  return evidenceNumber(stock?.score_value ?? stock?.score) ?? Number.NEGATIVE_INFINITY;
}

function compareRadarPoolStocks(a, b) {
  return radarScoreValue(b) - radarScoreValue(a) || toNumber(a.rank) - toNumber(b.rank);
}

function buildRadarPoolLists(stocks = state.stocks) {
  const officialStocks = stocks.filter(officialRankEligible);
  const electronicTechTop30 = officialStocks.filter((stock) => getRadarPool(stock) === "electronicTechPool").sort(compareRadarPoolStocks).slice(0, 30);
  const nonElectronicTop30 = officialStocks.filter((stock) => getRadarPool(stock) === "nonElectronicPool").sort(compareRadarPoolStocks).slice(0, 30);
  const rank = (list) => list.map((stock, index) => ({ ...stock, display_rank: index + 1 }));
  const combinedTop60 = [...electronicTechTop30, ...nonElectronicTop30].sort(compareRadarPoolStocks).slice(0, 60);
  const dataGapPool = stocks.filter((stock) => !officialRankEligible(stock)).sort(compareRadarPoolStocks).slice(0, 60);
  return {
    electronicTechPool: rank(electronicTechTop30),
    nonElectronicPool: rank(nonElectronicTop30),
    combinedPool: rank(combinedTop60),
    dataGapPool: rank(dataGapPool),
  };
}

function eventCodes() {
  return new Set(state.news.flatMap((event) => event.related_stocks || []).map(normalizeCode));
}

function isRealSourceUrl(url) {
  try {
    const raw = String(url || "").trim();
    if (!raw || raw === "#" || /example\.com|demo|test/i.test(raw)) return false;
    const parsed = new URL(raw);
    if (!["http:", "https:"].includes(parsed.protocol)) return false;
    if (!parsed.hostname || /example\.com|localhost|127\.0\.0\.1/i.test(parsed.hostname)) return false;
    return true;
  } catch {
    return false;
  }
}

function eventUrl(event) {
  return event?.source_url || event?.url || "";
}

function formatDate(value) {
  const text = String(value || "");
  return text.includes("T") ? text.slice(0, 10) : (text || "日期未標示");
}

function radarModeInfo(stock, mode = "main") {
  const score = toNumber(stock.score);
  const volume = toNumber(stock.volume);
  const dailyChange = toNumber(stock.daily_change);
  const isConstruction = conceptIncludes(stock, constructionThemes);
  const isFinance = conceptIncludes(stock, financeThemes);
  const isDefensive = isConstruction || isFinance;
  const isMainTheme = isTechStock(stock);
  const penalty = Math.max(isConstruction ? 10 : 0, isFinance ? 15 : 0);
  const cancelPenalty = volume > 3000 || eventCodes().has(normalizeCode(stock.code)) || dailyChange > 3;
  const downgraded = mode === "main" && isDefensive && penalty > 0 && !cancelPenalty;
  return {
    isMainTheme,
    isDefensive,
    downgraded,
    displayScore: downgraded ? Math.max(0, score - penalty) : score,
  };
}

function sortedStocks(mode = "main", input = state.stocks) {
  const list = [...input];
  if (mode === "tech") {
    return list.filter(isTechStock).sort((a, b) => toNumber(a.rank) - toNumber(b.rank));
  }
  if (mode === "nontech") {
    return list.filter(isNonTechStock).sort((a, b) => toNumber(a.rank) - toNumber(b.rank));
  }
  if (mode === "defensive") {
    return list
      .filter((stock) => radarModeInfo(stock, mode).isDefensive)
      .sort((a, b) =>
        toNumber(b.score) - toNumber(a.score) ||
        toNumber(b.volume) - toNumber(a.volume) ||
        toNumber(b.revenue_yoy) - toNumber(a.revenue_yoy) ||
        toNumber(b.revenue_mom) - toNumber(a.revenue_mom) ||
        toNumber(a.rank) - toNumber(b.rank)
      );
  }
  if (mode === "market") {
    return list.sort((a, b) => toNumber(a.rank) - toNumber(b.rank));
  }
  return list.sort((a, b) => {
    const ai = radarModeInfo(a, mode);
    const bi = radarModeInfo(b, mode);
    return Number(bi.isMainTheme) - Number(ai.isMainTheme) || bi.displayScore - ai.displayScore || toNumber(a.rank) - toNumber(b.rank);
  });
}

function chip(text, tone = "") {
  return `<span class="chip ${tone}">${escapeHtml(text)}</span>`;
}

function stockChips(codes, emptyText = "無") {
  const normalized = (codes || []).map(normalizeCode).filter(Boolean);
  if (!normalized.length) return chip(emptyText);
  return normalized.map((code) => {
    const label = stockLabel(code);
    if (!masterName(code)) {
      return chip(label);
    }
    return `<a class="chip stock-link" href="stock.html?code=${encodeURIComponent(code)}">${escapeHtml(label)}</a>`;
  }).join("");
}

function externalLinks(code) {
  const safeCode = encodeURIComponent(normalizeCode(code));
  const normalized = normalizeCode(code);
  if (!normalized) return "";
  const links = [
    ["CMoney 概覽", `https://www.cmoney.tw/finance/${safeCode}/f00025`],
    ["Yahoo 股市", `https://tw.stock.yahoo.com/quote/${safeCode}.TW`],
    ["PChome 股市", `https://pchome.megatime.com.tw/stock/sto0/ock1/sid${normalized}.html`],
  ];
  return `<div class="button-row">${links.map(([label, href]) => `<a class="solid-link" href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`).join("")}</div>`;
}

function cleanDisplay(value) {
  if (value === null || value === undefined) return "—";
  const text = String(value).trim();
  if (!text || text === "undefined" || text === "null" || text === "NaN") return "—";
  return text;
}

function infoItem(label, value, extra = "") {
  return `
    <div class="info-item ${extra}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(cleanDisplay(value))}</strong>
    </div>
  `;
}

function infoHtmlItem(label, html, extra = "") {
  return `
    <div class="info-item ${extra}">
      <span>${escapeHtml(label)}</span>
      <strong>${html || "—"}</strong>
    </div>
  `;
}

function infoBadge(label, value, tone = "") {
  return `
    <div class="info-item">
      <span>${escapeHtml(label)}</span>
      <strong>${chip(cleanDisplay(value), tone)}</strong>
    </div>
  `;
}

function radarScore(stock, mode = "main") {
  const info = radarModeInfo(stock, mode);
  const score = Number.isFinite(info.displayScore) ? `${info.displayScore.toFixed(0)}分` : "-";
  return `${stock.rating || "-"} / ${score}`;
}

function matchesRating(stock, rating) {
  if (!rating) return true;
  const stockRating = String(stock.rating || "").trim();
  if (rating === "A") return stockRating === "A" || stockRating === "A-";
  if (rating === "C") return stockRating === "C" || stockRating === "觀察";
  return stockRating === rating;
}

function revenueMonthText(stock) {
  const candidates = [stock?.revenue_month, stock?.data_version];
  for (const value of candidates) {
    const match = String(value || "").match(/(\d{4})-(\d{1,2})/);
    if (match) return `${Number(match[2])}月`;
  }
  return "當月份";
}

function revenueLabels(stock) {
  const month = revenueMonthText(stock);
  return {
    current: "當月營收(百萬)",
    mom: `月增率(${month})`,
    yoy: `年增率(${month})`,
  };
}

function revenueAmount(stock) {
  return stock?.current_revenue_million ?? stock?.current_revenue ?? "-";
}

function evidenceNumber(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(String(value).replace(/,/g, "").replace(/%/g, ""));
  return Number.isFinite(number) ? number : null;
}

function evidencePercent(value) {
  const number = evidenceNumber(value);
  return number === null ? null : `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function isLowBaseWatch(stock) {
  const yoy = evidenceNumber(stock?.revenue_yoy_value);
  const mom = evidenceNumber(stock?.revenue_mom_value);
  const notes = `${stock?.reason || ""} ${stock?.risk_tags || ""}`;
  return (yoy !== null && mom !== null && yoy > 100 && mom <= 0)
    || notes.includes("低基期")
    || notes.includes("月增轉弱");
}

function evidenceRevenue(stock) {
  const month = String(stock?.revenue_month || "").trim();
  const revenue = evidenceNumber(stock?.current_revenue_million);
  const mom = evidencePercent(stock?.revenue_mom_value);
  const yoy = evidencePercent(stock?.revenue_yoy_value);
  if (!/^\d{4}-\d{2}$/.test(month) || revenue === null || mom === null || yoy === null) return "營收資料不足";
  return `${month} 月營收 ${revenue.toFixed(2)} 百萬，月增 ${mom}，年增 ${yoy}`;
}

function evidenceVolume(stock) {
  if (!officialRankEligible(stock)) return priceStatusLine(stock);
  const volume = evidenceNumber(stock?.volume_value);
  if (volume === null) return "成交量資料不足";
  const amount = Math.round(volume).toLocaleString("zh-TW");
  return volume >= 3000 ? `成交量 ${amount} 張，符合量能門檻` : "成交量不足 3000 張";
}

function evidenceTheme(stock) {
  const industryName = getIndustryName(stock);
  const tags = inferThemeTags(stock);
  if (!tags.length && !industryName) return "題材分類不足，需補資料";
  return `${industryName ? `產業：${industryName}` : "產業待補"}${tags.length ? `；題材：${tags.join("、")}` : ""}`;
}

const SIGNAL_STATUS_LABELS = {
  verified: "已驗證",
  estimated: "推估",
  manual: "手動",
  missing: "缺資料",
  fallback: "fallback，不列入正式排名",
  unknown: "推估或手動，來源待確認",
};

const TRUST_LEVEL_LABELS = {
  high: "資料完整",
  medium: "部分推估",
  low: "資料缺口",
};

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object || {}, key);
}

function isMissingSignalValue(value) {
  if (value === null || value === undefined) return true;
  const text = String(value).trim();
  return !text || ["-", "undefined", "null", "nan"].includes(text.toLowerCase());
}

function isPositiveSignalValue(value) {
  if (isMissingSignalValue(value)) return false;
  const text = String(value).trim().toLowerCase();
  if (["true", "1", "yes", "y", "是"].includes(text)) return true;
  if (["false", "0", "no", "n", "否"].includes(text)) return false;
  const number = evidenceNumber(value);
  return number !== null && number !== 0;
}

function signalStatus(stock, statusField, valueFields, allowedStatuses) {
  const rawStatus = String(stock?.[statusField] || "").trim().toLowerCase();
  if (allowedStatuses.includes(rawStatus)) return rawStatus;
  const existingValueField = valueFields.find((field) => hasOwn(stock, field));
  if (!existingValueField) return "missing";
  return isPositiveSignalValue(stock[existingValueField]) ? "unknown" : "missing";
}

function priceSourceStatus(stock) {
  const rawStatus = String(stock?.price_source_status || "").trim().toLowerCase();
  if (rawStatus === "verified") return hasVerifiedMarketDate(stock) ? "verified" : "fallback";
  if (["fallback", "missing"].includes(rawStatus)) return rawStatus;
  const rawSource = String(stock?.price_source || stock?.price_data_source || "").trim().toLowerCase();
  if (/fallback|simulated|generated|mock/.test(rawSource)) return "fallback";
  if (isMissingSignalValue(stock?.close)) return "missing";
  return hasVerifiedMarketDate(stock) ? "verified" : "fallback";
}

function hasVerifiedMarketDate(stock) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(stock?.market_date || "").trim());
}

function officialRankEligible(stock) {
  if (priceSourceStatus(stock) !== "verified" || !hasVerifiedMarketDate(stock)) return false;
  if (hasOwn(stock, "official_rank_eligible")) {
    const value = stock.official_rank_eligible;
    if (typeof value === "boolean") return value;
    const text = String(value || "").trim().toLowerCase();
    return ["true", "1", "yes", "y"].includes(text);
  }
  return true;
}

function priceStatusLine(stock) {
  const status = priceSourceStatus(stock);
  const source = cleanDisplay(stock?.price_source || stock?.price_data_source || stock?.data_source || "-");
  const date = cleanDisplay(stock?.market_date);
  if (status === "verified") return `價格資料：${source}${date !== "-" ? `，市場日期 ${date}` : ""}`;
  if (status === "fallback") return "價格資料缺漏：fallback，不列入正式排名";
  return "價格資料缺漏";
}

function displayClose(stock) {
  return officialRankEligible(stock) ? cleanDisplay(stock?.close) : "價格資料缺漏";
}

function displayVolume(stock) {
  return officialRankEligible(stock) ? cleanDisplay(stock?.volume) : "價格資料缺漏";
}

function displayVolumeLots(stock) {
  if (!officialRankEligible(stock)) return "價格資料缺漏";
  const volume = toNumber(stock?.volume_value ?? stock?.volume);
  if (Number.isFinite(volume)) return `${dashboardNumber(volume, 0)} 張`;
  const fallback = cleanDisplay(stock?.volume);
  return fallback === "—" ? "資料待補" : `${fallback} 張`;
}

function displayChangePercent(stock) {
  if (!officialRankEligible(stock)) return "價格資料缺漏";
  const candidates = [
    stock?.change_percent,
    stock?.change_pct,
    stock?.daily_change,
    stock?.daily_change_pct,
    stock?.price_change_pct,
  ];
  for (const value of candidates) {
    const text = String(value ?? "").trim();
    if (!text || text === "-" || text === "—") continue;
    const number = toNumber(value);
    if (Number.isFinite(number)) return dashboardPercent(number);
    return cleanDisplay(value);
  }
  return "資料待補";
}

function latestRevenueAmountLabel(stock) {
  const month = revenueMonthText(stock);
  return month && month !== "當月份" ? `最新月份(${month})營收(百萬)` : "最新月份營收(百萬)";
}

function trustInfo(stock) {
  const signals = [
    {
      key: "eps",
      label: "EPS",
      status: signalStatus(stock, "eps_signal_status", ["eps_signal", "eps_turnaround", "eps_turnaround_signal"], ["verified", "estimated", "manual", "missing"]),
    },
    {
      key: "gross",
      label: "毛利率",
      status: signalStatus(stock, "gross_margin_signal_status", ["gross_margin_signal", "gross_margin_improvement"], ["verified", "estimated", "manual", "missing"]),
    },
    {
      key: "target",
      label: "法人目標",
      status: signalStatus(stock, "institutional_target_status", ["institutional_target_signal", "institutional_target_revision"], ["verified", "manual", "missing"]),
    },
    {
      key: "price",
      label: "價量",
      status: priceSourceStatus(stock),
    },
  ];
  const statuses = signals.map((signal) => signal.status);
  const explicitLevel = String(stock?.data_confidence_level || "").trim().toLowerCase();
  const level = ["high", "medium", "low"].includes(explicitLevel)
    ? explicitLevel
    : (statuses.includes("missing") || statuses.includes("fallback") ? "low" : statuses.includes("estimated") || statuses.includes("manual") || statuses.includes("unknown") ? "medium" : "high");
  const explicitReasons = Array.isArray(stock?.data_confidence_reasons)
    ? stock.data_confidence_reasons.map((reason) => String(reason || "").trim()).filter(Boolean)
    : [];
  const reasons = explicitReasons.length
    ? explicitReasons
    : signals
        .filter((signal) => signal.status !== "verified")
        .map((signal) => `${signal.label}：${SIGNAL_STATUS_LABELS[signal.status] || SIGNAL_STATUS_LABELS.unknown}`);
  return { level, signals, reasons };
}

function trustBadge(stock) {
  const info = trustInfo(stock);
  const label = TRUST_LEVEL_LABELS[info.level] || TRUST_LEVEL_LABELS.low;
  return `<span class="trust-badge trust-${escapeHtml(info.level)}">${escapeHtml(label)}</span>`;
}

function trustSourceLine(stock) {
  return trustInfo(stock).signals
    .map((signal) => `${signal.label}：${SIGNAL_STATUS_LABELS[signal.status] || SIGNAL_STATUS_LABELS.unknown}`)
    .join("；");
}

function trustReasonText(stock) {
  const reasons = trustInfo(stock).reasons;
  return reasons.length ? reasons.join("；") : "資料來源狀態完整";
}

const TRANSPARENT_RADAR_NAMES = {
  mid: "中線主升段",
  short: "短線爆發",
  long: "長線核心",
  revenue: "營收轉強",
  lowbase: "低基期觀察",
};

function radarRuleChecks(stock, radarMode) {
  const yoy = evidenceNumber(stock?.revenue_yoy_value);
  const mom = evidenceNumber(stock?.revenue_mom_value);
  const volume = evidenceNumber(stock?.volume_value);
  const revenue = evidenceNumber(stock?.current_revenue_million);
  const score = evidenceNumber(stock?.score_value);
  const listed = String(stock?.market || "").trim() === "上市";
  const lowBase = isLowBaseWatch(stock);
  if (radarMode === "short") return [
    [listed, "上市"],
    [volume !== null && volume >= 3000, "量能≥3000張"],
    [(yoy !== null && yoy > 30) || (mom !== null && mom > 20), "年增>30%或月增>20%"],
    [score !== null && score >= 50, "原始排序分數≥50"],
  ];
  if (radarMode === "long") return [
    [listed, "上市"],
    [yoy !== null && yoy > 20, "年增>20%"],
    [revenue !== null && revenue >= 1000, "月營收≥1000百萬"],
    [!lowBase, "非低基期觀察"],
  ];
  if (radarMode === "revenue") return [
    [yoy !== null && yoy > 30, "年增>30%"],
    [mom !== null && mom > 0, "月增>0%"],
  ];
  if (radarMode === "lowbase") return [
    [lowBase, "高年增月增轉弱、低基期或月增轉弱標籤"],
  ];
  return [
    [listed, "上市"],
    [isTechStock(stock), "電子"],
    [yoy !== null && yoy > 30, "年增>30%"],
    [mom !== null && mom > 0, "月增>0%"],
    [volume !== null && volume >= 1000, "量能>1000張"],
    [!lowBase, "非低基期觀察"],
  ];
}

function evidenceMatchedRules(stock, radarMode) {
  const checks = radarRuleChecks(stock, radarMode);
  const matched = checks.filter(([passed]) => passed).map(([, label]) => label);
  const base = `命中 ${matched.length} / ${checks.length}${matched.length ? `：${matched.join("、")}` : ""}`;
  if (radarMode === "short") return `${base}。短線資料仍缺完整漲跌幅與即時量價，目前僅為初步觀察。`;
  if (radarMode === "long") return `${base}。長線資料仍缺 EPS、毛利率、估值，目前僅為初步觀察。`;
  return base;
}

function warningReason(stock) {
  const warnings = [];
  const yoy = evidenceNumber(stock?.revenue_yoy_value);
  const mom = evidenceNumber(stock?.revenue_mom_value);
  const volume = evidenceNumber(stock?.volume_value);
  const concept = String(stock?.concept || "");
  const notes = `${stock?.reason || ""} ${stock?.risk_tags || ""}`;
  if (yoy !== null && mom !== null && yoy > 100 && mom <= 0) warnings.push("年增很高但月增轉弱，可能是低基期或一次性因素");
  else if (notes.includes("低基期")) warnings.push("原始資料標記低基期，需確認成長持續性");
  if (notes.includes("月增轉弱") && !(yoy !== null && mom !== null && yoy > 100 && mom <= 0)) warnings.push("月增轉弱，需確認後續營收是否恢復");
  if (/營建|資產|都更/.test(concept)) warnings.push("營建資產股可能受單月入帳影響，需確認連續性");
  if (/金融|壽險|銀行/.test(concept)) warnings.push("金融股營收結構特殊，需搭配利率、匯率、投資收益確認");
  if (/生技|新藥/.test(concept)) warnings.push("生技股需確認產品進度與獲利能力，營收跳升不一定等於主升段");
  if (volume !== null && volume < 1000) warnings.push("成交量偏低，流動性不足");
  return warnings.length ? warnings.join("；") : "暫無明確警示";
}

function dataGapNote(stock, radarMode) {
  const notes = {
    short: "尚未納入完整即時漲跌幅、漲停、量比與分時資料",
    mid: "尚未納入技術突破、族群同步與法人籌碼",
    long: "尚未納入 EPS、毛利率、估值與季度財報",
    revenue: "此分區只看月營收，尚未確認技術與題材強度",
    lowbase: "此分區為風險觀察，不代表主升段",
  };
  return notes[radarMode] || notes.mid;
}

function matchesTransparentRadar(stock, radarMode) {
  const yoy = evidenceNumber(stock?.revenue_yoy_value);
  const mom = evidenceNumber(stock?.revenue_mom_value);
  const volume = evidenceNumber(stock?.volume_value);
  const revenue = evidenceNumber(stock?.current_revenue_million);
  const listed = String(stock?.market || "").trim() === "上市";
  if (radarMode === "mid") return listed && isTechStock(stock);
  if (radarMode === "short") return listed && volume !== null && volume >= 1000;
  if (radarMode === "long") return listed && revenue !== null && revenue >= 1000;
  if (radarMode === "revenue") return (yoy !== null && yoy > 30) || (mom !== null && mom > 0);
  if (radarMode === "lowbase") return isLowBaseWatch(stock);
  return true;
}

function stockCard(stock, mode = "main", compact = false) {
  const info = radarModeInfo(stock, mode);
  const modeName = mode === "market" ? "全市場" : mode === "defensive" ? "資產防守" : "主升段";
  const labels = revenueLabels(stock);
  return `
    <article class="card stock-card">
      <div class="section-title">
        <h3><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.code)}">#${escapeHtml(stock.rank)} ${escapeHtml(stock.code)} ${escapeHtml(displayStockName(stock.code))}</a></h3>
        <div class="chip-row">${chip(radarScore(stock, mode), "good")}${trustBadge(stock)}</div>
      </div>
      <div class="grid ${compact ? "cols-3" : "cols-4"}">
        <div class="metric"><span>雷達評分</span><strong>${escapeHtml(radarScore(stock, mode))}</strong></div>
        <div class="metric"><span>收盤價</span><strong>${escapeHtml(displayClose(stock))}</strong></div>
        <div class="metric"><span>成交量</span><strong>${escapeHtml(displayVolume(stock))}${officialRankEligible(stock) ? " 張" : ""}</strong></div>
        ${compact ? "" : `<div class="metric"><span>雷達模式</span><strong>${escapeHtml(modeName)}</strong></div>`}
      </div>
      ${info.downgraded ? `<p class="penalty-note">主升段模式降權：族群非當前高動能主流，需等待政策、利率或量價確認。</p>` : ""}
      ${compact ? "" : `
      <div class="grid cols-4">
        <div class="metric"><span>${escapeHtml(labels.current)}</span><strong>${escapeHtml(revenueAmount(stock))}</strong></div>
        <div class="metric"><span>${escapeHtml(labels.mom)}</span><strong>${escapeHtml(stock.revenue_mom)}</strong></div>
        <div class="metric"><span>去年同月營收</span><strong>${escapeHtml(stock.previous_year_revenue)}</strong></div>
        <div class="metric"><span>${escapeHtml(labels.yoy)}</span><strong>${escapeHtml(stock.revenue_yoy)}</strong></div>
      </div>`}
      <p><span class="label">概念股</span>${escapeHtml(stock.concept || "-")}</p>
      <p><span class="label">入選理由</span>${escapeHtml(stock.reason || "-")}</p>
      <p><span class="label">價格資料</span>${escapeHtml(priceStatusLine(stock))}</p>
      <p><span class="label">資料來源狀態</span>${escapeHtml(trustSourceLine(stock))}</p>
      <div class="chip-row">${String(stock.risk_tags || "一般觀察").split("、").map((x) => chip(x)).join("")}</div>
    </article>
  `;
}

function stockTable(stocks, mode = "main", compact = false) {
  if (!stocks.length) return `<div class="empty">沒有符合條件的股票</div>`;
  const labels = revenueLabels(stocks[0]);
  const rows = stocks.map((stock) => {
    const info = radarModeInfo(stock, mode);
    return `
      <tr>
        <td>${escapeHtml(stock.display_rank ?? stock.rank)}</td>
        <td><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.code)}">${escapeHtml(stock.code)}</a></td>
        <td>${escapeHtml(displayStockName(stock.code))}</td>
        <td>${escapeHtml(radarScore(stock, mode))}${info.downgraded ? "<br><span class=\"chip warn\">降權</span>" : ""}</td>
        <td>${escapeHtml(displayClose(stock))}</td>
        <td>${escapeHtml(displayVolume(stock))}</td>
        <td>${escapeHtml(revenueAmount(stock))}</td>
        <td>${escapeHtml(stock.revenue_mom)}</td>
        <td>${escapeHtml(stock.revenue_yoy)}</td>
        <td>${escapeHtml(stock.concept)}</td>
        <td>${escapeHtml(stock.reason)}</td>
        <td>${escapeHtml(stock.risk_tags || "一般觀察")}</td>
      </tr>
    `;
  }).join("");
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>排名</th><th>股票代號</th><th>股票名稱</th><th>雷達評分</th><th>收盤價</th><th>成交量</th><th>${escapeHtml(labels.current)}</th><th>${escapeHtml(labels.mom)}</th><th>${escapeHtml(labels.yoy)}</th><th>概念股</th><th>入選理由</th><th>風險標籤</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function radarEvidenceTable(stocks, mode = "mid") {
  if (!stocks.length) return `<div class="empty">沒有符合條件的股票</div>`;
  const rows = stocks.map((stock) => {
    const score = evidenceNumber(stock.score_value);
    const scoreHint = score === null ? "原始分數未標示" : `原始分數：${score.toFixed(0)}，僅供排序參考，不作為單一判斷依據。`;
    const matchedText = evidenceMatchedRules(stock, mode);
    const revenueText = evidenceRevenue(stock);
    const volumeText = evidenceVolume(stock);
    const themeText = evidenceTheme(stock);
    const warningText = warningReason(stock);
    const gapText = dataGapNote(stock, mode);
    const sourceText = `資料來源狀態：${trustSourceLine(stock)}。${priceStatusLine(stock)}。${gapText}`;
    const trustText = trustReasonText(stock);
    return `
      <tr title="${escapeHtml(scoreHint)}">
        <td class="cell-nowrap cell-number" data-label="排名">${escapeHtml(stock.display_rank ?? stock.rank)}</td>
        <td class="cell-nowrap" data-label="股票代號"><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.code)}">${escapeHtml(stock.code)}</a></td>
        <td class="cell-nowrap" data-label="股票名稱">${escapeHtml(displayStockName(stock.code))}</td>
        <td class="cell-nowrap" data-label="雷達分區"><span class="evidence-section">${getRadarPool(stock) === "nonElectronicPool" ? "非電子防守" : "電子 / AI科技"}</span></td>
        <td class="cell-nowrap" data-label="資料可信度" title="${escapeHtml(trustText)}">${trustBadge(stock)}</td>
        <td class="cell-reason" data-label="條件命中" title="${escapeHtml(matchedText)}"><span class="cell-clamp">${escapeHtml(matchedText)}</span></td>
        <td class="cell-reason" data-label="營收證據" title="${escapeHtml(revenueText)}"><span class="cell-clamp">${escapeHtml(revenueText)}</span></td>
        <td class="cell-nowrap cell-number" data-label="量能證據" title="${escapeHtml(volumeText)}">${escapeHtml(volumeText)}</td>
        <td class="cell-theme" data-label="題材證據" title="${escapeHtml(themeText)}"><span class="cell-clamp">${escapeHtml(themeText)}</span></td>
        <td class="cell-reason" data-label="警示原因" title="${escapeHtml(warningText)}"><span class="cell-clamp">${escapeHtml(warningText)}</span></td>
        <td class="cell-reason" data-label="資料來源狀態" title="${escapeHtml(sourceText)}"><span class="cell-clamp">${escapeHtml(sourceText)}</span></td>
      </tr>
    `;
  }).join("");
  return `
    <div class="table-wrap radar-evidence-wrap radar-table-wrap">
      <table class="radar-evidence-table radar-table">
        <thead><tr><th>排名</th><th>股票代號</th><th>股票名稱</th><th>雷達分區</th><th>資料可信度</th><th>條件命中</th><th>營收證據</th><th>量能證據</th><th>題材證據</th><th>警示原因</th><th>資料來源狀態</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function stockRadarDetail(stock) {
  const labels = revenueLabels(stock);
  const rows = [
    ["資料版本", stockDataVersionText(stock)],
    ["行情更新時間", stockMarketUpdateText(stock)],
    ["市場交易日", stockMarketTradeDate(stock)],
    ["AI選股排名", stock.rank],
    ["AI觀察分數", radarScore(stock, "market")],
    ["收盤價", displayClose(stock)],
    ["漲幅%", displayChangePercent(stock)],
    ["成交量", displayVolumeLots(stock)],
    [latestRevenueAmountLabel(stock), revenueAmount(stock)],
    [labels.mom, stock.revenue_mom],
    [labels.yoy, stock.revenue_yoy],
  ];
  return `
    <div class="stock-info-card">
      <h3>價格與資料狀態</h3>
      <div class="chip-row trust-row">${trustBadge(stock)}</div>
      <div class="stock-info-grid">
        ${rows.map(([label, value]) => infoItem(label, value)).join("")}
      </div>
      <div class="stock-notes">
        <p><span class="label">價格資料</span>${escapeHtml(priceStatusLine(stock))}</p>
        <p><span class="label">資料來源狀態</span>${escapeHtml(trustSourceLine(stock))}</p>
        <p><span class="label">資料可信度說明</span>${escapeHtml(trustReasonText(stock))}</p>
      </div>
    </div>
  `;
}

function stockConceptPayload(code) {
  const records = state.stockConcepts?.stocks || {};
  return records[normalizeCode(code)] || null;
}

function stockConceptItems(code) {
  const payload = stockConceptPayload(code);
  const concepts = Array.isArray(payload?.concepts) ? payload.concepts : [];
  return concepts.filter((item) => item && item.concept_name);
}

function stockConceptNames(code, limit = 12) {
  const items = stockConceptItems(code);
  return items.slice(0, limit).map((item) => item.concept_name);
}

function stockConceptLinks(code, limit = 12) {
  const items = stockConceptItems(code);
  if (!items.length) return "—";
  const links = items.slice(0, limit).map((item) => {
    const name = item.concept_name || "";
    const href = item.source_url || `concepts.html?q=${encodeURIComponent(name)}`;
    return `<a class="stock-link" href="${escapeHtml(href)}" target="${item.source_url ? "_blank" : "_self"}" rel="noopener">${escapeHtml(name)}</a>`;
  });
  const extra = items.length > limit ? ` <span class="muted">另 ${items.length - limit} 項</span>` : "";
  return `${links.join("、")}${extra}`;
}

function stockConceptSourceText(code) {
  const payload = stockConceptPayload(code);
  if (!payload) return "概念資料待補";
  const count = payload.concept_count ?? stockConceptItems(code).length;
  const updated = state.stockConcepts?.updated_at || "";
  return `MoneyDJ 主資料庫反查 ${count} 項${updated ? `｜更新 ${formatDashboardTime(updated)}` : ""}`;
}

function stockMasterDetail(code, stock) {
  const record = masterRecord(code);
  const status = stock ? "命中今日雷達" : "今日未入選雷達";
  const industry = industryLabel(record?.industry || stock?.industry || stock?.category);
  const conceptNames = stockConceptNames(code, 6);
  const supplyChain = stock ? cleanDisplay(stock.business || stock.concept) : cleanDisplay(conceptNames.slice(0, 4).join("、") || industry);
  const relatedThemes = stockConceptLinks(code, 14);
  return `
    <div class="stock-info-card">
      <h3>基本資料</h3>
      <div class="stock-info-grid">
        ${infoItem("股票代號", normalizeCode(code))}
        ${infoItem("股票名稱", record?.name || "名稱待補")}
        ${infoItem("市場別", record?.market)}
        ${infoItem("產業別", industry)}
        ${infoItem("類股 / 供應鏈", supplyChain)}
        ${infoHtmlItem("概念股相關", relatedThemes)}
        ${infoItem("概念資料來源", stockConceptSourceText(code))}
        ${infoBadge("今日雷達狀態", status, stock ? "good" : "warn")}
      </div>
    </div>
  `;
}

function eventCard(event) {
  const holdings = new Set(readStoredCodes(HOLDINGS_KEY));
  const related = (event.related_stocks || []).map(normalizeCode).filter(Boolean);
  const radarHits = related.filter((code) => stockByCode(code));
  const holdingHits = related.filter((code) => holdings.has(code));
  const impactTone = event.impact === "偏多" ? "good" : event.impact === "偏空" ? "bad" : "";
  const url = eventUrl(event);
  return `
    <article class="card news-card" data-region="${escapeHtml(event.region || "")}" data-category="${escapeHtml(event.category || "")}" data-holding-hit="${holdingHits.length ? "1" : "0"}">
      <div class="chip-row">
        ${chip(formatDate(event.date))}
        ${chip(event.region || "地區未標示")}
        ${chip(`題材：${event.category || "未分類"}`)}
        ${chip(`事件強度：${event.event_strength || "未標示"}`, event.event_strength === "高" ? "warn" : "")}
        ${chip(`影響方向：${event.impact || "中性"}`, impactTone)}
      </div>
      <h3>${escapeHtml(event.title || "未命名事件")}</h3>
      <p><span class="label">新聞摘要</span>${escapeHtml(event.summary || event.logic || "尚無摘要")}</p>
      <p class="analysis"><span class="label">題材連動分析</span>${escapeHtml(event.asurada_analysis || event.logic || "尚無連動分析")}</p>
      <p><span class="label">相關台股代號與名稱</span></p>
      <div class="chip-row">${stockChips(related, "無相關台股")}</div>
      <p><span class="label">雷達命中</span></p>
      <div class="chip-row">${stockChips(radarHits, "未命中今日雷達")}</div>
      <p><span class="label">持股命中</span></p>
      <div class="chip-row">${stockChips(holdingHits, "未命中我的持股")}</div>
      ${isRealSourceUrl(url) ? `<a class="solid-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">查看來源</a>` : `<span class="chip">來源待補</span>`}
    </article>
  `;
}

function newsListHtml(events, emptyText = "目前沒有相關新聞") {
  const validEvents = (events || []).filter((event) => isRealSourceUrl(eventUrl(event)));
  if (!validEvents.length) return `<div class="empty">${escapeHtml(emptyText)}</div>`;
  return `
    <ol class="news-list">
      ${validEvents.map((event) => {
        const url = eventUrl(event);
        return `
          <li>
            <a class="stock-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(event.title || "未命名新聞")}</a>
            <div class="muted">來源：${escapeHtml(event.source_name || "來源未標示")}｜日期：${escapeHtml(formatDate(event.date))}｜題材：${escapeHtml(event.category || "未分類")}｜影響：${escapeHtml(event.impact || "中性")}</div>
            ${event.summary ? `<p>${escapeHtml(event.summary)}</p>` : ""}
            ${event.asurada_analysis ? `<p class="analysis">${escapeHtml(event.asurada_analysis)}</p>` : ""}
            <p><span class="label">分析相關股票</span></p><div class="chip-row">${stockChips(event.related_stocks || [], "無相關股票")}</div>
            <a class="solid-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">查看新聞</a>
          </li>
        `;
      }).join("")}
    </ol>
  `;
}

function externalSearchLinks(keyword) {
  const q = encodeURIComponent(keyword || "");
  const links = [
    ["Yahoo 股市搜尋", `https://tw.stock.yahoo.com/search/result?q=${q}`],
    ["鉅亨網搜尋", `https://news.cnyes.com/search/all?keyword=${q}`],
    ["MoneyDJ 搜尋", `https://www.moneydj.com/kmdj/search/list.aspx?_Query_=${q}`],
    ["CMoney 搜尋", `https://www.cmoney.tw/notes/?q=${q}`],
  ];
  return `<div class="button-row">${links.map(([label, href]) => `<a class="solid-link" href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`).join("")}</div>`;
}

function conceptEntries() {
  return Object.entries(state.concepts || {}).map(([key, concept]) => ({
    name: concept.concept_name || concept.theme_name || concept.name || key,
    theme_name: concept.concept_name || concept.theme_name || concept.name || key,
    group: concept.group || "全部概念",
    aliases: concept.aliases || [],
    keywords: concept.keywords || [],
    description: concept.description || "",
    related_stocks: concept.related_stocks || [],
    source_links: concept.source_links || [],
    source_status: concept.source_status || "來源狀態未標示",
  }));
}

function conceptMatches(concept, query, group = "全部概念") {
  if (group && group !== "全部概念" && concept.group !== group) return false;
  if (!query) return true;
  const text = [concept.name, concept.group, concept.description, ...(concept.aliases || []), ...(concept.keywords || [])].join(" ").toLowerCase();
  return text.includes(query.toLowerCase());
}

function renderHeader(active) {
  const nav = [
    ["index.html", "首頁", "index"],
    ["radar.html", "AI選股", "radar"],
    ["concepts.html", "產業題材庫", "concepts"],
    ["news.html", "重大新聞", "news"],
    ["stock.html", "個股概覽", "stock"],
    ["portfolio.html", "持股追蹤", "portfolio"],
  ];
  const el = $("#siteHeader");
  if (!el) return;
  el.innerHTML = `
    <div class="site-header">
      <h1>霆隼AI選股網</h1>
      <p>台股題材研究與候選股整理平台</p>
      <nav class="nav">${nav.map(([href, label, key]) => `<a class="${active === key ? "active" : ""}" href="${href}">${label}</a>`).join("")}</nav>
      ${siteVersionMiniHtml()}
    </div>
  `;
}

function renderError(target, message) {
  const el = typeof target === "string" ? $(target) : target;
  if (el) el.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
}

function nonTechEventStocks() {
  const holdings = new Set([...readStoredCodes(HOLDINGS_KEY), ...readStoredCodes(WATCHLIST_KEY)]);
  return state.stocks.filter((stock) => {
    if (!isNonTechStock(stock)) return false;
    const code = normalizeCode(stock.code);
    const hasEvent = eventCodes().has(code);
    const isHighEvent = state.news.some((event) => event.event_strength === "高" && (event.related_stocks || []).map(normalizeCode).includes(code));
    const isHeavyVolume = toNumber(stock.volume) > 50000;
    const isLimitOrStrong = toNumber(stock.daily_change) >= 3 || String(stock.risk_tags || "").includes("爆量股");
    const isMine = holdings.has(code);
    return hasEvent || isHighEvent || isHeavyVolume || isLimitOrStrong || isMine;
  });
}

function normalizeDashboardData(raw) {
  if (Array.isArray(raw)) return { date: "", updated_at: "", items: raw, available: true };
  if (!raw || typeof raw !== "object") return { date: "", updated_at: "", items: [], available: false };
  return {
    ...raw,
    date: String(raw.date || "").trim(),
    updated_at: String(raw.updated_at || "").trim(),
    items: Array.isArray(raw.items) ? raw.items : [],
    available: true,
  };
}

function latestItems(raw) {
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === "object" && Array.isArray(raw.items)) return raw.items;
  return [];
}

function latestMeta(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return {
    updated_at: raw.updated_at || raw.generated_at || raw.date || "",
    content_latest_at: raw.content_latest_at || "",
    stage: raw.stage || "",
    stage_label: raw.stage_label || "",
    schedule_time: raw.schedule_time || "",
    data_version: raw.data_version || "",
    items_count: raw.items_count ?? raw.total_available ?? "",
    new_items_count: raw.new_items_count ?? "",
    source_count: raw.source_count ?? "",
    stale: Boolean(raw.stale),
    stale_reason: raw.stale_reason || "",
  };
}

function mergeLatestMeta(...payloads) {
  const meta = payloads.map(latestMeta).find((item) => item.updated_at || item.stage || item.data_version) || {};
  state.latestUpdate = { ...state.latestUpdate, ...meta };
}

function formatDashboardTime(value) {
  return String(value || "")
    .replace("T", " ")
    .replace(/\+08:00\b/g, "")
    .replace(/\+00:00\b/g, "")
    .replace(/\s*Asia\/Taipei\b/g, "")
    .replace(/\s*\(Asia\/Taipei\)\s*/g, "")
    .trim();
}

function formatDashboardDate(value) {
  const text = formatDashboardTime(value);
  const match = text.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : text;
}

function formatSiteVersionTime(value) {
  const text = formatDashboardTime(value);
  const match = text.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : (text || "資料尚未更新");
}

function siteVersionStatusLabel() {
  const status = String(siteVersionState.status || "");
  if (status.includes("部分")) return "部分資料保留上一版";
  if (status.includes("完全") || status.includes("整站同步完成")) return "完全同步";
  return status || "資料狀態未標示";
}

function siteVersionMiniHtml() {
  const updated = formatSiteVersionTime(siteVersionState.updated_at);
  const slot = siteVersionState.slot_label || "未標示";
  const schedule = siteVersionState.schedule_time ? ` ${escapeHtml(siteVersionState.schedule_time)}` : "";
  const build = siteVersionState.build_id || "-";
  const status = siteVersionStatusLabel();
  return `
    <div class="site-version-mini" aria-label="全站資料版本">
      <span>全站更新：<strong>${escapeHtml(updated)}</strong></span>
      <span>更新時段：<strong>${escapeHtml(slot)}${schedule}</strong></span>
      <span>版本：<strong>${escapeHtml(build)}</strong></span>
      <span>同步狀態：<strong>${escapeHtml(status)}</strong></span>
    </div>
  `;
}

function dashboardUpdateText(data) {
  if (!data?.available) return "資料尚未更新";
  if (data.updated_at) return `資料日期：${formatDashboardTime(data.updated_at)}`;
  if (data.date) return `資料日期：${formatDashboardDate(data.date)}`;
  return "更新時間未標示";
}

function dashboardHasValue(value) {
  const text = String(value ?? "").trim();
  if (!text || text === "-") return false;
  return !/(資料待補|待補|尚未更新|N\/A|undefined|null)/i.test(text);
}

function dashboardDisplayNumber(source, keys, digits = 0) {
  const raw = dashboardFirstValue(source, keys);
  if (!dashboardHasValue(raw)) return "";
  const formatted = dashboardNumber(raw, digits);
  return dashboardHasValue(formatted) ? formatted : "";
}

function dashboardDisplayPercent(source, keys) {
  const raw = dashboardFirstValue(source, keys);
  if (!dashboardHasValue(raw)) return "";
  const formatted = dashboardPercent(raw);
  return dashboardHasValue(formatted) ? formatted : "";
}

function dashboardDisplayBillion(source, keys) {
  const raw = dashboardFirstValue(source, keys);
  if (!dashboardHasValue(raw)) return "";
  const text = String(raw).trim();
  if (text.includes("億")) return text;
  const number = toNumber(raw);
  return Number.isFinite(number) ? `${number.toLocaleString("zh-TW", { maximumFractionDigits: 2 })} 億` : text;
}

function dashboardToneClass(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return "";
  if (number > 0) return " is-up";
  if (number < 0) return " is-down";
  return "";
}

function dashboardNumber(value, digits = 0) {
  const number = toNumber(value);
  return Number.isFinite(number)
    ? number.toLocaleString("zh-TW", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "-";
}

function dashboardPercent(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function dashboardList(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || "").trim()).filter(Boolean).join("、") || "-";
  return String(value || "").trim() || "-";
}

function dashboardEmpty(message) {
  return `<div class="dashboard-empty">${escapeHtml(message)}</div>`;
}

function dashboardSectionTitle(title, data) {
  return `<div class="section-title dashboard-title"><h2>${escapeHtml(title)}</h2><span class="dashboard-meta">${escapeHtml(dashboardUpdateText(data))}</span></div>`;
}

function dashboardQualityWarnings(...datasets) {
  return datasets.flatMap((data) => {
    const warnings = data?.data_quality_warning;
    if (Array.isArray(warnings)) return warnings.filter(Boolean);
    if (warnings) return [String(warnings)];
    return [];
  });
}

function warnDashboardQuality(...datasets) {
  const warnings = [...new Set(dashboardQualityWarnings(...datasets))];
  if (warnings.length) console.warn("Dashboard data quality warning", warnings);
}

function homeVersionDiagnostics(snapshot, hotThemes, hotStocks) {
  const diagnostics = {
    build_version: BUILD_VERSION,
    app_version: APP_VERSION,
    data_updated_at: snapshot?.updated_at || hotThemes?.updated_at || hotStocks?.updated_at || "",
    snapshot_updated_at: snapshot?.updated_at || "",
    themes_updated_at: hotThemes?.updated_at || "",
    stocks_updated_at: hotStocks?.updated_at || "",
    current_page_url: window.location.href,
    source_type: snapshot?.source_type || hotThemes?.source_type || hotStocks?.source_type || "",
  };
  return `
    <section class="panel dashboard-section war-room-section version-diagnostics">
      <div class="section-title dashboard-title"><h2>資料版本診斷</h2><span class="dashboard-meta">${escapeHtml(BUILD_VERSION)}</span></div>
      <pre>${escapeHtml(JSON.stringify(diagnostics, null, 2))}</pre>
    </section>
  `;
}

function hotStocksTable(data) {
  const items = data.available ? data.items.slice(0, 10) : [];
  if (!items.length) return dashboardEmpty("今日熱門股資料尚未更新");
  return `<div class="table-wrap"><table class="dashboard-table"><thead><tr><th>排名</th><th>代號</th><th>名稱</th><th>股價</th><th>漲跌幅</th><th>成交量</th><th>所屬題材</th></tr></thead><tbody>${items.map((item, index) => `<tr><td>${escapeHtml(item.rank || index + 1)}</td><td>${escapeHtml(item.code || "-")}</td><td>${escapeHtml(item.name || "-")}</td><td>${escapeHtml(dashboardNumber(item.price, 2))}</td><td>${escapeHtml(dashboardPercent(item.change_percent))}</td><td>${escapeHtml(dashboardNumber(item.volume))}</td><td>${escapeHtml(item.theme || "-")}</td></tr>`).join("")}</tbody></table></div>`;
}

function hotSectorsTable(data) {
  const items = data.available ? data.items.slice(0, 5) : [];
  if (!items.length) return dashboardEmpty("今日熱門類股資料尚未更新");
  return `<div class="table-wrap"><table class="dashboard-table"><thead><tr><th>排名</th><th>類股</th><th>漲跌幅</th><th>成交量變化</th><th>代表股</th><th>強弱判斷</th></tr></thead><tbody>${items.map((item, index) => `<tr><td>${escapeHtml(item.rank || index + 1)}</td><td>${escapeHtml(item.sector || "-")}</td><td>${escapeHtml(dashboardPercent(item.change_percent))}</td><td>${escapeHtml(item.volume_status || "-")}</td><td>${escapeHtml(dashboardList(item.stocks))}</td><td>${escapeHtml(item.status || "-")}</td></tr>`).join("")}</tbody></table></div>`;
}

function hotThemesTable(data) {
  const items = data.available ? data.items.slice(0, 5) : [];
  if (!items.length) return dashboardEmpty("今日熱門題材資料尚未更新");
  return `<div class="table-wrap"><table class="dashboard-table"><thead><tr><th>排名</th><th>題材</th><th>強度</th><th>代表股</th><th>觸發原因</th><th>相關新聞數</th></tr></thead><tbody>${items.map((item, index) => `<tr><td>${escapeHtml(item.rank || index + 1)}</td><td>${escapeHtml(item.theme || "-")}</td><td>${escapeHtml(dashboardNumber(item.score))}</td><td>${escapeHtml(dashboardList(item.stocks))}</td><td>${escapeHtml(item.reason || "-")}</td><td>${escapeHtml(dashboardNumber(item.news_count))}</td></tr>`).join("")}</tbody></table></div>`;
}

function majorNewsList(data) {
  if (!data.available || !data.items.length) return dashboardEmpty("今日重大新聞資料尚未更新");
  const items = [...data.items]
    .sort((left, right) => {
      const impact = (item) => Number(item.priority || item.impact_score || 0) + (dashboardList(item.themes) !== "-" ? 2 : 0) + (dashboardList(item.stocks) !== "-" ? 2 : 0) + (isRealSourceUrl(item.url) ? 1 : 0);
      return impact(right) - impact(left) || String(right.time || "").localeCompare(String(left.time || ""));
    })
    .slice(0, 5);
  return `<div class="dashboard-news-list">${items.map((item) => {
    const title = escapeHtml(item.title || "未命名新聞");
    const headline = isRealSourceUrl(item.url)
      ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `<span>${title}</span>`;
    return `<article class="dashboard-news-item"><time>${escapeHtml(item.time || "-")}</time><div><h3>${headline}</h3><p>${escapeHtml(item.source || "來源未標示")}</p></div><div><span class="label">影響題材</span>${escapeHtml(dashboardList(item.themes))}</div><div><span class="label">相關個股</span>${escapeHtml(dashboardList(item.stocks))}</div></article>`;
  }).join("")}</div>`;
}

function dashboardFirstValue(source, keys) {
  for (const key of keys) {
    const value = source?.[key];
    if (value !== null && value !== undefined && String(value).trim() !== "") return value;
  }
  return "-";
}

function dashboardMetric(label, value) {
  return `<div class="market-summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function marketSnapshotCards(data) {
  if (!data.available) return dashboardEmpty("大盤狀態資料尚未更新");
  const fields = [
    ["資料狀態", dashboardFirstValue(data, ["session"])],
    ["更新時間", dashboardFirstValue(data, ["updated_at"])],
    ["下一次更新", dashboardFirstValue(data, ["next_update_at"])],
    ["加權指數", dashboardNumber(dashboardFirstValue(data, ["taiex", "close", "index_close"]), 2)],
    ["漲跌點數", dashboardNumber(dashboardFirstValue(data, ["taiex_change", "change_points", "change"]), 2)],
    ["漲跌幅", dashboardPercent(dashboardFirstValue(data, ["taiex_change_percent", "change_percent", "change_pct"]))],
    ["成交值", dashboardFirstValue(data, ["turnover", "turnover_value", "trading_value"])],
    ["上漲家數", dashboardNumber(dashboardFirstValue(data, ["up_count"]))],
    ["下跌家數", dashboardNumber(dashboardFirstValue(data, ["down_count"]))],
    ["漲停家數", dashboardNumber(dashboardFirstValue(data, ["limit_up_count"]))],
    ["跌停家數", dashboardNumber(dashboardFirstValue(data, ["limit_down_count"]))],
    ["盤勢判讀", dashboardFirstValue(data, ["market_status", "market_view", "interpretation", "status"])],
    ["資金流向", dashboardFirstValue(data, ["fund_flow"])],
  ];
  return `<div class="war-room-market-grid market-summary-grid">${fields.map(([label, value]) => dashboardMetric(label, value)).join("")}</div>`;
}

function homeFilters() {
  return `
    <section class="panel dashboard-section war-room-section home-filter-panel" aria-label="首頁篩選器">
      <div class="section-title dashboard-title"><h2>首頁篩選</h2><span class="dashboard-meta">只作用於題材排行與市場候選股</span></div>
      <div class="home-filter-grid">
        <label>市場<select id="homeMarketFilter"><option value="all">全部</option><option value="上市">上市</option><option value="上櫃">上櫃</option></select></label>
        <label>類別<select id="homeGroupFilter"><option value="all">全部</option><option value="electronics">電子</option><option value="non-electronics">非電子</option><option value="finance">金融</option><option value="traditional">傳產</option></select></label>
        <label>強弱<select id="homeStrengthFilter"><option value="all">全部</option><option value="strong">強勢</option><option value="turning">轉強</option><option value="limit-up">漲停集中</option><option value="retreat">退潮</option></select></label>
        <label>題材關鍵字搜尋<input id="homeKeywordFilter" placeholder="AI、PCB、記憶體、塑化、面板、安控"></label>
      </div>
    </section>
  `;
}

function homeFilterValues() {
  return {
    market: $("#homeMarketFilter")?.value || "all",
    group: $("#homeGroupFilter")?.value || "all",
    strength: $("#homeStrengthFilter")?.value || "all",
    keyword: ($("#homeKeywordFilter")?.value || "").trim().toLowerCase(),
  };
}

function homeTextBlob(item) {
  return [
    item.theme,
    item.sector,
    item.market_group,
    item.market,
    item.code,
    item.name,
    item.reason,
    item.signal,
    item.status,
    dashboardList(item.stocks),
  ].join(" ").toLowerCase();
}

function isHomeRetreat(item) {
  const status = `${item.status || ""} ${item.signal || ""} ${item.warning || ""}`;
  const change = toNumber(item.change_percent_avg ?? item.change_percent);
  return /退潮|轉弱|降溫|量縮|跌破/.test(status) || (Number.isFinite(change) && change < 0);
}

function matchHomeGroup(item, group) {
  if (group === "all") return true;
  const text = homeTextBlob(item);
  if (group === "electronics") return /電子|半導體|面板|安控|成熟製程|AI|PCB|記憶體|光電|網通/.test(text);
  if (group === "non-electronics") return /非電子|傳產|金融|塑化|原物料|營建|航運|鋼鐵|觀光|生技/.test(text);
  if (group === "finance") return /金融|銀行|壽險|金控/.test(text);
  if (group === "traditional") return /傳產|塑化|原物料|營建|航運|鋼鐵|觀光|食品|水泥|橡膠/.test(text);
  return true;
}

function matchHomeStrength(item, strength) {
  if (strength === "all") return true;
  const text = homeTextBlob(item);
  if (strength === "strong") return /強勢|強/.test(text) || toNumber(item.score) >= 80;
  if (strength === "turning") return /轉強/.test(text);
  if (strength === "limit-up") return toNumber(item.limit_up_count) > 0 || item.is_limit_up === true;
  if (strength === "retreat") return isHomeRetreat(item);
  return true;
}

function filterHomeItems(items, filters, kind) {
  return (items || []).filter((item) => {
    if (filters.market !== "all" && kind === "stock" && String(item.market || "") !== filters.market) return false;
    if (!matchHomeGroup(item, filters.group)) return false;
    if (!matchHomeStrength(item, filters.strength)) return false;
    if (filters.keyword && !homeTextBlob(item).includes(filters.keyword)) return false;
    return true;
  });
}

function strongestThemeRanking(data, filters = homeFilterValues()) {
  const items = data.available ? filterHomeItems(data.items, filters, "theme").slice(0, 10) : [];
  if (!items.length) return dashboardEmpty("今日最強題材資料尚未更新");
  return `<div class="table-wrap"><table class="theme-ranking"><thead><tr><th>排名</th><th>題材</th><th>產業類別</th><th>強度</th><th>平均漲跌幅</th><th>上漲家數</th><th>漲停</th><th>代表股</th><th>觸發原因</th><th>訊號</th></tr></thead><tbody>${items.map((item, index) => `<tr><td>${escapeHtml(item.rank || index + 1)}</td><td>${escapeHtml(item.theme || "-")}</td><td>${escapeHtml(item.sector || item.market_group || "-")}</td><td>${escapeHtml(dashboardNumber(item.score))}</td><td>${escapeHtml(dashboardPercent(item.change_percent_avg))}</td><td>${escapeHtml(dashboardNumber(item.up_count))}</td><td>${escapeHtml(dashboardNumber(item.limit_up_count))}</td><td>${escapeHtml(dashboardList(item.stocks))}</td><td>${escapeHtml(item.reason || "-")}</td><td>${escapeHtml(item.signal || item.status || "-")}</td></tr>`).join("")}</tbody></table></div>`;
}

function sectorSummary(data, filters = homeFilterValues()) {
  const raw = data.available && Array.isArray(data.sector_summary) ? data.sector_summary : [];
  const items = filterHomeItems(raw, filters, "sector").slice(0, 8);
  if (!items.length) return dashboardEmpty("產業強弱資料尚未更新");
  return `<div class="sector-summary">${items.map((item) => `<article><div><strong>${escapeHtml(item.sector || "類別未標示")}</strong><span>${escapeHtml(item.status || "-")}</span></div><p>漲跌幅：${escapeHtml(dashboardPercent(item.change_percent))}</p><p>代表題材：${escapeHtml(dashboardList(item.themes))}</p><p>代表股：${escapeHtml(dashboardList(item.stocks))}</p><small>${escapeHtml(item.reason || "-")}</small></article>`).join("")}</div>`;
}

function hotStockTable(data, filters = homeFilterValues()) {
  const items = data.available ? filterHomeItems(data.items, filters, "stock").slice(0, 20) : [];
  if (!items.length) return dashboardEmpty("今日市場候選股資料尚未更新");
  return `<div class="table-wrap"><table class="hot-stock-table"><thead><tr><th>排名</th><th>股票代號</th><th>股票名稱</th><th>市場</th><th>產業</th><th>題材</th><th>股價</th><th>漲跌幅</th><th>成交量</th><th>量比</th><th>漲停</th><th>分數</th><th>入選原因</th></tr></thead><tbody>${items.map((item, index) => {
    const code = normalizeCode(item.code);
    return `<tr><td>${escapeHtml(item.rank || index + 1)}</td><td>${code ? `<a href="stock.html?code=${encodeURIComponent(code)}">${escapeHtml(code)}</a>` : "-"}</td><td>${escapeHtml(item.name || "-")}</td><td>${escapeHtml(item.market || "-")}</td><td>${escapeHtml(item.sector || item.market_group || "-")}</td><td>${escapeHtml(item.theme || "-")}</td><td>${escapeHtml(dashboardNumber(item.price, 2))}</td><td>${escapeHtml(dashboardPercent(item.change_percent))}</td><td>${escapeHtml(dashboardNumber(item.volume))}</td><td>${escapeHtml(dashboardNumber(item.volume_ratio, 2))}</td><td>${escapeHtml(item.is_limit_up ? "是" : "否")}</td><td>${escapeHtml(dashboardNumber(item.score))}</td><td>${escapeHtml(item.reason || "-")}</td></tr>`;
  }).join("")}</tbody></table></div>`;
}

function retreatAlerts(data) {
  if (!data.available) return dashboardEmpty("退潮警示資料尚未更新");
  const alerts = data.items.filter(isHomeRetreat).slice(0, 5);
  if (!alerts.length) return dashboardEmpty("目前資料未標示明確退潮警示");
  return `<div class="war-room-alert-list">${alerts.map((item) => `<div><strong>${escapeHtml(item.theme || "題材未標示")}</strong><span>${escapeHtml(item.warning || item.status || item.signal || "轉弱觀察")}</span></div>`).join("")}</div>`;
}

function internationalRiskList(data) {
  const items = data.available && Array.isArray(data.international_risks) ? data.international_risks.slice(0, 5) : [];
  if (!items.length) return dashboardEmpty("國際新聞風險尚未更新");
  return `<div class="risk-news-list">${items.map((item) => {
    const title = escapeHtml(item.title || "未命名風險");
    const headline = isRealSourceUrl(item.url)
      ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `<span>${title}</span>`;
    return `<article><h3>${headline}</h3><div><span>${escapeHtml(item.impact || "中性")}</span><small>${escapeHtml(item.source_name || "來源未標示")}</small></div><p>相關市場：${escapeHtml(dashboardList(item.related_markets))}</p><p>${escapeHtml(item.reason || "-")}</p></article>`;
  }).join("")}</div>`;
}

function tomorrowConditions(snapshot, themes) {
  const raw = snapshot.tomorrow_conditions || themes.tomorrow_conditions || [];
  const conditions = Array.isArray(raw) ? raw.map((item) => String(item || "").trim()).filter(Boolean) : [];
  if (!conditions.length) return dashboardEmpty("明日作戰條件資料尚未更新");
  return `<ul class="tomorrow-condition-list war-room-condition-list">${conditions.slice(0, 8).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function objectiveNote() {
  return `<section class="panel dashboard-section war-room-section objective-note"><p>首頁排名僅依全市場當日資料、題材同步性、產業漲跌、量能變化與新聞催化計算；個人持股與自選股不得參與分數、排序與首頁預設呈現。</p></section>`;
}

function renderHomeFilteredSections(hotThemes, hotStocks) {
  const filters = homeFilterValues();
  const themeEl = $("#homeThemeRanking");
  const sectorEl = $("#homeSectorSummary");
  const stockEl = $("#homeHotStocks");
  if (themeEl) themeEl.innerHTML = strongestThemeRanking(hotThemes, filters);
  if (sectorEl) sectorEl.innerHTML = sectorSummary(hotThemes, filters);
  if (stockEl) stockEl.innerHTML = hotStockTable(hotStocks, filters);
}

function bindHomeFilters(hotThemes, hotStocks) {
  ["#homeMarketFilter", "#homeGroupFilter", "#homeStrengthFilter", "#homeKeywordFilter"].forEach((selector) => {
    const control = $(selector);
    control?.addEventListener("input", () => renderHomeFilteredSections(hotThemes, hotStocks));
    control?.addEventListener("change", () => renderHomeFilteredSections(hotThemes, hotStocks));
  });
}

function homeJoinList(value, limit = 4) {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item || "").trim()).filter(Boolean).slice(0, limit);
    return items.length ? items.join("、") : "-";
  }
  const text = String(value || "").trim();
  return text || "-";
}

const TWSE_INDUSTRY_LABELS = {
  "01": "水泥",
  "02": "食品",
  "03": "塑膠",
  "04": "紡織纖維",
  "05": "電機機械",
  "06": "電器電纜",
  "08": "玻璃陶瓷",
  "09": "造紙",
  "10": "鋼鐵",
  "11": "橡膠",
  "12": "汽車",
  "14": "營建",
  "15": "航運",
  "16": "觀光",
  "17": "金融",
  "18": "貿易百貨",
  "20": "其他",
  "21": "化學",
  "22": "生技醫療",
  "23": "油電燃氣",
  "24": "半導體",
  "25": "電腦及週邊",
  "26": "光電",
  "27": "通信網路",
  "28": "電子零組件",
  "29": "電子通路",
  "30": "資訊服務",
  "31": "其他電子",
  "32": "文化創意",
  "33": "農業科技",
  "34": "電子商務",
  "35": "綠能環保",
  "36": "數位雲端",
  "37": "運動休閒",
  "38": "居家生活",
};

function homeDisplayTheme(item) {
  const theme = String(item?.theme || "").trim();
  if (/^\d{2}$/.test(theme)) return TWSE_INDUSTRY_LABELS[theme] || `產業代碼 ${theme}`;
  return theme || item?.sector || item?.market_group || "-";
}

function homeStockLinks(value, limit = 5) {
  const items = Array.isArray(value) ? value : [value];
  const links = items.map((item) => String(item || "").trim()).filter(Boolean).slice(0, limit).map((text) => {
    const match = text.match(/^(\d{4})\s*(.*)$/);
    if (!match) return escapeHtml(text);
    const code = normalizeCode(match[1]);
    const name = match[2] || "";
    return `<a href="stock.html?code=${encodeURIComponent(code)}">${escapeHtml(`${code} ${name}`.trim())}</a>`;
  });
  return links.length ? links.join("、") : "-";
}

function homeThemeQuery(theme) {
  const label = String(theme || "").trim();
  const aliases = [
    ["記憶體", "記憶體"],
    ["DRAM", "記憶體"],
    ["AI 伺服器", "AI伺服器"],
    ["AI伺服器", "AI伺服器"],
    ["滑軌", "AI伺服器"],
    ["半導體", "半導體"],
    ["AI 晶片", "半導體"],
    ["航空", "航空"],
    ["雲端", "雲端"],
    ["算力", "AI伺服器"],
  ];
  const hit = aliases.find(([keyword]) => label.includes(keyword));
  return hit ? hit[1] : label.split(/[／/|｜]/)[0].trim();
}

function homeThemeLink(theme) {
  const label = String(theme || "").trim() || "-";
  if (label === "-") return "-";
  return `<a href="concepts.html?q=${encodeURIComponent(homeThemeQuery(label))}">${escapeHtml(label)}</a>`;
}

function isExcludedHomeObservation(item) {
  const text = `${item.sector || ""} ${item.market_group || ""} ${item.theme || ""} ${item.reason || ""}`;
  return /金融|銀行|壽險|金控|營建|營造|建材營造/.test(text);
}

function homeFlowJudge(item) {
  const signal = item.signal || item.status || item.volume_status || "";
  const limitUp = toNumber(item.limit_up_count);
  const change = toNumber(item.change_percent_avg ?? item.change_percent);
  const parts = [];
  if (dashboardHasValue(signal)) parts.push(signal);
  if (Number.isFinite(limitUp) && limitUp > 0) parts.push(`漲停 ${dashboardNumber(limitUp)}`);
  if (Number.isFinite(change) && change !== 0) parts.push(`漲跌 ${dashboardPercent(change)}`);
  return parts.length ? parts.join("｜") : "觀察";
}

function homeStockFlowGroups(data) {
  const items = data.available ? data.items.filter((item) => !isExcludedHomeObservation(item)) : [];
  const groups = new Map();
  items.forEach((item) => {
    const theme = homeDisplayTheme(item);
    const key = `${item.sector || item.market_group || "未分類"}|${theme}`;
    const current = groups.get(key) || {
      sector: item.sector || item.market_group || "未分類",
      theme,
      score: 0,
      stocks: [],
      reasons: [],
    };
    current.score = Math.max(current.score, toNumber(item.score) || 0);
    if (current.stocks.length < 5) {
      const code = normalizeCode(item.code);
      current.stocks.push(code ? `${code} ${item.name || ""}`.trim() : item.name || "-");
    }
    if (dashboardHasValue(item.reason) && current.reasons.length < 2) current.reasons.push(item.reason);
    groups.set(key, current);
  });
  return [...groups.values()]
    .sort((left, right) => right.score - left.score)
    .slice(0, 10);
}

function homePanelTitle(title, data) {
  return `
    <div class="home-panel-title">
      <h2>${escapeHtml(title)}</h2>
      <span>${escapeHtml(dashboardUpdateText(data))}</span>
    </div>
  `;
}

function homeMarketOverview(snapshot) {
  if (!snapshot.available) return dashboardEmpty("今日市場總覽資料尚未更新");
  const metric = (label, value, toneSource = value) => dashboardHasValue(value) ? [label, value, toneSource] : null;
  const metrics = [
    metric("加權指數", dashboardDisplayNumber(snapshot, ["taiex", "close", "index_close"], 2)),
    metric("成交(億)", dashboardDisplayBillion(snapshot, ["turnover_billion", "turnover_value_billion", "trading_value_billion", "turnover"])),
    metric("漲幅", dashboardDisplayPercent(snapshot, ["taiex_change_percent", "change_percent", "change_pct"]), dashboardFirstValue(snapshot, ["taiex_change_percent", "change_percent", "change_pct"])),
    metric("漲跌", dashboardDisplayNumber(snapshot, ["taiex_change", "change_points", "change"], 2), dashboardFirstValue(snapshot, ["taiex_change", "change_points", "change"])),
    metric("昨收", dashboardDisplayNumber(snapshot, ["previous_close", "prev_close", "yesterday_close"], 2)),
    metric("昨量(億)", dashboardDisplayBillion(snapshot, ["previous_turnover_billion", "prev_turnover_billion", "yesterday_turnover_billion"])),
    metric("上漲家數", dashboardDisplayNumber(snapshot, ["up_count", "stock_up_count"], 0), dashboardFirstValue(snapshot, ["up_count", "stock_up_count"])),
    metric("下跌家數", dashboardDisplayNumber(snapshot, ["down_count", "stock_down_count"], 0), -Math.abs(toNumber(dashboardFirstValue(snapshot, ["down_count", "stock_down_count"])) || 0)),
    metric("漲停家數", dashboardDisplayNumber(snapshot, ["limit_up_count", "stock_limit_up_count"], 0), dashboardFirstValue(snapshot, ["limit_up_count", "stock_limit_up_count"])),
    metric("跌停家數", dashboardDisplayNumber(snapshot, ["limit_down_count", "stock_limit_down_count"], 0), -Math.abs(toNumber(dashboardFirstValue(snapshot, ["limit_down_count", "stock_limit_down_count"])) || 0)),
  ].filter(Boolean);
  if (!metrics.length) return dashboardEmpty("大盤數值待補，盤後資料會沿用至隔日 09:00 前。");
  return `<div class="home-market-grid">${metrics.map(([label, value, toneSource]) => `<article><span>${escapeHtml(label)}</span><strong class="${dashboardToneClass(toneSource).trim()}">${escapeHtml(value)}</strong></article>`).join("")}</div>`;
}

function homeThemeTopTable(data) {
  const sourceItems = Array.isArray(data.verified_hot_themes) && data.verified_hot_themes.length
    ? data.verified_hot_themes
    : data.items;
  const items = data.available ? sourceItems.slice(0, 5) : [];
  if (!items.length) return dashboardEmpty("熱門題材資料尚未更新");
  const rows = items.map((item, index) => ({
    rank: item.rank || index + 1,
    theme: homeDisplayTheme(item),
    strength: item.fund_strength || item.strength || dashboardNumber(item.score),
    leaders: item.stocks || [],
    judge: item.judgement || item.reason || homeFlowJudge(item),
  }));
  return `
    <p class="home-section-note">當下最新交叉核對盤中資金流、類股漲跌、漲停與強勢股，再整理出最強題材前五。</p>
    <div class="table-wrap home-table-wrap home-desktop-only">
      <table class="home-dashboard-table">
        <thead><tr><th>排名</th><th>題材</th><th>資金強度</th><th>最強代表股</th><th>判斷</th></tr></thead>
        <tbody>${rows.map((item) => `
          <tr>
            <td>${escapeHtml(item.rank)}</td>
            <td>${homeThemeLink(item.theme)}</td>
            <td class="home-number">${escapeHtml(item.strength)}</td>
            <td>${homeStockLinks(item.leaders, 5)}</td>
            <td>${escapeHtml(item.judge)}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    </div>
    <div class="home-mobile-cards">
      ${rows.map((item) => `
        <article>
          <div><strong>${escapeHtml(item.rank)}. ${homeThemeLink(item.theme)}</strong><span>資金強度 ${escapeHtml(item.strength)}</span></div>
          <p><b>最強代表股</b>${homeStockLinks(item.leaders, 5)}</p>
          <p><b>判斷</b>${escapeHtml(item.judge)}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function homeAiStockTable(data) {
  const items = homeStockFlowGroups(data);
  if (!items.length) return dashboardEmpty("AI選股觀察資料尚未更新");
  return `
    <p class="home-section-note">當下最新交叉核對盤中資金流、類股漲跌、漲停與強勢股，再整理出最強資金方向和代表個股。</p>
    <div class="table-wrap home-table-wrap home-desktop-only">
      <table class="home-dashboard-table">
        <thead><tr><th>產業別</th><th>題材</th><th>最強代表股(5檔)</th><th>阿斯拉評語</th></tr></thead>
        <tbody>${items.map((item, index) => {
          const comment = item.reasons.length ? item.reasons.join("；") : `依候選股分數與量能同步性排序，第 ${index + 1} 組資金方向。`;
          return `
            <tr>
              <td>${escapeHtml(item.sector)}</td>
              <td>${homeThemeLink(item.theme)}</td>
              <td>${homeStockLinks(item.stocks, 5)}</td>
              <td>${escapeHtml(comment)}</td>
            </tr>
          `;
        }).join("")}</tbody>
      </table>
    </div>
    <div class="home-mobile-cards">
      ${items.map((item, index) => {
        const comment = item.reasons.length ? item.reasons[0] : `依候選股分數與量能同步性排序，第 ${index + 1} 組資金方向。`;
        return `
          <article>
            <div><strong>${escapeHtml(item.sector)}｜${homeThemeLink(item.theme)}</strong><span>第 ${index + 1} 組</span></div>
            <p><b>最強代表股</b>${homeStockLinks(item.stocks, 5)}</p>
            <p><b>阿斯拉評語</b>${escapeHtml(comment)}</p>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function homeThreeDayThemeTable(data) {
  const items = data.available && Array.isArray(data.three_day_limit_themes)
    ? data.three_day_limit_themes.slice(0, 10)
    : [];
  if (!items.length) return dashboardEmpty("前三天漲停題材統計尚未建立");
  const rows = items.map((item, index) => ({
    rank: item.rank || index + 1,
    theme: item.theme || "-",
    limitCount: item.limit_up_count_3d ?? item.limit_up_count ?? "-",
    stocks: item.stocks || [],
    judgement: item.judgement || item.reason || "-",
  }));
  return `
    <p class="home-section-note">依前三個交易日漲停最多的題材排序，並列出目前資料庫可辨識的相關概念股。</p>
    <div class="table-wrap home-table-wrap home-desktop-only">
      <table class="home-dashboard-table">
        <thead><tr><th>排名</th><th>題材</th><th>三日漲停統計</th><th>相關概念股</th><th>判斷</th></tr></thead>
        <tbody>${rows.map((item) => `
          <tr>
            <td>${escapeHtml(item.rank)}</td>
            <td>${homeThemeLink(item.theme)}</td>
            <td class="home-number">${escapeHtml(item.limitCount)}</td>
            <td>${homeStockLinks(item.stocks, 20)}</td>
            <td>${escapeHtml(item.judgement)}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    </div>
    <div class="home-mobile-cards">
      ${rows.map((item) => `
        <article>
          <div><strong>${escapeHtml(item.rank)}. ${homeThemeLink(item.theme)}</strong><span>三日漲停 ${escapeHtml(item.limitCount)}</span></div>
          <p><b>相關概念股</b>${homeStockLinks(item.stocks, 20)}</p>
          <p><b>判斷</b>${escapeHtml(item.judgement)}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function homeMajorNewsTable(data) {
  const items = data.available ? [...data.items]
    .sort((left, right) => {
      const score = (item) => Number(item.priority || item.impact_score || 0) + (isRealSourceUrl(eventUrl(item)) ? 10 : 0);
      return score(right) - score(left) || String(right.date || right.time || "").localeCompare(String(left.date || left.time || ""));
    })
    .slice(0, 5) : [];
  if (!items.length) return dashboardEmpty("重大新聞資料尚未更新");
  return `
    <div class="table-wrap home-table-wrap">
      <table class="home-dashboard-table home-news-table">
        <thead><tr><th>時間</th><th>標題</th><th>影響題材</th><th>影響個股</th><th>來源</th></tr></thead>
        <tbody>${items.map((item) => {
          const url = eventUrl(item);
          const title = escapeHtml(item.title || "未命名新聞");
          const headline = isRealSourceUrl(url)
            ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
            : `<span>${title}</span>`;
          return `
            <tr>
              <td>${escapeHtml(item.time || item.date || "-")}</td>
              <td>${headline}</td>
              <td>${escapeHtml(homeJoinList(item.themes || item.category || item.related_keywords, 4))}</td>
              <td>${escapeHtml(homeJoinList(item.stocks || item.related_stocks, 5))}</td>
              <td>${escapeHtml(item.source || item.source_name || "-")}</td>
            </tr>
          `;
        }).join("")}</tbody>
      </table>
    </div>
    <div class="home-news-more"><a href="news.html">查看全部重大新聞</a></div>
  `;
}

async function renderHome() {
  const main = $("#app");
  const [snapshotRaw, stocksRaw, themesRaw] = await Promise.all([
    loadJson("data/daily_market_snapshot.json", null),
    loadJson("data/daily_hot_stocks.json", null),
    loadJson("data/daily_hot_themes.json", null),
  ]);
  const snapshot = normalizeDashboardData(snapshotRaw);
  const hotStocks = normalizeDashboardData(stocksRaw);
  const hotThemes = normalizeDashboardData(themesRaw);
  warnDashboardQuality(snapshot, hotStocks, hotThemes);
  main.innerHTML = `
    <section class="panel dashboard-section war-room-section war-room-market">
      ${dashboardSectionTitle("今日市場總覽", snapshot)}
      ${marketSnapshotCards(snapshot)}
    </section>
    ${homeFilters()}
    <div class="war-room-grid home-dashboard-grid">
      <section class="panel dashboard-section war-room-section"><div class="section-title dashboard-title"><h2>今日最強題材排行</h2><span class="dashboard-meta">${escapeHtml(dashboardUpdateText(hotThemes))}</span></div><div id="homeThemeRanking">${strongestThemeRanking(hotThemes)}</div></section>
      <section class="panel dashboard-section war-room-section"><div class="section-title dashboard-title"><h2>今日產業類別強弱</h2><span class="dashboard-meta">${escapeHtml(dashboardUpdateText(hotThemes))}</span></div><div id="homeSectorSummary">${sectorSummary(hotThemes)}</div></section>
      <section class="panel dashboard-section war-room-section home-wide"><div class="section-title dashboard-title"><h2>今日市場候選股</h2><span class="dashboard-meta">${escapeHtml(dashboardUpdateText(hotStocks))}</span></div><div id="homeHotStocks">${hotStockTable(hotStocks)}</div></section>
      <section class="panel dashboard-section war-room-section war-room-warning">${dashboardSectionTitle("今日退潮警示", hotThemes)}${retreatAlerts(hotThemes)}</section>
      <section class="panel dashboard-section war-room-section">${dashboardSectionTitle("國際新聞風險", snapshot)}${internationalRiskList(snapshot)}</section>
      <section class="panel dashboard-section war-room-section">${dashboardSectionTitle("明日作戰條件", snapshot.available ? snapshot : hotThemes)}${tomorrowConditions(snapshot, hotThemes)}</section>
    </div>
    ${objectiveNote()}
    ${homeVersionDiagnostics(snapshot, hotThemes, hotStocks)}
  `;
  bindHomeFilters(hotThemes, hotStocks);
}

function radarStockSearchText(stock) {
  return [
    stock.code,
    displayStockName(stock.code),
    getIndustryName(stock),
    inferThemeTags(stock).join(" "),
    stock.concept,
    stock.business,
    stock.reason,
    stock.risk_tags,
  ].join(" ").toLowerCase();
}

function stockMasterCountText() {
  const count = state.universeCount || Object.keys(state.master || {}).length;
  return count ? `全台股 ${dashboardNumber(count)} 檔上市櫃股票` : "全台股上市櫃股票";
}

function radarFormatTimestamp(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return formatDashboardTime(raw);
  const parts = new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date).reduce((acc, part) => {
    acc[part.type] = part.value;
    return acc;
  }, {});
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

function radarLatestDataText(stocks, news) {
  const timestamps = [];
  stocks.forEach((stock) => {
    if (stock.market_date) timestamps.push(`${stock.market_date}T00:00:00+08:00`);
  });
  news.forEach((event) => {
    if (event.date) timestamps.push(event.date);
  });
  const latest = timestamps
    .map((value) => ({ value, time: new Date(value).getTime() }))
    .filter((item) => Number.isFinite(item.time))
    .sort((a, b) => b.time - a.time)[0];
  return latest ? `資料時間：${radarFormatTimestamp(latest.value)}` : "資料時間未標示";
}

function radarCleanThemeLabel(value) {
  const text = cleanDisplay(value);
  if (/^\d{2}$/.test(text)) return TWSE_INDUSTRY_LABELS[text] || `產業代碼 ${text}`;
  return text === "—" ? "題材待補" : text;
}

function radarThemeList(stock) {
  const tags = inferThemeTags(stock).map(radarCleanThemeLabel).filter((tag) => tag && tag !== "題材待補");
  String(stock.concept || "").split(/[;、,，/｜|]/).map(radarCleanThemeLabel).forEach((tag) => {
    if (tag && tag !== "題材待補") tags.push(tag);
  });
  const industry = radarCleanThemeLabel(getIndustryName(stock));
  if (industry && industry !== "題材待補") tags.push(industry);
  return [...new Set(tags)].slice(0, 4);
}

function stockNameForList(code, fallbackName = "") {
  const master = masterName(code);
  const fallback = String(fallbackName || "").trim();
  const name = master || fallback;
  return name && name !== "名稱待補" ? name : "";
}

function radarStockLabelLink(code, fallbackName = "") {
  const normalized = normalizeCode(code);
  if (!/^\d{4}$/.test(normalized)) return escapeHtml(String(code || "").trim() || "-");
  const name = stockNameForList(normalized, fallbackName);
  const nameText = name ? ` ${name}` : "";
  return `<a class="stock-link" href="stock.html?code=${encodeURIComponent(normalized)}">${escapeHtml(normalized)}</a>${escapeHtml(nameText)}`;
}

function parseStockText(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(\d{4})(?:\s+(.+))?$/);
  return {
    code: match ? match[1] : normalizeCode(text),
    name: match ? String(match[2] || "").trim() : "",
  };
}

function radarStockLink(stock) {
  const code = normalizeCode(stock?.code);
  const name = stock?.name || "";
  if (!code) return "-";
  return radarStockLabelLink(code, name);
}

function radarThemeLink(theme) {
  const label = radarCleanThemeLabel(theme);
  if (!label || label === "題材待補") return escapeHtml(label);
  return `<a class="stock-link" href="concepts.html?q=${encodeURIComponent(label)}">${escapeHtml(label)}</a>`;
}

function radarTopStocksByTheme(stocks, limit = 5) {
  const groups = new Map();
  stocks.forEach((stock) => {
    radarThemeList(stock).forEach((theme) => {
      const current = groups.get(theme) || { theme, score: 0, stocks: [], stockCodes: new Set(), reasons: [] };
      current.score += Math.max(0, radarScoreValue(stock));
      const code = normalizeCode(stock.code);
      if (code && !current.stockCodes.has(code) && current.stocks.length < limit) {
        current.stockCodes.add(code);
        current.stocks.push(stock);
      }
      if (dashboardHasValue(stock.reason) && current.reasons.length < 2) current.reasons.push(stock.reason);
      groups.set(theme, current);
    });
  });
  return [...groups.values()]
    .map((group) => ({ ...group, avgScore: group.stocks.length ? group.score / group.stocks.length : 0 }))
    .sort((a, b) => b.avgScore - a.avgScore || b.stocks.length - a.stocks.length)
    .slice(0, 5);
}

function radarRecentNewsThemes(news = state.news) {
  const groups = new Map();
  news.filter((event) => isRealSourceUrl(eventUrl(event))).forEach((event) => {
    const labels = [
      event.category,
      ...(event.related_keywords || []),
    ].map(radarCleanThemeLabel).filter((label) => label && label !== "題材待補");
    [...new Set(labels)].forEach((theme) => {
      const current = groups.get(theme) || { theme, count: 0, stocks: new Set(), events: [] };
      current.count += 1;
      (event.related_stocks || []).map(normalizeCode).filter(Boolean).forEach((code) => current.stocks.add(code));
      if (current.events.length < 3) current.events.push(event.title || event.category || "新聞");
      groups.set(theme, current);
    });
  });
  return [...groups.values()].sort((a, b) => b.count - a.count || b.stocks.size - a.stocks.size).slice(0, 5);
}

function radarLowBaseStocks(stocks) {
  return stocks
    .filter((stock) => {
      const yoy = evidenceNumber(stock.revenue_yoy_value ?? stock.revenue_yoy);
      const mom = evidenceNumber(stock.revenue_mom_value ?? stock.revenue_mom);
      const reason = `${stock.reason || ""} ${stock.risk_tags || ""}`;
      return (Number.isFinite(yoy) && yoy >= 50 && Number.isFinite(mom) && mom >= 0) || /低基期/.test(reason);
    })
    .sort((a, b) =>
      radarScoreValue(b) - radarScoreValue(a) ||
      (evidenceNumber(b.revenue_yoy_value) || 0) - (evidenceNumber(a.revenue_yoy_value) || 0) ||
      (evidenceNumber(b.volume_value) || 0) - (evidenceNumber(a.volume_value) || 0)
    )
    .slice(0, 10);
}

function radarStockLinks(stocks, limit = 5) {
  const list = Array.isArray(stocks) ? stocks : [];
  const links = list.slice(0, limit).map((stock) => {
    if (typeof stock === "string") {
      const parsed = parseStockText(stock);
      return parsed.code ? radarStockLabelLink(parsed.code, parsed.name) : escapeHtml(stock);
    }
    return radarStockLink(stock);
  });
  return links.length ? links.join("、") : "-";
}

function radarTop5ThemeItems(data = state.themeTop5) {
  if (!data?.available || !Array.isArray(data.items)) return [];
  return data.items.slice(0, 5).map((item, index) => ({
    rank: item.rank || index + 1,
    theme: item.theme || "-",
    score: item.score ?? "-",
    status: item.status || "",
    stocks: item.stocks || [],
    evidence: item.evidence && typeof item.evidence === "object" ? item.evidence : {},
    conclusion: item.conclusion || "",
  }));
}

function radarTop5ThemeSearchText(item) {
  return [
    item.theme,
    item.score,
    item.status,
    item.conclusion,
    ...(item.stocks || []).map((stock) => `${stock.code || ""} ${stock.name || ""}`),
    ...Object.values(item.evidence || {}),
  ].join(" ").toLowerCase();
}

function radarThemeEvidenceList(evidence = {}) {
  const fields = [
    ["新聞面", evidence.news],
    ["技術面", evidence.technical],
    ["漲跌面", evidence.price],
    ["資金面", evidence.flow],
    ["基本面 / 產業催化", evidence.fundamental],
  ];
  return fields.map(([label, text]) => `
    <div class="theme-evidence-item">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(text || "資料待補")}</span>
    </div>
  `).join("");
}

function rankingAccordionButton() {
  return `<button class="ranking-toggle" type="button">展開依據</button>`;
}

function radarTop5ThemeCards(items) {
  if (!items.length) return `<div class="empty">五日內最強題材資料尚未更新</div>`;
  return `
    <div class="theme-top5-grid">
      ${items.map((item) => `
        <article class="theme-top5-card">
          <div class="theme-top5-head">
            <div>
              <span class="theme-rank">#${escapeHtml(item.rank)}</span>
              <h3>${radarThemeLink(item.theme)}</h3>
            </div>
            <div class="theme-score">
              <strong>${escapeHtml(item.score)}</strong>
              <span>${escapeHtml(item.status || "觀察")}</span>
            </div>
          </div>
          <div class="theme-stock-row">${radarStockLinks(item.stocks, 8)}</div>
          ${rankingAccordionButton()}
          <div class="ranking-detail">
            <div class="theme-evidence-grid">${radarThemeEvidenceList(item.evidence)}</div>
            <p class="theme-conclusion"><strong>結論</strong>${escapeHtml(item.conclusion || "資料待補")}</p>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function rankingDataItems(raw) {
  const data = normalizeDashboardData(raw);
  const sourceNote = String(raw?.source_note || "").trim();
  return {
    ...data,
    generated_at: String(raw?.generated_at || raw?.updated_at || raw?.date || "").trim(),
    range: String(raw?.range || "").trim(),
    source_note: /\?{4,}/.test(sourceNote) ? "" : sourceNote,
    items: Array.isArray(raw?.items) ? raw.items : [],
  };
}

function radarStageUpdateText() {
  const meta = state.latestUpdate || {};
  const stage = meta.stage_label || meta.stage || "";
  const time = formatDashboardTime(meta.updated_at || "");
  if (stage && time) return `${stage} ${time}`;
  if (time) return `最後更新 ${time}`;
  return "資料更新時間未標示";
}

function rankingMetaText(data) {
  if (data.generated_at) return `資料時間：${escapeHtml(formatDashboardTime(data.generated_at))}`;
  if (data.updated_at) return `資料時間：${escapeHtml(formatDashboardTime(data.updated_at))}`;
  if (data.date) return `資料日期：${escapeHtml(formatDashboardDate(data.date))}`;
  return "資料時間未標示";
}

function rankingStockChips(stocks = [], limit = 6) {
  const list = Array.isArray(stocks) ? stocks.slice(0, limit) : [];
  if (!list.length) return `<span class="muted">代表股待補</span>`;
  return list.map((stock) => `<span class="ranking-chip">${radarStockLink(stock)}</span>`).join("");
}

function rankingList(values = []) {
  const list = Array.isArray(values) ? values : [values].filter(Boolean);
  return list.length ? list.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>資料待補</li>";
}

function qualityBadge(item) {
  if (!item?.data_quality || item.data_quality !== "low") return "";
  return `<span class="ranking-quality">資料不足</span>`;
}

function renderNewsThemeRankingCards(items, showAll = false) {
  const visible = items.slice(0, showAll ? 10 : 5);
  return `
    <div class="ranking-card-list">
      ${visible.map((item) => `
        <article class="ranking-card">
          <div class="ranking-card-head">
            <div>
              <span class="theme-rank">#${escapeHtml(item.rank || "")}</span>
              <h3>${radarThemeLink(item.theme || "題材待補")}</h3>
              <div class="ranking-submeta">新聞 ${escapeHtml(item.news_count ?? 0)} 篇｜來源 ${escapeHtml(item.unique_sources ?? 0)} 個｜提及 ${escapeHtml(item.mentioned_stock_count ?? 0)} 檔</div>
            </div>
            <div class="ranking-score"><strong>${escapeHtml(item.theme_score ?? "-")}</strong><span>綜合分數</span></div>
          </div>
          <div class="ranking-stock-row">${rankingStockChips(item.representative_stocks, 6)}</div>
          ${rankingAccordionButton()}
          <div class="ranking-detail">
            <div class="evidence-grid">
              <div class="supply-demand-box"><strong>新聞面</strong><p>${escapeHtml(item.evidence?.news || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>技術面</strong><p>${escapeHtml(item.evidence?.technical || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>漲跌面</strong><p>${escapeHtml(item.evidence?.price || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>資金面</strong><p>${escapeHtml(item.evidence?.volume || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>供需面：需求</strong><ul>${rankingList(item.supply_demand?.demand)}</ul></div>
              <div class="supply-demand-box"><strong>供需面：供給</strong><ul>${rankingList(item.supply_demand?.supply)}</ul></div>
              <div class="supply-demand-box"><strong>基本面</strong><p>${escapeHtml(item.evidence?.fundamental || item.supply_demand?.price_power || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>阿斯拉判斷 ${qualityBadge(item)}</strong><p>${escapeHtml(item.asurada_comment || item.supply_demand?.conclusion || "資料待補")}</p></div>
            </div>
            ${item.data_quality_note ? `<p class="risk-note">${escapeHtml(item.data_quality_note)}</p>` : ""}
          </div>
        </article>
      `).join("")}
    </div>
    ${items.length > 5 ? `<button class="ranking-toggle" id="newsThemeToggle">${showAll ? "收合 TOP 5" : "顯示更多 6-10 名"}</button>` : ""}
  `;
}

function renderLowBaseRankingCards(items, market = "上市") {
  const filtered = items
    .filter((item) => market === "全部" || (item.market || "") === market)
    .slice(0, 10);
  if (!filtered.length) return `<div class="empty">低基期題材資料載入失敗，請確認 docs/data/low-base-theme-ranking.json 是否存在。</div>`;
  return `
    <div class="ranking-card-list">
      ${filtered.map((item) => `
        <article class="ranking-card">
          <div class="ranking-card-head">
            <div>
              <span class="theme-rank">#${escapeHtml(item.rank || "")}</span>
              <h3>${radarStockLabelLink(item.code, item.name)}</h3>
              <div class="ranking-submeta">${radarThemeLink(item.theme || "題材待補")}｜${escapeHtml(item.market || "市場別待補")}</div>
            </div>
            <div class="ranking-score"><strong>${escapeHtml(item.score ?? "-")}</strong><span>綜合分數</span></div>
          </div>
          ${rankingAccordionButton()}
          <div class="ranking-detail">
            <div class="evidence-grid">
              <div class="supply-demand-box"><strong>漲跌面</strong><p>${item.five_day_change_pct === null || item.five_day_change_pct === undefined ? "資料待補" : escapeHtml(dashboardPercent(item.five_day_change_pct))}</p></div>
              <div class="supply-demand-box"><strong>資金面</strong><p>${item.volume_ratio_20d === null || item.volume_ratio_20d === undefined ? "20 日量比資料待補" : escapeHtml(dashboardNumber(item.volume_ratio_20d, 2))}</p></div>
              <div class="supply-demand-box"><strong>低位階位置</strong><p>${item.position?.range_position_pct === null || item.position?.range_position_pct === undefined ? "資料待補" : escapeHtml(`${dashboardNumber(item.position.range_position_pct, 1)}%`)}</p></div>
              <div class="supply-demand-box"><strong>技術面</strong><p>${escapeHtml(item.technical?.note || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>供需面</strong><p>${escapeHtml(item.supply_demand?.conclusion || item.supply_demand?.demand || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>基本面</strong><p>${escapeHtml(item.fundamental?.turnaround_note || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>判斷理由 ${qualityBadge(item)}</strong><p>${escapeHtml(item.reason || "資料待補")}</p></div>
            </div>
            <p class="risk-note"><strong>風險</strong>${escapeHtml(item.risk || "風險資料待補")}</p>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function lowBaseStockRecord(item) {
  return stockByCode(item?.code);
}

function lowBasePrice(item) {
  const stock = lowBaseStockRecord(item);
  const value = item?.current_price ?? item?.price ?? stock?.close_price ?? stock?.close ?? stock?.price;
  const number = toNumber(value);
  return Number.isFinite(number) ? dashboardNumber(number, 2) : cleanDisplay(value);
}

function lowBaseChangePct(item) {
  const stock = lowBaseStockRecord(item);
  const changeValue = item?.price_change ?? item?.change_value ?? stock?.price_change ?? stock?.change;
  const percentValue = item?.change_percent ?? item?.daily_change ?? item?.five_day_change_pct ?? stock?.change_percent ?? stock?.daily_change;
  const changeNumber = toNumber(changeValue);
  const percentNumber = toNumber(percentValue);
  if (Number.isFinite(changeNumber) && Number.isFinite(percentNumber)) {
    const changeText = `${changeNumber > 0 ? "+" : ""}${changeNumber.toFixed(2)}`;
    return `${changeText} (${dashboardPercent(percentNumber)})`;
  }
  if (Number.isFinite(percentNumber)) return dashboardPercent(percentNumber);
  return cleanDisplay(percentValue);
}

function lowBaseVolume(item) {
  const stock = lowBaseStockRecord(item);
  const value = item?.volume ?? item?.volume_value ?? stock?.volume_value ?? stock?.volume;
  const number = toNumber(value);
  return Number.isFinite(number) ? dashboardNumber(number) : cleanDisplay(value);
}

function lowBaseRevenueMonthLabel(item) {
  const stock = lowBaseStockRecord(item);
  const value = item?.revenue_month ?? stock?.revenue_month ?? stock?.data_version;
  const match = String(value || "").match(/(\d{4})-(\d{1,2})/);
  return match ? `${Number(match[2])}月` : "最新月份";
}

function lowBaseRevenueAmount(item) {
  const stock = lowBaseStockRecord(item);
  const value = item?.current_revenue_million ?? item?.revenue ?? stock?.current_revenue_million ?? stock?.current_revenue;
  const number = toNumber(value);
  return Number.isFinite(number) ? dashboardNumber(number, 2) : cleanDisplay(value);
}

function lowBaseRevenuePercent(item, type) {
  const stock = lowBaseStockRecord(item);
  const fundamental = item?.fundamental || {};
  const value = type === "mom"
    ? (fundamental.revenue_mom ?? item?.revenue_mom ?? stock?.revenue_mom_value ?? stock?.revenue_mom)
    : (fundamental.revenue_yoy ?? item?.revenue_yoy ?? stock?.revenue_yoy_value ?? stock?.revenue_yoy);
  const number = toNumber(value);
  return Number.isFinite(number) ? dashboardPercent(number) : cleanDisplay(value);
}

function lowBaseOptionalMetric(item, keys, options = {}) {
  const stock = lowBaseStockRecord(item);
  const sources = [item, item?.fundamental, stock];
  for (const source of sources) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      const text = String(value ?? "").trim();
      if (text && !["missing", "null", "undefined", "-"].includes(text.toLowerCase())) {
        const number = toNumber(value);
        if (Number.isFinite(number)) {
          if (options.percent) {
            if (options.signed === false) return `${number.toFixed(options.digits ?? 2)}%`;
            return dashboardPercent(number);
          }
          return dashboardNumber(number, options.digits ?? 2);
        }
        return cleanDisplay(value);
      }
    }
  }
  return "資料待補";
}

function renderLowBaseRankingCards(items, market = "上市") {
  const filtered = items
    .filter((item) => market === "全部" || (item.market || "") === market)
    .slice(0, 10);
  if (!filtered.length) return `<div class="empty">低基期題材資料載入失敗，請確認 docs/data/low-base-theme-ranking.json 是否存在。</div>`;
  return `
    <div class="ranking-card-list">
      ${filtered.map((item) => `
        <article class="ranking-card">
          <div class="ranking-card-head">
            <div>
              <span class="theme-rank">#${escapeHtml(item.rank || "")}</span>
              <h3>${radarStockLabelLink(item.code, item.name)}</h3>
              <div class="ranking-submeta">${radarThemeLink(item.theme || "題材待補")}｜${escapeHtml(item.market || "市場別待補")}</div>
            </div>
            <div class="ranking-score"><strong>${escapeHtml(item.score ?? "-")}</strong><span>綜合分數</span></div>
          </div>
          <div class="ranking-stock-metrics">
            <div><span>當天現價</span><strong>${escapeHtml(lowBasePrice(item))}</strong></div>
            <div><span>漲幅%</span><strong>${escapeHtml(lowBaseChangePct(item))}</strong></div>
            <div><span>成交量</span><strong>${escapeHtml(lowBaseVolume(item))}</strong></div>
          </div>
          ${rankingAccordionButton()}
          <div class="ranking-detail">
            <div class="evidence-grid">
              <div class="supply-demand-box"><strong>當月營收(百萬)</strong><p>${escapeHtml(lowBaseRevenueAmount(item))}</p></div>
              <div class="supply-demand-box"><strong>月增率(${escapeHtml(lowBaseRevenueMonthLabel(item))})</strong><p>${escapeHtml(lowBaseRevenuePercent(item, "mom"))}</p></div>
              <div class="supply-demand-box"><strong>年增率(${escapeHtml(lowBaseRevenueMonthLabel(item))})</strong><p>${escapeHtml(lowBaseRevenuePercent(item, "yoy"))}</p></div>
              <div class="supply-demand-box"><strong>毛利率</strong><p>${escapeHtml(lowBaseOptionalMetric(item, ["gross_margin", "gross_margin_value", "gross_margin_pct"], { percent: true, signed: false }))}</p></div>
              <div class="supply-demand-box"><strong>EPS</strong><p>${escapeHtml(lowBaseOptionalMetric(item, ["eps", "eps_value", "latest_eps"], { digits: 2 }))}</p></div>
              <div class="supply-demand-box"><strong>本益比</strong><p>${escapeHtml(lowBaseOptionalMetric(item, ["pe_ratio", "per", "price_earnings_ratio"], { digits: 2 }))}</p></div>
              <div class="supply-demand-box"><strong>法人預估目標價</strong><p>${escapeHtml(lowBaseOptionalMetric(item, ["institutional_target_price", "target_price", "consensus_target_price"], { digits: 2 }))}</p></div>
              <div class="supply-demand-box"><strong>技術面</strong><p>${escapeHtml(item.technical?.note || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>供需面</strong><p>${escapeHtml(item.supply_demand?.conclusion || item.supply_demand?.demand || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>基本面</strong><p>${escapeHtml(item.fundamental?.turnaround_note || "資料待補")}</p></div>
              <div class="supply-demand-box"><strong>判斷理由 ${qualityBadge(item)}</strong><p>${escapeHtml(item.reason || "資料待補")}</p></div>
            </div>
            <p class="risk-note"><strong>風險</strong>${escapeHtml(item.risk || "風險資料待補")}</p>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

async function renderNewsThemeRanking(showAll = false) {
  const root = $("#newsThemeRankingRoot");
  if (!root) return;
  const raw = await loadJson("./data/news-theme-ranking.json", null);
  if (!raw) {
    root.innerHTML = `<div class="empty">新聞題材資料載入失敗，請確認 docs/data/news-theme-ranking.json 是否存在。</div>`;
    return;
  }
  const data = rankingDataItems(raw);
  state.newsThemeRanking = { ...data, available: true };
  const items = data.items
    .slice()
    .sort((a, b) => (Number(b.theme_score) || 0) - (Number(a.theme_score) || 0))
    .slice(0, 10);
  root.innerHTML = `
    <div class="section-title">
      <div>
        <h2>新聞最多題材</h2>
        <p class="mode-note">近五個交易日，依新聞熱度、題材擴散與供需訊號排序</p>
      </div>
      <span>${rankingMetaText(data)}</span>
    </div>
    ${data.source_note ? `<p class="ranking-source-note">${escapeHtml(data.source_note)}</p>` : ""}
    ${items.length ? renderNewsThemeRankingCards(items, showAll) : `<div class="empty">新聞題材資料載入失敗，請確認 docs/data/news-theme-ranking.json 是否存在。</div>`}
  `;
  const toggle = $("#newsThemeToggle");
  if (toggle) toggle.addEventListener("click", () => renderNewsThemeRanking(!showAll));
}

async function renderLowBaseThemeRanking(market = "上市") {
  const root = $("#lowBaseThemeRankingRoot");
  if (!root) return;
  const raw = await loadJson("./data/low-base-theme-ranking.json", null);
  if (!raw) {
    root.innerHTML = `<div class="empty">低基期題材資料載入失敗，請確認 docs/data/low-base-theme-ranking.json 是否存在。</div>`;
    return;
  }
  const data = rankingDataItems(raw);
  state.lowBaseRanking = { ...data, available: true };
  const items = data.items
    .slice()
    .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0));
  root.innerHTML = `
    <div class="section-title">
      <div>
        <h2>低基期題材個股排行</h2>
        <p class="mode-note">從強題材中篩出低位階、剛轉強、具供需催化的個股</p>
      </div>
      <span>${rankingMetaText(data)}</span>
    </div>
    <div class="ranking-toolbar">
      <label>市場別
        <select id="lowBaseMarketFilter">
          ${["全部", "上市", "上櫃"].map((option) => `<option value="${option}" ${option === market ? "selected" : ""}>${option}</option>`).join("")}
        </select>
      </label>
    </div>
    ${data.source_note ? `<p class="ranking-source-note">${escapeHtml(data.source_note)}</p>` : ""}
    ${renderLowBaseRankingCards(items, market)}
  `;
  const select = $("#lowBaseMarketFilter");
  if (select) select.addEventListener("change", (event) => renderLowBaseThemeRanking(event.target.value));
}

function renderRadarOverview() {
  const root = $("#radarOverviewRoot");
  if (!root) return;
  const topTheme = radarTop5ThemeItems()[0];
  const newsTheme = (state.newsThemeRanking?.items || [])[0];
  const lowBase = (state.lowBaseRanking?.items || [])[0];
  const aiTop = state.stocks
    .slice()
    .sort((a, b) => radarScoreValue(b) - radarScoreValue(a))[0];
  const latest = [
    state.themeTop5,
    state.newsThemeRanking,
    state.lowBaseRanking,
    state.hotThemes,
  ].find((data) => data?.available);
  root.innerHTML = `
    <div class="section-title">
      <div>
        <h2>盤勢總覽</h2>
        <p class="mode-note">快速看目前 AI 選股頁的核心排行摘要，切換上方分類可看完整內容。</p>
      </div>
      <span>${latest ? dashboardUpdateText(latest) : "資料待更新"}</span>
    </div>
    <div class="overview-grid">
      <article class="overview-card">
        <span>今日最強主流題材</span>
        <strong>${topTheme ? radarThemeLink(topTheme.theme) : "資料待更新"}</strong>
        <p>${topTheme ? `綜合分數 ${escapeHtml(topTheme.score)}｜${escapeHtml(topTheme.status || "觀察")}` : "請確認 theme-top5.json 是否已產生。"}</p>
      </article>
      <article class="overview-card">
        <span>新聞最多題材第一名</span>
        <strong>${newsTheme ? radarThemeLink(newsTheme.theme) : "資料待更新"}</strong>
        <p>${newsTheme ? `新聞 ${escapeHtml(newsTheme.news_count || 0)} 篇｜分數 ${escapeHtml(newsTheme.theme_score || "-")}` : "請確認 news-theme-ranking.json 是否已產生。"}</p>
      </article>
      <article class="overview-card">
        <span>低基期排行第一名</span>
        <strong>${lowBase ? radarStockLabelLink(lowBase.code, lowBase.name) : "資料待更新"}</strong>
        <p>${lowBase ? `${radarThemeLink(lowBase.theme || "題材待補")}｜分數 ${escapeHtml(lowBase.score || "-")}` : "請確認 low-base-theme-ranking.json 是否已產生。"}</p>
      </article>
      <article class="overview-card">
        <span>AI選股分數最高個股</span>
        <strong>${aiTop ? radarStockLink(aiTop) : "資料待更新"}</strong>
        <p>${aiTop ? `原始排序分數 ${escapeHtml(radarScoreValue(aiTop))}` : "請確認 stocks-latest.json 是否已產生。"}</p>
      </article>
      <article class="overview-card">
        <span>最後更新時間</span>
        <strong>${latest ? dashboardUpdateText(latest) : "資料待更新"}</strong>
        <p>若時間未更新，請重新執行資料產生腳本。</p>
      </article>
    </div>
  `;
}

function activateRadarTab(name, updateHash = true) {
  const fallback = "overview";
  const panelNames = $all(".radar-panel").map((panel) => panel.dataset.radarPanel);
  const target = panelNames.includes(name) ? name : fallback;
  $all(".radar-tab").forEach((tab) => {
    const active = tab.dataset.radarTab === target;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  $all(".radar-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.radarPanel === target);
  });
  if (updateHash && window.location.hash.slice(1) !== target) {
    history.replaceState(null, "", `#${target}`);
  }
}

function initRadarTabs() {
  const tabs = $all(".radar-tab");
  if (!tabs.length) return;
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateRadarTab(tab.dataset.radarTab || "overview"));
  });
  const hash = window.location.hash.replace("#", "");
  activateRadarTab(hash || "overview", Boolean(hash));
  window.addEventListener("hashchange", () => activateRadarTab(window.location.hash.replace("#", "") || "overview", false));
}

function initRankingAccordions() {
  if (rankingAccordionsReady) return;
  rankingAccordionsReady = true;
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".ranking-toggle");
    if (!button) return;
    const card = button.closest(".ranking-card, .theme-top5-card");
    if (!card) return;
    const expanded = card.classList.toggle("is-expanded");
    button.textContent = expanded ? "收合依據" : "展開依據";
  });
}

function radarThemeGroupsTable(groups) {
  if (!groups.length) return `<div class="empty">目前沒有符合搜尋條件的題材</div>`;
  const rows = groups.map((group, index) => `
    <tr>
      <td class="cell-number">${index + 1}</td>
      <td>${radarThemeLink(group.theme)}</td>
      <td class="cell-number">${dashboardNumber(group.avgScore ?? group.score ?? group.count, 0)}</td>
      <td>${radarStockLinks(group.stocks, 5)}</td>
      <td>${escapeHtml((group.reasons || group.events || []).slice(0, 2).join("；") || "依現有資料彙整")}</td>
    </tr>
  `).join("");
  return `
    <div class="table-wrap ai-selection-table-wrap">
      <table class="ai-selection-table">
        <thead><tr><th>排名</th><th>題材</th><th>強度</th><th>代表個股</th><th>判斷依據</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function radarLowBaseTable(stocks) {
  if (!stocks.length) return `<div class="empty">目前沒有符合搜尋條件的低基期觀察股</div>`;
  const rows = stocks.map((stock, index) => {
    const themes = radarThemeList(stock).slice(0, 3).map(radarThemeLink).join("、") || "題材待補";
    return `
      <tr>
        <td class="cell-number">${index + 1}</td>
        <td>${radarStockLink(stock)}</td>
        <td>${themes}</td>
        <td class="cell-number">${escapeHtml(dashboardPercent(stock.revenue_yoy_value))}</td>
        <td class="cell-number">${escapeHtml(dashboardPercent(stock.revenue_mom_value))}</td>
        <td class="cell-number">${escapeHtml(dashboardNumber(stock.volume_value, 0))}</td>
        <td>${escapeHtml(cleanDisplay(stock.reason))}</td>
      </tr>
    `;
  }).join("");
  return `
    <div class="table-wrap ai-selection-table-wrap">
      <table class="ai-selection-table">
        <thead><tr><th>排名</th><th>個股</th><th>相關題材</th><th>營收年增</th><th>營收月增</th><th>成交量</th><th>觀察理由</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function radarNewsThemesTable(groups) {
  if (!groups.length) return `<div class="empty">目前新聞資料尚未形成題材排行</div>`;
  const rows = groups.map((group, index) => `
    <tr>
      <td class="cell-number">${index + 1}</td>
      <td>${radarThemeLink(group.theme)}</td>
      <td class="cell-number">${dashboardNumber(group.count, 0)}</td>
      <td>${radarStockLinks([...group.stocks], 5)}</td>
      <td>${escapeHtml(group.events.slice(0, 2).join("；"))}</td>
    </tr>
  `).join("");
  return `
    <div class="table-wrap ai-selection-table-wrap">
      <table class="ai-selection-table">
        <thead><tr><th>排名</th><th>新聞題材</th><th>出現次數</th><th>相關個股</th><th>代表新聞</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderRadar() {
  renderHeader("radar");
  const main = $("#app");
  const conceptOptions = conceptEntries().map((concept) => `<option value="${escapeHtml(concept.name)}"></option>`).join("");
  main.innerHTML = `
    <nav class="radar-tabs" aria-label="AI選股分類">
      <button class="radar-tab is-active" type="button" data-radar-tab="overview">盤勢總覽</button>
      <button class="radar-tab" type="button" data-radar-tab="themeTop5">五日最強題材</button>
      <button class="radar-tab" type="button" data-radar-tab="newsTheme">新聞最多題材</button>
      <button class="radar-tab" type="button" data-radar-tab="lowBase">低基期排行</button>
      <button class="radar-tab" type="button" data-radar-tab="aiRanking">AI選股清單</button>
    </nav>
    <section class="radar-panel is-active" data-radar-panel="overview">
      <div id="radarOverviewRoot" class="radar-section"></div>
    </section>
    <section class="radar-panel" data-radar-panel="themeTop5">
      <div class="radar-section ai-selection-panel">
        <div class="section-title"><h2>五日內最強題材 TOP 5</h2><span id="themeStockCount"></span></div>
        <p class="mode-note">選出前五強後，拆成新聞面、技術面、漲跌面、資金面、基本面 / 產業催化，讓盤面依據一眼看懂。</p>
        <div id="themeStockList"></div>
      </div>
    </section>
    <section class="radar-panel" data-radar-panel="newsTheme">
      <div id="newsThemeRankingRoot" class="radar-section news-theme-ranking"></div>
    </section>
    <section class="radar-panel" data-radar-panel="lowBase">
      <div id="lowBaseThemeRankingRoot" class="radar-section low-base-theme-ranking"></div>
    </section>
    <section class="radar-panel" data-radar-panel="aiRanking">
      <div class="panel">
        <div class="section-title"><h2>AI選股清單</h2><span>${escapeHtml(`${stockMasterCountText()}｜${radarStageUpdateText()}`)}</span></div>
        <div class="filters">
          <label>股票搜尋<input id="search" placeholder="代號、名稱或概念股，例如 2337、旺宏、CPO"></label>
          <label>題材搜尋<input id="concept" list="conceptOptions" placeholder="AI、PCB、記憶體、玻璃基板..."></label>
        </div>
        <datalist id="conceptOptions">${conceptOptions}</datalist>
        <p class="mode-note">此頁改為題材與低基期觀察清單；股票名稱與市場別以官方上市、上櫃主檔為準，題材與觀察清單則依目前內部雷達資料與新聞題材資料彙整。</p>
      </div>
    </section>
  `;
  renderNewsThemeRanking().then(renderRadarOverview);
  renderLowBaseThemeRanking().then(renderRadarOverview);
  initRadarTabs();
  const render = () => {
    const search = $("#search").value.trim().toLowerCase();
    const concept = $("#concept").value.trim().toLowerCase();
    const top5Themes = radarTop5ThemeItems().filter((item) => {
      const haystack = radarTop5ThemeSearchText(item);
      if (search && !haystack.includes(search)) return false;
      if (concept && !haystack.includes(concept)) return false;
      return true;
    });
    const top5Time = state.themeTop5?.updated_at || state.themeTop5?.date ? `${dashboardUpdateText(state.themeTop5)}｜` : "";
    $("#themeStockCount").textContent = `${top5Time}${top5Themes.length} 組題材`;
    $("#themeStockList").innerHTML = radarTop5ThemeCards(top5Themes);
    renderRadarOverview();
  };
  ["search", "concept"].forEach((id) => $(`#${id}`).addEventListener("input", render));
  render();
}

function eventMarketGroup(event) {
  if (event.market_group) return event.market_group;
  const text = `${event.category || ""} ${(event.related_keywords || []).join(" ")} ${event.title || ""}`.toUpperCase();
  return TECH_THEMES.some((keyword) => text.includes(String(keyword).toUpperCase())) ? "電子股" : "非電子類別";
}

function eventNewsRegion(event) {
  if (event.news_region) return event.news_region;
  return event.region === "國際" ? "國際" : "台股";
}

function renderNews() {
  renderHeader("news");
  const main = $("#app");
  const sections = [
    ["電子股", "國際", "電子股｜國際重大新聞"],
    ["電子股", "台股", "電子股｜台股重大新聞"],
    ["非電子類別", "國際", "非電子類別｜國際重大新聞"],
    ["非電子類別", "台股", "非電子類別｜台股重大新聞"],
  ];
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>重大新聞雷達</h2><span>依市場屬性與新聞地區分區，僅保留摘要、來源與連動分析</span></div>
    </section>
    ${sections.map(([group, region, title]) => `
      <section class="panel">
        <div class="section-title"><h2>${title}</h2><span id="count-${group}-${region}"></span></div>
        <div id="news-${group}-${region}" class="grid"></div>
      </section>
    `).join("")}
  `;
  sections.forEach(([group, region]) => {
    const list = state.news
      .filter((event) => isRealSourceUrl(eventUrl(event)) && eventMarketGroup(event) === group && eventNewsRegion(event) === region)
      .filter((event) => ["高", "中高"].includes(event.event_strength))
      .slice(0, 5);
    const target = $(`#news-${group}-${region}`);
    const count = $(`#count-${group}-${region}`);
    if (count) count.textContent = `${list.length} 則`;
    if (target) target.innerHTML = list.length ? list.map(eventCard).join("") : `<div class="empty">目前沒有此分區新聞</div>`;
  });
}

function newsStrengthTone(strength) {
  if (strength === "高") return "warn";
  if (strength === "中高") return "good";
  return "";
}

function newsImpactTone(impact) {
  if (impact === "偏多") return "good";
  if (impact === "偏空") return "bad";
  return "";
}

function newsStrengthBasis(event) {
  const strength = event?.event_strength || "未標示";
  if (strength === "高") return "高：題材明確、來源有效、相關股票或族群連動較強，可能影響資金方向。";
  if (strength === "中高") return "中高：事件具明確題材連動，但仍需觀察族群擴散、成交量與後續新聞。";
  if (strength === "中") return "中：保留為觀察線索，需等待更多來源、量價或公司資訊確認。";
  return "未標示：資料尚未提供完整強度判斷，僅保留為新聞線索。";
}

function newsImpactBasis(event) {
  const impact = event?.impact || "中性";
  if (impact === "偏多") return "偏多：可能支持需求、報價、訂單、政策、資金流或產業催化。";
  if (impact === "偏空") return "偏空：可能涉及需求降溫、成本壓力、財報、政策或公司風險。";
  return "中性：目前僅確認事件存在，尚不足以判定明確多空。";
}

function sourceHostLabel(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function newsSourceSearchLinks() {
  const sources = [
    ["CMoney 美股快訊", "https://www.cmoney.tw/notes/?tag=76325"],
    ["CMoney 台股即時", "https://www.cmoney.tw/notes/?navId=twstock_news"],
    ["鉅亨美股新聞", "https://news.cnyes.com/news/cat/wd_stock"],
    ["鉅亨台股新聞", "https://news.cnyes.com/news/cat/tw_stock_news"],
    ["MoneyDJ 產業分析", "https://www.moneydj.com/kmdj/common/listnewarticles.aspx?a=X0300000&svc=NW"],
    ["MoneyDJ 即時新聞", "https://www.moneydj.com/KMDJ/News/NewsRealList.aspx?a=MB010000"],
  ];
  return sources.map(([label, href]) => `<a class="news-source-link" href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`).join("");
}

function newsSectionKey(group, region) {
  return `${group}-${region}`.replace(/[^\w\u4e00-\u9fa5-]/g, "-");
}

function eventCard(event) {
  const holdings = new Set(readStoredCodes(HOLDINGS_KEY));
  const related = (event.related_stocks || []).map(normalizeCode).filter(Boolean);
  const radarHits = related.filter((code) => stockByCode(code));
  const holdingHits = related.filter((code) => holdings.has(code));
  const impactTone = newsImpactTone(event.impact);
  const strengthTone = newsStrengthTone(event.event_strength);
  const url = eventUrl(event);
  const hasSource = isRealSourceUrl(url);
  const sourceLabel = event.source_name || sourceHostLabel(url) || "來源未標示";
  const title = event.title || "未命名事件";
  return `
    <article class="card news-card news-event-card" data-region="${escapeHtml(event.region || "")}" data-category="${escapeHtml(event.category || "")}" data-holding-hit="${holdingHits.length ? "1" : "0"}">
      <div class="chip-row">
        ${chip(formatDate(event.date))}
        ${chip(event.region || eventNewsRegion(event) || "地區未標示")}
        ${chip(`題材：${event.category || "未分類"}`)}
        ${chip(`事件強度：${event.event_strength || "未標示"}`, strengthTone)}
        ${chip(`影響方向：${event.impact || "中性"}`, impactTone)}
      </div>
      <h3 class="news-title">
        ${hasSource ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>` : escapeHtml(title)}
      </h3>
      <div class="news-meta">
        <span>來源：${escapeHtml(sourceLabel)}</span>
        ${hasSource ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">查看原文</a>` : `<span>來源待補</span>`}
      </div>
      <div class="news-evidence-grid">
        <div><strong>事件強度依據</strong><p>${escapeHtml(newsStrengthBasis(event))}</p></div>
        <div><strong>影響方向說明</strong><p>${escapeHtml(newsImpactBasis(event))}</p></div>
      </div>
      <p><span class="label">新聞摘要</span>${escapeHtml(event.summary || event.logic || "尚缺摘要")}</p>
      <p class="analysis"><span class="label">題材連動分析</span>${escapeHtml(event.asurada_analysis || event.logic || "尚缺連動分析")}</p>
      <p><span class="label">相關台股</span></p>
      <div class="chip-row">${stockChips(related, "無相關台股")}</div>
      <p><span class="label">雷達命中</span></p>
      <div class="chip-row">${stockChips(radarHits, "未命中今日雷達")}</div>
      <p><span class="label">持股命中</span></p>
      <div class="chip-row">${stockChips(holdingHits, "未命中我的持股")}</div>
    </article>
  `;
}

function renderNews() {
  renderHeader("news");
  const main = $("#app");
  const sections = [
    ["電子股", "國際", "電子股｜國際重大新聞"],
    ["電子股", "台股", "電子股｜台股重大新聞"],
    ["非電子類別", "國際", "非電子類別｜國際重大新聞"],
    ["非電子類別", "台股", "非電子類別｜台股重大新聞"],
  ];
  main.innerHTML = `
    <section class="panel news-radar-intro">
      <div class="section-title">
        <h2>重大新聞雷達</h2>
        <span>每日更新，依國際 / 台股與電子 / 非電子分區整理</span>
      </div>
      <div class="news-rule-grid">
        <div>
          <h3>事件強度怎麼判斷？</h3>
          <p>優先看真實來源、事件明確度、題材關聯股票數、供需 / 報價 / 財報 / 政策訊號，以及是否可能帶動族群資金輪動。高與中高事件會優先出現在本頁。</p>
        </div>
        <div>
          <h3>影響方向怎麼判斷？</h3>
          <p>偏多代表需求、報價、訂單、政策或資金面可能改善；偏空代表需求降溫、成本、財報、政策或公司風險升高；中性代表仍需後續確認。</p>
        </div>
      </div>
      <div class="news-source-panel">
        <strong>新聞搜尋入口</strong>
        <div class="news-source-links">${newsSourceSearchLinks()}</div>
      </div>
    </section>
    ${sections.map(([group, region, title]) => {
      const key = newsSectionKey(group, region);
      return `
        <section class="panel news-section-card">
          <div class="section-title"><h2>${title}</h2><span id="count-${key}"></span></div>
          <div id="news-${key}" class="news-grid"></div>
        </section>
      `;
    }).join("")}
  `;
  sections.forEach(([group, region]) => {
    const key = newsSectionKey(group, region);
    const list = state.news
      .filter((event) => isRealSourceUrl(eventUrl(event)) && eventMarketGroup(event) === group && eventNewsRegion(event) === region)
      .filter((event) => ["高", "中高"].includes(event.event_strength))
      .sort((a, b) => {
        const score = (event) => (event.event_strength === "高" ? 10 : 5) + (isRealSourceUrl(eventUrl(event)) ? 2 : 0);
        return score(b) - score(a) || String(b.date || "").localeCompare(String(a.date || ""));
      })
      .slice(0, 5);
    const target = $(`#news-${key}`);
    const count = $(`#count-${key}`);
    if (count) count.textContent = `${list.length} 則`;
    if (target) target.innerHTML = list.length ? list.map(eventCard).join("") : `<div class="empty">目前沒有此分區新聞</div>`;
  });
}

function isoDateOnly(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const normalized = text.replace(" Asia/Taipei", "").replace(/\//g, "-");
  const match = normalized.match(/(20\d{2})-(\d{1,2})-(\d{1,2})/);
  if (match) {
    const [, year, month, day] = match;
    return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
  }
  const parsed = new Date(text);
  if (!Number.isNaN(parsed.getTime())) return parsed.toISOString().slice(0, 10);
  return "";
}

function explicitNewsDates(event) {
  const text = [event.title, event.summary, event.asurada_analysis].filter(Boolean).join(" ");
  const dates = [];
  const baseYear = isoDateOnly(event.date || state.newsLatestMeta?.updated_at).slice(0, 4) || String(new Date().getFullYear());
  const fullDatePattern = /(20\d{2})[/-](\d{1,2})[/-](\d{1,2})/g;
  const shortDatePattern = /(^|[^\d])(\d{1,2})\/(\d{1,2})(?!\d)/g;
  let match;
  while ((match = fullDatePattern.exec(text)) !== null) {
    dates.push(`${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`);
  }
  while ((match = shortDatePattern.exec(text)) !== null) {
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      dates.push(`${baseYear}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`);
    }
  }
  return [...new Set(dates)].sort((a, b) => b.localeCompare(a));
}

function effectiveNewsDateValue(event) {
  const explicit = explicitNewsDates(event || {});
  return explicit[0] || isoDateOnly(event?.date || event?.updated_at);
}

function newsLatestDateValue() {
  const metaDate = state.newsLatestMeta?.content_latest_at || "";
  if (metaDate) return metaDate;
  const dates = (state.news || [])
    .map((event) => effectiveNewsDateValue(event))
    .filter(Boolean)
    .sort((a, b) => b.localeCompare(a));
  return dates[0] || "";
}

function newsLatestUpdateText() {
  const meta = state.newsLatestMeta || {};
  const latest = meta.updated_at || "";
  const stage = meta.stage_label || meta.stage || "";
  if (!latest) return "每日整理時間：資料尚未更新";
  return `每日整理時間：${formatDashboardTime(latest)}${stage ? `｜本次資料階段：${stage}` : ""}`;
}

function newsContentLatestText() {
  const latest = newsLatestDateValue();
  return latest ? `新聞內容最新日期：${formatDashboardTime(latest)}` : "新聞內容最新日期：資料尚未更新";
}

const NEWS_UPDATE_SCHEDULE = [
  ["00:00", "夜間更新"],
  ["08:07", "盤前更新"],
  ["11:07", "盤中更新"],
  ["13:37", "收盤更新"],
  ["17:07", "盤後籌碼"],
  ["19:07", "晚間總結"],
];

function newsUpdateScheduleHtml() {
  const meta = state.newsLatestMeta || {};
  const currentTime = String(meta.schedule_time || "");
  const currentStage = String(meta.stage_label || meta.stage || "");
  return `
    <div class="news-schedule-box" aria-label="重大新聞定時更新表">
      <div class="news-schedule-heading">
        <strong>定時更新</strong>
        <span>Asia/Taipei，實際內容以新聞來源成功抓取時間為準</span>
      </div>
      <div class="news-schedule-list">
        ${NEWS_UPDATE_SCHEDULE.map(([time, label]) => {
          const isCurrent = currentTime === time || currentStage === label;
          return `<span class="news-schedule-item ${isCurrent ? "is-current" : ""}"><b>${time}</b>${label}</span>`;
        }).join("")}
      </div>
    </div>
  `;
}

function newsFreshnessWarningText() {
  const meta = state.newsLatestMeta || {};
  if (meta.stale) {
    return meta.stale_reason || "新聞來源目前未取得新資料，以下為上次成功取得的新聞。";
  }
  const packageDate = isoDateOnly(meta.updated_at);
  const contentDate = newsLatestDateValue();
  if (!packageDate || !contentDate || contentDate >= packageDate) return "";
  return `提醒：目前新聞來源內容最新日期為 ${formatDashboardTime(contentDate)}，但資料檔整理時間為 ${formatDashboardTime(meta.updated_at)}；代表排程已執行，但來源尚未抓到同日新聞。`;
}

function newsImportanceScore(event) {
  const strength = event.event_strength === "高" ? 40 : event.event_strength === "中高" ? 28 : event.event_strength === "中" ? 14 : 0;
  const source = isRealSourceUrl(eventUrl(event)) ? 15 : 0;
  const stocks = Math.min((event.related_stocks || []).length, 8) * 3;
  const keywords = Math.min((event.related_keywords || []).length, 10);
  const impact = event.impact && event.impact !== "中性" ? 8 : 0;
  return strength + source + stocks + keywords + impact;
}

function newsAccordionItem(event, index) {
  const related = (event.related_stocks || []).map(normalizeCode).filter(Boolean);
  const url = eventUrl(event);
  const hasSource = isRealSourceUrl(url);
  const sourceLabel = event.source_name || sourceHostLabel(url) || "來源未標示";
  const title = event.title || "未命名事件";
  const impactTone = newsImpactTone(event.impact);
  const strengthTone = newsStrengthTone(event.event_strength);
  return `
    <details class="news-accordion-item">
      <summary>
        <span class="news-rank">#${index + 1}</span>
        <span class="news-summary-main">
          <span class="news-summary-title">
            ${hasSource ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>` : escapeHtml(title)}
          </span>
          <span class="news-summary-meta">
            ${escapeHtml(formatDate(effectiveNewsDateValue(event) || event.date))} · ${escapeHtml(sourceLabel)} · ${escapeHtml(event.category || "未分類")}
          </span>
        </span>
        <span class="news-summary-tags">
          <span class="chip ${strengthTone}">強度：${escapeHtml(event.event_strength || "未標示")}</span>
          <span class="chip ${impactTone}">方向：${escapeHtml(event.impact || "中性")}</span>
        </span>
      </summary>
      <div class="news-accordion-body">
        <div class="news-evidence-grid">
          <div><strong>事件強度依據</strong><p>${escapeHtml(newsStrengthBasis(event))}</p></div>
          <div><strong>影響方向說明</strong><p>${escapeHtml(newsImpactBasis(event))}</p></div>
        </div>
        <p><span class="label">新聞摘要</span>${escapeHtml(event.summary || event.logic || "尚缺摘要")}</p>
        <p class="analysis"><span class="label">題材連動分析</span>${escapeHtml(event.asurada_analysis || event.logic || "尚缺連動分析")}</p>
        <p><span class="label">相關台股</span></p>
        <div class="chip-row">${stockChips(related, "無相關台股")}</div>
        <div class="button-row">
          ${hasSource ? `<a class="solid-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">查看原文</a>` : `<span class="chip">來源待補</span>`}
        </div>
      </div>
    </details>
  `;
}

function sortedNewsItems(items) {
  return items
    .slice()
    .sort((a, b) => {
      const dateOrder = String(effectiveNewsDateValue(b) || b.date || "").localeCompare(String(effectiveNewsDateValue(a) || a.date || ""));
      return dateOrder || newsImportanceScore(b) - newsImportanceScore(a);
    });
}

function newsPassesFilter(event, filter) {
  if (!isRealSourceUrl(eventUrl(event))) return false;
  const region = eventNewsRegion(event);
  const impact = String(event.impact || "");
  if (filter === "positive") return impact.includes("偏多");
  if (filter === "negative") return impact.includes("偏空");
  if (filter === "taiwan") return region === "台股";
  if (filter === "international") return region === "國際";
  return true;
}

function newsWithinRecentDays(event, days = 5) {
  const date = effectiveNewsDateValue(event);
  const baseDate = isoDateOnly(state.newsLatestMeta?.updated_at || state.newsLatestMeta?.content_latest_at || new Date().toISOString());
  if (!date || !baseDate) return false;
  const eventTime = Date.parse(`${date}T00:00:00+08:00`);
  const baseTime = Date.parse(`${baseDate}T00:00:00+08:00`);
  if (Number.isNaN(eventTime) || Number.isNaN(baseTime)) return false;
  const diffDays = (baseTime - eventTime) / 86400000;
  return diffDays >= 0 && diffDays <= days;
}

function majorNewsForRegion(region) {
  const base = state.news.filter((event) => isRealSourceUrl(eventUrl(event)) && eventNewsRegion(event) === region && newsWithinRecentDays(event, 5));
  const primary = sortedNewsItems(base.filter((event) => ["高", "中高"].includes(event.event_strength)));
  const fallback = sortedNewsItems(base.filter((event) => event.event_strength === "中"));
  const selected = primary.slice();
  const seen = new Set(selected.map((event) => eventUrl(event) || event.title || ""));
  fallback.forEach((event) => {
    const key = eventUrl(event) || event.title || "";
    if (selected.length < 5 && !seen.has(key)) {
      selected.push(event);
      seen.add(key);
    }
  });
  return sortedNewsItems(selected).slice(0, 5);
}

function renderNewsLists(filter = "major") {
  const sections = [
    ["國際", "國際重大新聞"],
    ["台股", "台股重大新聞"],
  ];
  const globalList = filter === "major"
    ? []
    : sortedNewsItems(state.news.filter((event) => newsPassesFilter(event, filter))).slice(0, 30);
  sections.forEach(([region]) => {
    const key = newsSectionKey("all", region);
    const list = filter === "major"
      ? majorNewsForRegion(region)
      : globalList.filter((event) => eventNewsRegion(event) === region);
    const target = $(`#news-${key}`);
    const count = $(`#count-${key}`);
    if (count) count.textContent = `${list.length} 則`;
    if (target) {
      target.innerHTML = list.length
        ? list.map(newsAccordionItem).join("")
        : `<div class="empty">${filter === "major" ? "目前沒有高 / 中高新聞，且沒有可補位的中強度新聞" : "目前沒有符合此篩選的新聞"}</div>`;
    }
  });
}

function renderNews() {
  renderHeader("news");
  const main = $("#app");
  const sections = [
    ["國際", "國際重大新聞"],
    ["台股", "台股重大新聞"],
  ];
  const filters = [
    ["major", "重大新聞"],
    ["all", "全部新聞"],
    ["positive", "偏多"],
    ["negative", "偏空"],
    ["taiwan", "台股"],
    ["international", "國際"],
  ];
  main.innerHTML = `
    <section class="panel news-radar-intro compact">
      <div class="section-title">
        <h2>重大新聞雷達</h2>
        <span>${newsLatestUpdateText()}</span>
      </div>
      <p class="muted">${newsContentLatestText()}</p>
      ${newsFreshnessWarningText() ? `<div class="empty">${escapeHtml(newsFreshnessWarningText())}</div>` : ""}
      ${newsUpdateScheduleHtml()}
      <div class="news-filter-tabs" role="tablist" aria-label="新聞篩選">
        ${filters.map(([key, label], index) => `<button class="news-filter-btn ${index === 0 ? "is-active" : ""}" type="button" data-news-filter="${key}">${label}</button>`).join("")}
      </div>
      <div class="news-rule-grid">
        <div>
          <h3>事件強度依據</h3>
          <p>依真實來源、事件明確度、題材關聯股票數、供需 / 報價 / 財報 / 政策訊號與族群資金輪動排序。重大新聞預設每區 5 則；若沒有高 / 中高，會補上最新中強度新聞。</p>
        </div>
        <div>
          <h3>影響方向說明</h3>
          <p>偏多代表需求、報價、訂單、政策或資金面可能改善；偏空代表風險升高；中性代表仍需後續確認。</p>
        </div>
      </div>
      <div class="news-source-panel compact">
        <strong>新聞搜尋入口</strong>
        <div class="news-source-links">${newsSourceSearchLinks()}</div>
      </div>
    </section>
    ${sections.map(([region, title]) => {
      const key = newsSectionKey("all", region);
      return `
        <section class="panel news-section-card">
          <div class="section-title"><h2>${title}</h2><span id="count-${key}"></span></div>
          <div id="news-${key}" class="news-accordion-list"></div>
        </section>
      `;
    }).join("")}
  `;
  renderNewsLists("major");
  document.querySelectorAll(".news-filter-btn").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".news-filter-btn").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      renderNewsLists(button.dataset.newsFilter || "major");
    });
  });
}

function themeEntries() {
  return Object.entries(state.themes).map(([key, theme]) => ({
    theme_name: theme.theme_name || theme.name || key,
    aliases: theme.aliases || [],
    keywords: theme.keywords || [],
    related_stocks: theme.related_stocks || [],
    source_links: theme.source_links || [],
    description: theme.description || "",
  }));
}

function renderThemes() {
  renderHeader("themes");
  const main = $("#app");
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>題材概念股已整併至概念股資料庫</h2><span>避免兩個頁面資料不一致</span></div>
      <p>概念股清單、外部參考來源、今日雷達命中與持股命中，統一放在「概念股資料庫」。</p>
      <div class="button-row">
        <a class="solid-link" href="concepts.html">前往概念股資料庫</a>
        <a class="solid-link ghost" href="radar.html">回到全股雷達</a>
      </div>
    </section>
  `;
}

function themeCard(theme) {
  const holdings = new Set(readStoredCodes(HOLDINGS_KEY));
  const related = (theme.related_stocks || []).map(normalizeCode).filter(Boolean);
  const radarHits = related.filter((code) => stockByCode(code));
  const holdingHits = related.filter((code) => holdings.has(code));
  return `
    <article class="card theme-card">
      <h3>${escapeHtml(theme.theme_name)}</h3>
      <p class="muted">${escapeHtml(theme.description || `${theme.theme_name} 相關題材`)}</p>
      <p><span class="label">分類</span>${escapeHtml(theme.group || "未分類")}</p>
      <p><span class="label">別名</span>${escapeHtml((theme.aliases || []).join("、") || "-")}</p>
      <p><span class="label">關鍵字</span>${escapeHtml((theme.keywords || []).join("、") || "-")}</p>
      <p><span class="label">相關個股清單</span></p>${conceptStockTable(theme)}
    </article>
  `;
}

function sourceLinksHtml(links) {
  const fallback = [{ name: "MoneyDJ 概念股參考", url: "https://www.moneydj.com/z/zg/zge/zge_E_E.djhtm" }];
  const valid = (links && links.length ? links : fallback).filter((link) => isRealSourceUrl(typeof link === "string" ? link : link.url));
  return `<div class="button-row">${valid.map((link) => {
    const href = typeof link === "string" ? link : link.url;
    const label = typeof link === "string" ? "參考來源" : (link.name || "參考來源");
    return `<a class="solid-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
  }).join("")}</div>`;
}

function conceptStockTable(concept) {
  const holdings = new Set([...readStoredCodes(HOLDINGS_KEY), ...readStoredCodes(WATCHLIST_KEY)]);
  const related = (concept.related_stocks || []).map(normalizeCode).filter(Boolean);
  if (!related.length) {
    return `
      <div class="empty">內部概念股清單待補，請查看外部參考來源</div>
    `;
  }
  return `
    <div class="table-wrap">
      <table class="concept-stock-table">
        <thead><tr><th>股票名稱</th><th>收盤價</th><th>漲跌</th><th>漲跌幅</th><th>成交量</th><th>今日雷達命中</th><th>持股命中</th></tr></thead>
        <tbody>
          ${related.map((code) => {
            const stock = stockByCode(code);
            const radarHit = Boolean(stock);
            const holdingHit = holdings.has(code);
            return `<tr>
              <td><a class="stock-link" href="stock.html?code=${encodeURIComponent(code)}">${escapeHtml(stockLabel(code))}</a></td>
              <td>${escapeHtml(stock ? displayClose(stock) : "-")}</td>
              <td>${escapeHtml(stock?.price_change || stock?.change || "-")}</td>
              <td>${escapeHtml(stock?.daily_change || stock?.change_percent || "-")}</td>
              <td>${escapeHtml(stock ? displayVolume(stock) : "-")}</td>
              <td>${radarHit ? "是" : "否"}</td>
              <td>${holdingHit ? "是" : "否"}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function renderConcepts() {
  renderHeader("concepts");
  const main = $("#app");
  main.innerHTML = `<section class="panel"><div class="section-title"><h2>概念股資料庫</h2><span>MoneyDJ 概念分類載入中...</span></div></section>`;
  let categories = [];
  let stocks = [];
  try {
    [categories, stocks] = await Promise.all([
      loadCsv("data/moneydj_concept_categories.csv"),
      loadCsv("data/moneydj_concept_stocks.csv"),
    ]);
  } catch (error) {
    main.innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>概念股資料庫</h2><span>MoneyDJ CSV 載入失敗</span></div>
        <div class="error">無法載入 data/moneydj_concept_categories.csv 或 data/moneydj_concept_stocks.csv，請先執行 MoneyDJ 抓取腳本。</div>
      </section>
    `;
    console.warn("MoneyDJ CSV load failed", error);
    return;
  }
  categories = categories
    .filter((row) => row.concept_code && row.concept_name)
    .sort((a, b) => toNumber(a.display_order) - toNumber(b.display_order));
  stocks = stocks
    .filter((row) => row.concept_code && row.stock_id)
    .sort((a, b) =>
      toNumber(a.display_order) - toNumber(b.display_order) ||
      toNumber(a.stock_order) - toNumber(b.stock_order)
    );
  if (!categories.length) {
    main.innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>概念股資料庫</h2><span>MoneyDJ CSV 無分類資料</span></div>
        <div class="error">moneydj_concept_categories.csv 沒有可顯示的概念分類。</div>
      </section>
    `;
    return;
  }
  const selectOptions = categories.map((concept) =>
    `<option value="${escapeHtml(concept.concept_code)}">${escapeHtml(concept.display_order)}. ${escapeHtml(concept.concept_name)}</option>`
  ).join("");
  const suggestions = categories.map((concept) => `<option value="${escapeHtml(concept.concept_name)}"></option>`).join("");
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>概念股資料庫</h2><span>資料來源：MoneyDJ，依原始 display_order 排序</span></div>
      <div class="filters">
        <label>概念分類<select id="conceptSelect">${selectOptions}</select></label>
        <label>可搜尋下拉框<input id="conceptSearch" list="conceptSuggestions" placeholder="AI、Apple、CoWoS、Google TPU、HDI、IC基板、眼鏡"></label>
      </div>
      <datalist id="conceptSuggestions">${suggestions}</datalist>
      <p class="muted">目前個股 CSV 先完成最小驗收：只含第一個概念 EH001276。其他概念會顯示「尚未抓取」。</p>
    </section>
    <section id="conceptResult"></section>
  `;
  const render = () => {
    const query = $("#conceptSearch").value.trim();
    const selectedCode = $("#conceptSelect").value;
    const filtered = query
      ? categories.filter((concept) => {
        const text = `${concept.concept_code} ${concept.concept_name}`.toLowerCase();
        return text.includes(query.toLowerCase());
      })
      : categories.filter((concept) => concept.concept_code === selectedCode);
    $("#conceptResult").innerHTML = filtered.length
      ? filtered.map((concept) => moneyDjConceptCard(concept, stocks)).join("")
      : `<div class="empty">找不到符合條件的 MoneyDJ 概念分類</div>`;
  };
  $("#conceptSearch").addEventListener("input", render);
  $("#conceptSelect").addEventListener("change", () => {
    $("#conceptSearch").value = "";
    render();
  });
  render();
}

function moneyDjConceptCard(concept, stocks) {
  const conceptStocks = stocks.filter((stock) => stock.concept_code === concept.concept_code);
  return `
    <article class="card theme-card">
      <div class="section-title">
        <h3>${escapeHtml(concept.concept_name)}</h3>
        ${chip(concept.concept_code)}
      </div>
      <div class="grid cols-4">
        <div class="metric"><span>概念代碼</span><strong>${escapeHtml(concept.concept_code)}</strong></div>
        <div class="metric"><span>原始排序</span><strong>${escapeHtml(concept.display_order)}</strong></div>
        <div class="metric"><span>個股數量</span><strong>${conceptStocks.length} 檔</strong></div>
        <div class="metric"><span>更新日期</span><strong>${escapeHtml(concept.updated_at || "-")}</strong></div>
      </div>
      ${moneyDjStockTable(conceptStocks)}
    </article>
  `;
}

function moneyDjStockTable(stocks) {
  if (!stocks.length) {
    return `<div class="empty">此概念個股尚未抓取，請先執行下一階段 MoneyDJ 全量個股抓取。</div>`;
  }
  return `
    <div class="table-wrap">
      <table class="concept-stock-table">
        <thead><tr><th>順序</th><th>股票代號</th><th>股票名稱</th><th>更新日期</th></tr></thead>
        <tbody>
          ${stocks.map((stock) => `
            <tr>
              <td>${escapeHtml(stock.stock_order)}</td>
              <td><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.stock_id)}">${escapeHtml(stock.stock_id)}</a></td>
              <td><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.stock_id)}">${escapeHtml(stock.stock_name)}</a></td>
              <td>${escapeHtml(stock.updated_at || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function conceptCard(concept) {
  return `
    <article class="card theme-card">
      <div class="section-title"><h3>${escapeHtml(concept.name)}</h3>${chip(concept.group || "未分類")}</div>
      <p class="muted">${escapeHtml(concept.description || `${concept.name} 相關概念`)}</p>
      <p><span class="label">來源狀態</span>${escapeHtml(concept.source_status || "來源狀態未標示")}</p>
      <p><span class="label">別名</span>${escapeHtml((concept.aliases || []).join("、") || "-")}</p>
      <p><span class="label">關鍵字</span>${escapeHtml((concept.keywords || []).join("、") || "-")}</p>
      <p><span class="label">相關個股</span></p>
      ${conceptStockTable(concept)}
      <p><span class="label">來源參考連結</span></p>${sourceLinksHtml(concept.source_links || [])}
    </article>
  `;
}

function asuradaStance(stock) {
  const score = toNumber(stock.score);
  const mom = toNumber(stock.revenue_mom);
  const volume = toNumber(stock.volume);
  if (volume > 50000) return "過熱不追";
  if (score >= 70 && mom > 0) return "偏多觀察";
  if (score >= 55) return "等回測";
  return "轉弱觀察";
}

function revenueAmountText(value) {
  if (value === null || value === undefined || String(value).trim() === "") return "—";
  const number = toNumber(value);
  return Number.isFinite(number)
    ? number.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";
}

function revenuePercentText(value) {
  if (value === null || value === undefined || String(value).trim() === "") return "—";
  const number = toNumber(value);
  if (!Number.isFinite(number)) return "—";
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function revenueMonthDisplay(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})$/);
  return match ? `${match[1]}/${match[2]}` : "—";
}

function revenueVerificationLinks(code) {
  const normalized = normalizeCode(code);
  if (!normalized) return "";
  const safeCode = encodeURIComponent(normalized);
  const links = [
    ["Yahoo 營收財報", `https://tw.stock.yahoo.com/quote/${safeCode}.TW/revenue`],
    ["Goodinfo 月營收", `https://goodinfo.tw/tw/ShowSaleMonChart.asp?STOCK_ID=${safeCode}`],
    ["Goodinfo 經營績效", `https://goodinfo.tw/tw/StockBzPerformance.asp?STOCK_ID=${safeCode}`],
  ];
  return `
    <div class="revenue-verify">
      <span class="label">外部查證</span>
      <div class="button-row">
        ${links.map(([label, href]) => `<a class="solid-link" href="${href}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`).join("")}
      </div>
    </div>
  `;
}

function monthlyRevenueTable(rows) {
  return `
    <div class="table-wrap revenue-table-wrap">
      <table class="revenue-table">
        <thead><tr><th>月份</th><th>當月營收(百萬)</th><th>月增率</th><th>年增率</th><th>累計營收(百萬)</th><th>累計年增率</th></tr></thead>
        <tbody>${rows.map((row) => `
          <tr>
            <td data-label="月份">${escapeHtml(revenueMonthDisplay(row.revenue_month))}</td>
            <td data-label="當月營收(百萬)">${escapeHtml(revenueAmountText(row.revenue))}</td>
            <td data-label="月增率">${escapeHtml(revenuePercentText(row.mom_pct))}</td>
            <td data-label="年增率">${escapeHtml(revenuePercentText(row.yoy_pct))}</td>
            <td data-label="累計營收(百萬)">${escapeHtml(revenueAmountText(row.cumulative_revenue))}</td>
            <td data-label="累計年增率">${escapeHtml(revenuePercentText(row.cumulative_yoy_pct))}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    </div>
  `;
}

function quarterlyRevenueTable(rows) {
  return `
    <div class="table-wrap revenue-table-wrap">
      <table class="revenue-table">
        <thead><tr><th>季度</th><th>季營收(百萬)</th><th>季增率</th><th>年增率</th><th>累計營收(百萬)</th><th>累計年增率</th><th>狀態</th></tr></thead>
        <tbody>${rows.map((row) => `
          <tr>
            <td data-label="季度">${escapeHtml(String(row.quarter || "—").replace("-", " "))}</td>
            <td data-label="季營收(百萬)">${escapeHtml(revenueAmountText(row.quarter_revenue))}</td>
            <td data-label="季增率">${escapeHtml(revenuePercentText(row.qoq_pct))}</td>
            <td data-label="年增率">${escapeHtml(revenuePercentText(row.yoy_pct))}</td>
            <td data-label="累計營收(百萬)">${escapeHtml(revenueAmountText(row.cumulative_revenue))}</td>
            <td data-label="累計年增率">${escapeHtml(revenuePercentText(row.cumulative_yoy_pct))}</td>
            <td data-label="狀態">${row.is_partial === "true" ? chip("尚未完整", "warn") : chip("完整")}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    </div>
  `;
}

function revenuePanel(code) {
  if (!state.revenueLoaded) {
    return `<section class="panel"><div class="section-title"><h2>營收表</h2></div><div class="empty">營收資料載入中...</div></section>`;
  }
  if (state.revenueError) {
    return `<section class="panel"><div class="section-title"><h2>營收表</h2></div><div class="error">${escapeHtml(state.revenueError)}</div>${revenueVerificationLinks(code)}</section>`;
  }
  const normalized = normalizeCode(code);
  const monthly = state.monthlyRevenue
    .filter((row) => normalizeCode(row.stock_id) === normalized)
    .sort((a, b) => String(b.revenue_month).localeCompare(String(a.revenue_month)));
  const quarterly = state.quarterlyRevenue
    .filter((row) => normalizeCode(row.stock_id) === normalized)
    .sort((a, b) => String(b.quarter).localeCompare(String(a.quarter)));
  if (!monthly.length) {
    return `<section class="panel"><div class="section-title"><h2>營收表</h2></div><div class="empty">此股票目前沒有可用營收資料。</div>${revenueVerificationLinks(code)}</section>`;
  }
  const latest = monthly[0];
  return `
    <section class="panel revenue-panel" data-revenue-code="${escapeHtml(normalized)}">
      <div class="section-title"><h2>營收表</h2><span>資料來源：${escapeHtml(latest.source || "公開資訊觀測站")}</span></div>
      <div class="grid cols-3 revenue-summary">
        <div class="metric"><span>最新月份</span><strong>${escapeHtml(revenueMonthDisplay(latest.revenue_month))}</strong></div>
        <div class="metric"><span>當月營收</span><strong>${escapeHtml(revenueAmountText(latest.revenue))} 百萬</strong></div>
        <div class="metric"><span>月增率</span><strong>${escapeHtml(revenuePercentText(latest.mom_pct))}</strong></div>
        <div class="metric"><span>年增率</span><strong>${escapeHtml(revenuePercentText(latest.yoy_pct))}</strong></div>
        <div class="metric"><span>累計營收</span><strong>${escapeHtml(revenueAmountText(latest.cumulative_revenue))} 百萬</strong></div>
        <div class="metric"><span>累計年增率</span><strong>${escapeHtml(revenuePercentText(latest.cumulative_yoy_pct))}</strong></div>
      </div>
      <div class="revenue-tabs" role="tablist" aria-label="營收表切換">
        <button type="button" class="revenue-tab active" data-revenue-mode="monthly" role="tab" aria-selected="true">月營收</button>
        <button type="button" class="revenue-tab secondary" data-revenue-mode="quarterly" role="tab" aria-selected="false">季營收</button>
      </div>
      <div class="revenue-view" data-revenue-view="monthly">${monthlyRevenueTable(monthly)}</div>
      <div class="revenue-view" data-revenue-view="quarterly" hidden>${quarterly.length ? quarterlyRevenueTable(quarterly) : `<div class="empty">此股票目前沒有可用季營收資料。</div>`}</div>
      ${revenueVerificationLinks(code)}
    </section>
  `;
}

function bindRevenueTabs() {
  $all(".revenue-tab").forEach((button) => {
    button.addEventListener("click", () => {
      const mode = button.dataset.revenueMode;
      $all(".revenue-tab").forEach((tab) => {
        const active = tab.dataset.revenueMode === mode;
        tab.classList.toggle("active", active);
        tab.classList.toggle("secondary", !active);
        tab.setAttribute("aria-selected", String(active));
      });
      $all(".revenue-view").forEach((view) => {
        view.hidden = view.dataset.revenueView !== mode;
      });
    });
  });
}

function renderStock() {
  renderHeader("stock");
  const params = new URLSearchParams(location.search);
  const initialCode = normalizeCode(params.get("code") || "");
  const main = $("#app");
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>個股查詢</h2></div>
      <div class="filters stock-search-form"><label>股票代號 / 名稱<input id="stockSearch" value="${escapeHtml(initialCode)}" placeholder="請輸入股票代號或名稱"></label></div>
    </section>
    <section id="stockResult"></section>
  `;
  const render = () => {
    const query = $("#stockSearch").value;
    const code = resolveStockQuery(query);
    const stock = stockByCode(code);
    const name = displayStockName(code);
    if (!String(query || "").trim()) {
      $("#stockResult").innerHTML = `<div class="empty">請輸入股票代號或名稱</div>`;
      return;
    }
    if (!code) {
      $("#stockResult").innerHTML = `<div class="empty">找不到此股票代號或名稱，請確認是否輸入錯誤。</div>`;
      return;
    }
    if (!knownStock(code)) {
      $("#stockResult").innerHTML = `<div class="empty">找不到此股票代號或名稱，請確認是否輸入錯誤。</div>`;
      return;
    }
    const record = masterRecord(code);
    const updateText = stockUpdateText(stock, record);
    if (!stock) {
      $("#stockResult").innerHTML = `
        <section class="panel">
          <div class="section-title"><h2>${escapeHtml(code)} ${escapeHtml(name)}</h2><span>更新日期：${escapeHtml(updateText)}</span>${chip("今日未入選雷達", "warn")}</div>
          ${stockMasterDetail(code, stock)}
          <p class="muted">尚無內部雷達資料。</p>
        </section>
        ${revenuePanel(code)}
        <section class="panel"><div class="section-title"><h2>技術圖表</h2></div>${externalLinks(code)}</section>
      `;
      bindRevenueTabs();
      if (!state.revenueLoaded) {
        loadRevenueHistory().then(() => {
          if (resolveStockQuery($("#stockSearch")?.value) === code) render();
        });
      }
      return;
    }
    const relatedNews = state.news.filter((event) => (event.related_stocks || []).map(normalizeCode).includes(code));
    const relatedThemes = themeEntries().filter((theme) => (theme.related_stocks || []).map(normalizeCode).includes(code));
    const tech = state.technical[code];
    $("#stockResult").innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>${escapeHtml(code)} ${escapeHtml(name)}</h2><span>更新日期：${escapeHtml(updateText)}</span>${chip("命中今日雷達", "good")}</div>
        ${stockMasterDetail(code, stock)}
        ${stockRadarDetail(stock)}
      </section>
      ${revenuePanel(code)}
      <section class="panel"><div class="section-title"><h2>技術圖表</h2></div>${externalLinks(code)}</section>
      <section class="panel"><div class="section-title"><h2>相關重大新聞</h2></div>${relatedNews.length ? relatedNews.map(eventCard).join("") : `<div class="empty">目前沒有該股相關重大新聞</div>`}</section>
      <section class="panel"><div class="section-title"><h2>相關題材</h2></div><div class="chip-row">${relatedThemes.length ? relatedThemes.map((x) => chip(x.theme_name)).join("") : chip("暫無題材對應")}</div></section>
      <section class="panel"><div class="section-title"><h2>技術面欄位</h2></div>${tech ? `<pre>${escapeHtml(JSON.stringify(tech, null, 2))}</pre>` : `<div class="empty">技術面資料尚未建立</div>`}</section>
    `;
    bindRevenueTabs();
    if (!state.revenueLoaded) {
      loadRevenueHistory().then(() => {
        if (resolveStockQuery($("#stockSearch")?.value) === code) render();
      });
    }
  };
  $("#stockSearch").addEventListener("input", render);
  render();
  if (!state.stockConceptsLoaded) {
    loadStockConceptsIndex().then(() => {
      const input = $("#stockSearch");
      if (input && String(input.value || "").trim()) render();
    });
  }
}

function moneyText(value, digits = 0) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString("zh-TW", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signedMoneyText(value, digits = 0) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : ""}${moneyText(number, digits)}`;
}

function signedPercentText(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function safeNumber(value, fallback = 0) {
  const number = toNumber(value);
  return Number.isFinite(number) ? number : fallback;
}

function portfolioHoldingMetrics(holding, totalValue) {
  const shares = Math.max(0, safeNumber(holding.shares));
  const avgCost = safeNumber(holding.avg_cost);
  const currentPrice = safeNumber(holding.current_price);
  const cost = shares * avgCost;
  const marketValue = shares * currentPrice;
  const pnl = marketValue - cost;
  const pnlPct = cost > 0 ? (pnl / cost) * 100 : NaN;
  const weight = totalValue > 0 ? (marketValue / totalValue) * 100 : 0;
  return { shares, avgCost, currentPrice, cost, marketValue, pnl, pnlPct, weight };
}

function portfolioFromStorage(basePortfolio) {
  try {
    const raw = localStorage.getItem(PORTFOLIO_STORAGE_KEY);
    if (!raw) return basePortfolio;
    const stored = JSON.parse(raw);
    if (!stored || !Array.isArray(stored.holdings)) return basePortfolio;
    return {
      ...basePortfolio,
      ...stored,
      cash: Math.max(0, safeNumber(stored.cash, basePortfolio.cash || 0)),
      holdings: stored.holdings,
      updated_at: stored.updated_at || basePortfolio.updated_at,
      source: "localStorage",
    };
  } catch (error) {
    console.warn("portfolio localStorage 讀取失敗", error);
    return basePortfolio;
  }
}

function savePortfolioDraft(portfolio) {
  try {
    localStorage.setItem(PORTFOLIO_STORAGE_KEY, JSON.stringify({
      cash: Math.max(0, safeNumber(portfolio.cash)),
      updated_at: new Date().toISOString().slice(0, 10),
      holdings: Array.isArray(portfolio.holdings) ? portfolio.holdings : [],
    }));
    return true;
  } catch (error) {
    console.warn("portfolio localStorage 寫入失敗", error);
    return false;
  }
}

function portfolioStatus(weight) {
  if (weight >= 40) return { text: "過度集中", tone: "warn" };
  if (weight >= 25) return { text: "主力持股", tone: "good" };
  if (weight >= 10) return { text: "中等部位", tone: "" };
  return { text: "觀察部位", tone: "" };
}

function portfolioStockLink(holding) {
  const code = normalizeCode(holding.symbol || holding.code);
  const name = holding.name || displayStockName(code);
  return code ? `<a class="stock-link" href="stock.html?code=${encodeURIComponent(code)}">${escapeHtml(code)}</a>` : "-";
}

function portfolioActionButtons(holding) {
  const code = normalizeCode(holding.symbol || holding.code);
  const name = holding.name || displayStockName(code);
  const price = safeNumber(holding.current_price);
  const label = `${code} ${name}`.trim();
  return `
    <div class="portfolio-row-actions">
      <button type="button" class="portfolio-row-action" data-portfolio-action="buy" data-symbol="${escapeHtml(code)}" data-label="${escapeHtml(label)}" data-price="${escapeHtml(price)}">加碼</button>
      <button type="button" class="portfolio-row-action is-sell" data-portfolio-action="sell" data-symbol="${escapeHtml(code)}" data-label="${escapeHtml(label)}" data-price="${escapeHtml(price)}">減碼</button>
    </div>
  `;
}

function portfolioAllocationBar(label, percent, tone = "") {
  const safePercent = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0));
  return `
    <div class="allocation-row">
      <div class="allocation-label"><strong>${escapeHtml(label)}</strong><span>${safePercent.toFixed(2)}%</span></div>
      <div class="allocation-track"><span class="${tone}" style="width:${safePercent.toFixed(2)}%"></span></div>
    </div>
  `;
}

function portfolioSummaryCards(summary) {
  const cards = [
    ["現金餘額", moneyText(summary.cash)],
    ["股票總成本", moneyText(summary.totalCost)],
    ["股票目前總市值", moneyText(summary.totalMarketValue)],
    ["總損益金額", signedMoneyText(summary.totalPnl), summary.totalPnl >= 0 ? "is-profit" : "is-loss"],
    ["總損益率", signedPercentText(summary.totalPnlPct), summary.totalPnl >= 0 ? "is-profit" : "is-loss"],
    ["股票部位", `${summary.stockWeight.toFixed(2)}%`],
    ["現金部位", `${summary.cashWeight.toFixed(2)}%`],
  ];
  return cards.map(([label, value, tone]) => `
    <article class="portfolio-summary-card ${tone || ""}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </article>
  `).join("");
}

function portfolioHoldingCard(holding, totalValue) {
  const code = normalizeCode(holding.symbol || holding.code);
  const metrics = portfolioHoldingMetrics(holding, totalValue);
  const status = portfolioStatus(metrics.weight);
  const name = holding.name || displayStockName(code);
  const summaryFields = [
    ["現價", moneyText(metrics.currentPrice, 2)],
    ["損益率", signedPercentText(metrics.pnlPct), metrics.pnl >= 0 ? "is-profit" : "is-loss"],
    ["持股占比", `${metrics.weight.toFixed(2)}%`],
  ];
  const fields = [
    ["題材", holding.theme || "-"],
    ["持有股數", moneyText(metrics.shares, 0)],
    ["平均成本", moneyText(metrics.avgCost, 2)],
    ["現價", moneyText(metrics.currentPrice, 2)],
    ["投資成本", moneyText(metrics.cost, 0)],
    ["目前市值", moneyText(metrics.marketValue, 0)],
    ["損益金額", signedMoneyText(metrics.pnl, 0), metrics.pnl >= 0 ? "is-profit" : "is-loss"],
    ["損益率", signedPercentText(metrics.pnlPct), metrics.pnl >= 0 ? "is-profit" : "is-loss"],
    ["持股占比", `${metrics.weight.toFixed(2)}%`],
  ];
  return `
    <details class="portfolio-holding-card">
      <summary class="portfolio-holding-card-summary">
        <div>
          <h3>${portfolioStockLink(holding)} <span>${escapeHtml(name)}</span></h3>
          <div class="portfolio-card-summary-metrics">
            ${summaryFields.map(([label, value, tone]) => `
              <span class="${tone || ""}">${escapeHtml(label)} ${escapeHtml(value)}</span>
            `).join("")}
          </div>
        </div>
        <div class="portfolio-card-summary-side">
          ${chip(status.text, status.tone)}
          <span class="portfolio-card-toggle">展開明細</span>
        </div>
      </summary>
      <div class="portfolio-card-detail">
        <div class="portfolio-card-metrics">
          ${fields.map(([label, value, tone]) => `
            <div class="portfolio-card-metric ${tone || ""}">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `).join("")}
        </div>
        <div class="portfolio-card-actions">
          ${portfolioActionButtons(holding)}
        </div>
      </div>
    </details>
  `;
}

function portfolioTable(holdings, totalValue) {
  if (!holdings.length) {
    return `<div class="empty">尚未新增持股。請編輯 <code>docs/data/portfolio.json</code> 加入 holdings 後，這裡才會顯示持股明細。</div>`;
  }
  const rows = holdings.map((holding) => {
    const code = normalizeCode(holding.symbol || holding.code);
    const metrics = portfolioHoldingMetrics(holding, totalValue);
    const status = portfolioStatus(metrics.weight);
    return `
      <tr>
        <td>${portfolioStockLink(holding)}</td>
        <td>${escapeHtml(holding.name || displayStockName(code))}</td>
        <td>${escapeHtml(holding.theme || "-")}</td>
        <td class="cell-number">${escapeHtml(moneyText(metrics.shares, 0))}</td>
        <td class="cell-number">${escapeHtml(moneyText(metrics.avgCost, 2))}</td>
        <td class="cell-number">${escapeHtml(moneyText(metrics.currentPrice, 2))}</td>
        <td class="cell-number">${escapeHtml(moneyText(metrics.cost, 0))}</td>
        <td class="cell-number">${escapeHtml(moneyText(metrics.marketValue, 0))}</td>
        <td class="cell-number ${metrics.pnl >= 0 ? "is-profit" : "is-loss"}">${escapeHtml(signedMoneyText(metrics.pnl, 0))}</td>
        <td class="cell-number ${metrics.pnl >= 0 ? "is-profit" : "is-loss"}">${escapeHtml(signedPercentText(metrics.pnlPct))}</td>
        <td class="cell-number">${escapeHtml(`${metrics.weight.toFixed(2)}%`)}</td>
        <td>${chip(status.text, status.tone)}</td>
        <td>${portfolioActionButtons(holding)}</td>
      </tr>
    `;
  }).join("");
  const cards = holdings.map((holding) => portfolioHoldingCard(holding, totalValue)).join("");
  return `
    <div class="portfolio-desktop-table">
      <div class="table-wrap portfolio-table-wrap">
        <table class="portfolio-table">
          <thead>
            <tr><th>代號</th><th>名稱</th><th>題材</th><th>持有股數</th><th>平均成本</th><th>現價</th><th>投資成本</th><th>目前市值</th><th>損益金額</th><th>損益率</th><th>持股占比</th><th>狀態</th><th>操作</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
    <div class="portfolio-mobile-cards" aria-label="手機版持股明細">${cards}</div>
  `;
}

function portfolioAllocation(holdings, summary) {
  if (!holdings.length && summary.cash <= 0) {
    return `<div class="empty">目前持股與現金皆為 0。新增持股或現金後，資金分配才會顯示。</div>`;
  }
  const stockBars = holdings.map((holding) => {
    const code = normalizeCode(holding.symbol || holding.code);
    const metrics = portfolioHoldingMetrics(holding, summary.totalValue);
    const label = `${code} ${holding.name || displayStockName(code)}`.trim();
    return portfolioAllocationBar(label, metrics.weight, metrics.weight >= 40 ? "warn" : "");
  }).join("");
  return `${stockBars}${portfolioAllocationBar("現金", summary.cashWeight, "cash")}`;
}

function portfolioStockOptions(holdings = []) {
  const seen = new Set();
  const options = [];
  const addOption = (code, name) => {
    const normalized = normalizeCode(code);
    if (!/^\d{4}$/.test(normalized) || seen.has(normalized)) return;
    seen.add(normalized);
    const label = `${normalized} ${name || displayStockName(normalized)}`.trim();
    options.push(`<option value="${escapeHtml(label)}"></option>`);
  };
  holdings.forEach((holding) => addOption(holding.symbol || holding.code, holding.name || masterName(holding.symbol || holding.code)));
  Object.keys(state.master || {}).sort().forEach((code) => addOption(code, masterName(code)));
  return options.join("");
}

function portfolioCalculator(holdings) {
  return `
    <div class="portfolio-calculator">
      <label>選擇股票<input id="portfolioCalcSymbol" list="portfolioStockOptions" placeholder="輸入代號或中文名稱，例如 2337 或 旺宏"><datalist id="portfolioStockOptions">${portfolioStockOptions(holdings)}</datalist></label>
      <label>操作類型<select id="portfolioCalcAction"><option value="buy">買進</option><option value="sell">賣出</option></select></label>
      <label>股數<input id="portfolioCalcShares" type="number" min="0" step="1" placeholder="例如 100"></label>
      <label>價格<input id="portfolioCalcPrice" type="number" min="0" step="0.01" placeholder="例如 145.5"></label>
      <button id="portfolioCalcButton" type="button">新增 / 更新持股</button>
    </div>
    <div id="portfolioCalcResult" class="portfolio-calc-result empty">輸入股數與價格後，會即時更新本機持股與資金配置。</div>
  `;
}

function upsertPortfolioHolding(portfolio, symbol, action, shares, price) {
  const holdings = Array.isArray(portfolio.holdings) ? [...portfolio.holdings] : [];
  const index = holdings.findIndex((item) => normalizeCode(item.symbol || item.code) === symbol);
  const existing = index >= 0 ? holdings[index] : null;
  const currentShares = existing ? Math.max(0, safeNumber(existing.shares)) : 0;
  const currentCost = existing ? currentShares * safeNumber(existing.avg_cost) : 0;
  const tradeAmount = shares * price;
  if (action === "sell") {
    if (!existing) return { error: "此股票目前不在持股內，無法做賣出更新。" };
    const sellShares = Math.min(shares, currentShares);
    const remainShares = currentShares - sellShares;
    if (remainShares <= 0) holdings.splice(index, 1);
    else holdings[index] = { ...existing, shares: remainShares, current_price: price };
    return {
      portfolio: { ...portfolio, cash: Math.max(0, safeNumber(portfolio.cash)) + (sellShares * price), holdings },
      message: `已賣出 ${symbol} ${moneyText(sellShares, 0)} 股，總覽已更新。`,
    };
  }
  const newShares = currentShares + shares;
  const newAvgCost = newShares > 0 ? (currentCost + tradeAmount) / newShares : 0;
  const nextHolding = {
    ...(existing || {}),
    symbol,
    name: existing?.name || displayStockName(symbol),
    shares: newShares,
    avg_cost: newAvgCost,
    current_price: price,
    theme: existing?.theme || "",
  };
  if (index >= 0) holdings[index] = nextHolding;
  else holdings.push(nextHolding);
  return {
    portfolio: { ...portfolio, cash: Math.max(0, safeNumber(portfolio.cash) - tradeAmount), holdings },
    message: `已買進 / 更新 ${symbol} ${displayStockName(symbol)}，總覽已更新。`,
  };
}

function bindPortfolioCalculator(portfolio) {
  const button = $("#portfolioCalcButton");
  if (!button) return;
  $all(".portfolio-row-action").forEach((actionButton) => {
    actionButton.addEventListener("click", () => {
      const symbolInput = $("#portfolioCalcSymbol");
      const actionSelect = $("#portfolioCalcAction");
      const priceInput = $("#portfolioCalcPrice");
      const sharesInput = $("#portfolioCalcShares");
      if (symbolInput) symbolInput.value = actionButton.dataset.label || actionButton.dataset.symbol || "";
      if (actionSelect) actionSelect.value = actionButton.dataset.portfolioAction || "buy";
      if (priceInput && actionButton.dataset.price) priceInput.value = actionButton.dataset.price;
      if (sharesInput) {
        sharesInput.focus();
        sharesInput.select();
      }
      $("#portfolioCalcButton")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  button.addEventListener("click", () => {
    const symbol = resolveStockQuery($("#portfolioCalcSymbol")?.value);
    const action = $("#portfolioCalcAction")?.value || "buy";
    const shares = Math.max(0, safeNumber($("#portfolioCalcShares")?.value));
    const price = Math.max(0, safeNumber($("#portfolioCalcPrice")?.value));
    const existingHolding = (portfolio.holdings || []).find((item) => normalizeCode(item.symbol || item.code) === symbol);
    const result = $("#portfolioCalcResult");
    if (!result) return;
    if (!symbol || (!knownStock(symbol) && !existingHolding && !stockByCode(symbol))) {
      result.innerHTML = "找不到此股票代號或名稱，請確認是否輸入正確。";
      return;
    }
    if (!shares || !price) {
      result.innerHTML = "請輸入有效股數與價格。";
      return;
    }
    const next = upsertPortfolioHolding(portfolio, symbol, action, shares, price);
    if (next.error) {
      result.innerHTML = next.error;
      return;
    }
    if (!savePortfolioDraft(next.portfolio)) {
      result.innerHTML = "瀏覽器無法儲存本機持股資料，請確認 localStorage 權限。";
      return;
    }
    result.innerHTML = next.message;
    renderPortfolio();
  });
}

async function renderPortfolio() {
  renderHeader("portfolio");
  const main = $("#app");
  const basePortfolio = await loadJson("data/portfolio.json", null);
  const portfolio = basePortfolio ? portfolioFromStorage(basePortfolio) : null;
  const holdings = Array.isArray(portfolio?.holdings) ? portfolio.holdings : [];
  if (!portfolio) {
    main.innerHTML = `<section class="panel"><div class="empty">投資組合資料尚未建立或讀取失敗</div></section>`;
    return;
  }
  const cash = Math.max(0, safeNumber(portfolio.cash));
  const holdingMetrics = holdings.map((holding) => portfolioHoldingMetrics(holding, 0));
  const totalCost = holdingMetrics.reduce((sum, item) => sum + item.cost, 0);
  const totalMarketValue = holdingMetrics.reduce((sum, item) => sum + item.marketValue, 0);
  const totalValue = cash + totalMarketValue;
  const totalPnl = totalMarketValue - totalCost;
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : NaN;
  const summary = {
    cash,
    totalCost,
    totalMarketValue,
    totalValue,
    totalPnl,
    totalPnlPct,
    stockWeight: totalValue > 0 ? (totalMarketValue / totalValue) * 100 : 0,
    cashWeight: totalValue > 0 ? (cash / totalValue) * 100 : 0,
  };
  main.innerHTML = `
    <section class="panel portfolio-page">
      <div class="section-title"><h2>投資組合總覽</h2><span>更新日期：${escapeHtml(portfolio.updated_at || "未標示")}</span></div>
      <div class="portfolio-summary-grid">${portfolioSummaryCards(summary)}</div>
    </section>
    <section class="panel portfolio-page">
      <div class="section-title"><h2>持股明細表</h2><span>${escapeHtml(`${holdings.length} 檔持股`)}</span></div>
      ${portfolioTable(holdings, totalValue)}
    </section>
    <section class="panel portfolio-page">
      <div class="section-title"><h2>資金分配</h2><span>股票 ${summary.stockWeight.toFixed(2)}%｜現金 ${summary.cashWeight.toFixed(2)}%</span></div>
      <div class="portfolio-allocation">${portfolioAllocation(holdings, summary)}</div>
    </section>
    <section class="panel portfolio-page">
      <div class="section-title"><h2>加碼 / 減碼試算器</h2><span>即時更新本機資料，不寫回 JSON</span></div>
      ${portfolioCalculator(holdings)}
      <div class="portfolio-note">
        本頁新增 / 更新持股會儲存在此瀏覽器 localStorage；若要修改網站預設模板，才需要編輯 <code>docs/data/portfolio.json</code>。
      </div>
    </section>
  `;
  bindPortfolioCalculator(portfolio);
}

function renderCodeHits(selector, codes) {
  const el = $(selector);
  if (!codes.length) {
    el.innerHTML = `<div class="empty">尚未設定清單</div>`;
    return;
  }
  el.innerHTML = codes.map((code) => {
    const stock = stockByCode(code);
    const newsHits = state.news.filter((event) => (event.related_stocks || []).map(normalizeCode).includes(code));
    return `
      <article class="card">
        <h3>${escapeHtml(stockLabel(code))}</h3>
        <div class="chip-row">
          ${stock ? chip("命中今日雷達", "good") : chip("今日未入選雷達")}
          ${newsHits.length ? chip(`命中重大新聞 ${newsHits.length} 則`, "warn") : chip("未命中重大新聞")}
        </div>
        ${stock ? `<p class="muted">雷達評分 ${escapeHtml(radarScore(stock))}｜收盤價 ${escapeHtml(displayClose(stock))}｜成交量 ${escapeHtml(displayVolume(stock))}${officialRankEligible(stock) ? " 張" : ""}</p>` : ""}
        ${newsHits.length ? `<div class="news-hit-list"><p><span class="label">命中重大新聞</span></p>${newsListHtml(newsHits, "來源待補")}</div>` : ""}
      </article>
    `;
  }).join("");
}

async function renderHomeDashboard() {
  const main = $("#app");
  const [snapshotRaw, stocksRaw, themesRaw, newsRaw] = await Promise.all([
    loadJson("data/daily_market_snapshot.json", null),
    loadJson("data/daily_hot_stocks.json", null),
    loadJson("data/daily_hot_themes.json", null),
    loadJson("data/news-events.json", null),
  ]);
  const snapshot = normalizeDashboardData(snapshotRaw);
  const hotStocks = normalizeDashboardData(stocksRaw);
  const hotThemes = normalizeDashboardData(themesRaw);
  const majorNews = normalizeDashboardData(newsRaw);
  warnDashboardQuality(snapshot, hotStocks, hotThemes, majorNews);
  main.innerHTML = `
    <section class="home-dashboard-panel">
      ${homePanelTitle("台股大盤最後紀錄", snapshot)}
      ${homeMarketOverview(snapshot)}
    </section>
    <section class="home-dashboard-panel">
      ${homePanelTitle("今日最強題材 Top 5", hotThemes)}
      ${homeThemeTopTable(hotThemes)}
    </section>
    <section class="home-dashboard-panel">
      ${homePanelTitle("前三天最強題材", hotThemes)}
      ${homeThreeDayThemeTable(hotThemes)}
    </section>
    <section class="home-dashboard-panel">
      ${homePanelTitle("重大新聞 Top 5", majorNews)}
      ${homeMajorNewsTable(majorNews)}
    </section>
  `;
}

async function boot(page) {
  await loadSiteVersion();
  renderHeader(page);
  if (page === "index") {
    await renderHomeDashboard();
    return;
  }
  if (page === "radar") {
    await loadRadarData();
    if (!state.stocks.length) {
      renderError("#app", "資料載入失敗或尚未建立：data/radar-latest.json");
      return;
    }
    initRankingAccordions();
    renderRadar();
    return;
  }
  await loadAllData();
  const missing = [];
  if (!state.stocks.length) missing.push("data/stocks-latest.json");
  if (!state.master || !Object.keys(state.master).length) missing.push("data/stock-master.json");
  if (!Array.isArray(state.news)) missing.push("data/news-events.json");
  if (missing.length) {
    renderError("#app", `資料載入失敗或尚未建立：${missing.join("、")}`);
    return;
  }
  if (page === "news") renderNews();
  if (page === "themes") renderThemes();
  if (page === "concepts") await renderConcepts();
  if (page === "stock") renderStock();
  if (page === "portfolio") await renderPortfolio();
}
