const HOLDINGS_KEY = "asurada_holdings";
const WATCHLIST_KEY = "asurada_watchlist";

const state = {
  stocks: [],
  news: [],
  themes: {},
  concepts: {},
  themeCandidates: [],
  technical: {},
  profiles: {},
  master: {},
};

const TECH_THEMES = [
  "AI伺服器", "AI PC", "AI手機", "AI智慧型眼鏡", "智慧眼鏡", "PCB", "CPO", "光通訊", "矽光子", "記憶體", "半導體", "半導體設備", "玻璃基板",
  "低軌衛星", "重電", "散熱", "電源", "被動元件", "IC設計", "封測", "材料",
  "機器人", "智慧眼鏡", "無人機", "軍工電子",
];

const NON_TECH_THEMES = [
  "營建", "資產", "都更", "金融", "壽險", "銀行", "生醫", "生技", "觀光", "食品", "航運", "鋼鐵", "塑化", "原物料", "傳產",
];

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

async function loadJson(path, fallback) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    console.warn(`Failed to load ${path}`, error);
    return fallback;
  }
}

async function loadText(path) {
  const response = await fetch(path, { cache: "no-store" });
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

async function loadAllData() {
  const [stocks, news, themes, concepts, themeCandidates, technical, profiles, master] = await Promise.all([
    loadJson("data/stocks-latest.json", []),
    loadJson("data/news-events.json", []),
    loadJson("data/themes-map.json", {}),
    loadJson("data/concepts-map.json", {}),
    loadJson("data/theme-candidates.json", []),
    loadJson("data/technical-latest.json", {}),
    loadJson("data/stock-profiles.json", {}),
    loadJson("data/stock-master.json", {}),
  ]);
  state.stocks = Array.isArray(stocks) ? stocks : [];
  state.news = Array.isArray(news) ? news : [];
  state.themes = Array.isArray(themes)
    ? Object.fromEntries(themes.map((theme) => [theme.name || theme.theme_name, theme]))
    : (themes && typeof themes === "object" ? themes : {});
  state.concepts = concepts && typeof concepts === "object" ? concepts : {};
  state.themeCandidates = Array.isArray(themeCandidates) ? themeCandidates : [];
  state.technical = technical && typeof technical === "object" ? technical : {};
  state.profiles = profiles && typeof profiles === "object" ? profiles : {};
  state.master = master && typeof master === "object" ? master : {};
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
    ["CMoney 營收", `https://www.cmoney.tw/finance/${safeCode}/f00029`],
    ["CMoney 技術分析", `https://www.cmoney.tw/finance/${safeCode}/technicalanalysis`],
    ["CMoney 籌碼K線", `https://www.cmoney.tw/finance/${safeCode}/stockmainkline`],
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

function stockCard(stock, mode = "main", compact = false) {
  const info = radarModeInfo(stock, mode);
  const modeName = mode === "market" ? "全市場" : mode === "defensive" ? "資產防守" : "主升段";
  const labels = revenueLabels(stock);
  return `
    <article class="card stock-card">
      <div class="section-title">
        <h3><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.code)}">#${escapeHtml(stock.rank)} ${escapeHtml(stock.code)} ${escapeHtml(displayStockName(stock.code))}</a></h3>
        ${chip(radarScore(stock, mode), "good")}
      </div>
      <div class="grid ${compact ? "cols-3" : "cols-4"}">
        <div class="metric"><span>雷達評分</span><strong>${escapeHtml(radarScore(stock, mode))}</strong></div>
        <div class="metric"><span>收盤價</span><strong>${escapeHtml(stock.close)}</strong></div>
        <div class="metric"><span>成交量</span><strong>${escapeHtml(stock.volume)} 張</strong></div>
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
        <td>${escapeHtml(stock.close)}</td>
        <td>${escapeHtml(stock.volume)}</td>
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

function stockRadarDetail(stock) {
  const labels = revenueLabels(stock);
  const rows = [
    ["雷達排名", stock.rank],
    ["雷達評分", radarScore(stock, "market")],
    ["收盤價", stock.close],
    ["成交量", stock.volume],
    [labels.current, revenueAmount(stock)],
    [labels.mom, stock.revenue_mom],
    [labels.yoy, stock.revenue_yoy],
  ];
  return `
    <div class="stock-info-card">
      <h3>雷達資訊</h3>
      <div class="stock-info-grid">
        ${rows.map(([label, value]) => infoItem(label, value)).join("")}
      </div>
      <div class="stock-notes">
        <p><span class="label">概念股</span>${escapeHtml(cleanDisplay(stock.concept))}</p>
        <p><span class="label">入選理由</span>${escapeHtml(cleanDisplay(stock.reason))}</p>
        <p><span class="label">風險標籤</span>${escapeHtml(cleanDisplay(stock.risk_tags || "一般觀察"))}</p>
      </div>
    </div>
  `;
}

function stockMasterDetail(code, stock) {
  const record = masterRecord(code);
  const status = stock ? "命中今日雷達" : "今日未入選雷達";
  return `
    <div class="stock-info-card">
      <h3>基本資料</h3>
      <div class="stock-info-grid">
        ${infoItem("股票代號", normalizeCode(code))}
        ${infoItem("股票名稱", record?.name || "名稱待補")}
        ${infoItem("市場別", record?.market)}
        ${infoItem("產業別", record?.industry)}
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
      <p class="analysis"><span class="label">阿斯拉連動分析</span>${escapeHtml(event.asurada_analysis || event.logic || "尚無連動分析")}</p>
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
    ["radar.html", "全股雷達", "radar"],
    ["news.html", "重大新聞", "news"],
    ["concepts.html", "概念股資料庫", "concepts"],
    ["stock.html", "個股查詢", "stock"],
    ["portfolio.html", "我的持股", "portfolio"],
  ];
  const el = $("#siteHeader");
  if (!el) return;
  el.innerHTML = `
    <div class="site-header">
      <h1>阿斯拉台股月營收轉強雷達</h1>
      <p>月營收轉強 + 主升段候選股觀察雷達，僅供研究與風險控管參考。</p>
      <nav class="nav">${nav.map(([href, label, key]) => `<a class="${active === key ? "active" : ""}" href="${href}">${label}</a>`).join("")}</nav>
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

function renderHome() {
  renderHeader("index");
  const main = $("#app");
  const holdings = readStoredCodes(HOLDINGS_KEY);
  const hitHoldings = holdings.filter((code) => stockByCode(code));
  const techStocks = sortedStocks("tech").slice(0, 30);
  const topStocks = techStocks.slice(0, 10);
    const nonTech = sortedStocks("nontech").slice(0, 30);
    const navEntrances = [
      ["radar.html", "全股雷達"],
      ["concepts.html", "概念股資料庫"],
      ["news.html", "重大新聞"],
      ["stock.html", "個股查詢"],
    ["portfolio.html", "我的持股"],
  ];
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>今日雷達總覽</h2><span>${escapeHtml(state.stocks[0]?.data_version || "")}</span></div>
      <div class="grid cols-4">
        <div class="metric"><span>電子主升段</span><strong>${techStocks.length} 檔</strong></div>
        <div class="metric"><span>A級</span><strong>${techStocks.filter((s) => s.rating === "A").length} 檔</strong></div>
        <div class="metric"><span>A-級</span><strong>${techStocks.filter((s) => s.rating === "A-").length} 檔</strong></div>
        <div class="metric"><span>持股命中</span><strong>${hitHoldings.length} 檔</strong></div>
      </div>
    </section>
    <section class="panel">
      <div class="section-title"><h2>前 10 名電子主升段雷達股</h2><a class="stock-link" href="radar.html">全股雷達</a></div>
      ${stockTable(topStocks, "main", true)}
    </section>
    <section class="panel">
      <div class="section-title"><h2>非電子類別摘要</h2><a class="stock-link" href="radar.html">切換非電子類別</a></div>
      <div class="grid cols-3">
        <div class="metric"><span>非電子入選</span><strong>${nonTech.length} 檔</strong></div>
        <div class="metric"><span>A級以上</span><strong>${nonTech.filter((s) => ["S", "A"].includes(s.rating)).length} 檔</strong></div>
        <div class="metric"><span>最高分</span><strong>${nonTech[0] ? radarScore(nonTech[0], "market") : "-"}</strong></div>
      </div>
    </section>
    <section class="panel">
      <div class="section-title"><h2>我的持股命中摘要</h2><a class="stock-link" href="portfolio.html">編輯清單</a></div>
      <div class="chip-row">${hitHoldings.length ? stockChips(hitHoldings) : chip("今日未命中，或尚未設定持股")}</div>
    </section>
    <section class="panel">
      <div class="section-title"><h2>導航入口</h2><span>新聞集中在重大新聞頁</span></div>
      <div class="button-row">${navEntrances.map(([href, label]) => `<a class="solid-link" href="${href}">${label}</a>`).join("")}</div>
    </section>
  `;
}

function renderRadar() {
  renderHeader("radar");
  const main = $("#app");
  const conceptOptions = conceptEntries().map((concept) => `<option value="${escapeHtml(concept.name)}"></option>`).join("");
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>全股雷達清單</h2><span id="radarCount"></span></div>
      <div class="filters">
        <label>雷達模式<select id="mode"><option value="tech">電子主升段</option><option value="nontech">非電子類別</option><option value="market">全市場雷達</option></select></label>
        <label>股票搜尋<input id="search" placeholder="代號、名稱或概念股，例如 2337、旺宏、CPO"></label>
        <label>雷達等級<select id="rating"><option value="">全部</option><option>S</option><option>A</option><option>B</option><option>C</option></select></label>
        <label>簡單題材篩選<input id="concept" list="conceptOptions" placeholder="AI、PCB、記憶體..."></label>
      </div>
      <datalist id="conceptOptions">${conceptOptions}</datalist>
      <p id="modeNote" class="mode-note"></p>
    </section>
    <section id="radarList"></section>
  `;
  const render = () => {
    const mode = $("#mode").value;
    const search = $("#search").value.trim().toLowerCase();
    const rating = $("#rating").value;
    const concept = $("#concept").value.trim().toLowerCase();
    let list = sortedStocks(mode);
    const hasUserFilter = Boolean(search || rating || concept);
    list = list.filter((stock) => {
      const haystack = `${stock.code} ${displayStockName(stock.code)} ${stock.concept || ""} ${stock.reason || ""}`.toLowerCase();
      if (search && !haystack.includes(search)) return false;
      if (!matchesRating(stock, rating)) return false;
      if (concept && !haystack.includes(concept)) return false;
      return true;
    });
    if (!hasUserFilter) list = list.slice(0, 30);
    list = list.map((stock, index) => ({ ...stock, display_rank: index + 1 }));
    $("#radarCount").textContent = `顯示 ${list.length} 檔`;
    $("#modeNote").textContent = mode === "tech"
      ? "電子主升段雷達只顯示電子與科技主流族群，非電子不佔用主升段排序。"
      : mode === "nontech"
        ? "非電子類別顯示營建、資產、金融、航運、原物料、觀光、生技等非電子族群。"
        : "全市場雷達不分電子與非電子，照原始雷達排序顯示。";
    $("#radarList").innerHTML = stockTable(list, mode);
  };
  ["mode", "search", "rating", "concept"].forEach((id) => $(`#${id}`).addEventListener("input", render));
  ["mode", "rating"].forEach((id) => $(`#${id}`).addEventListener("change", render));
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
              <td>${escapeHtml(stock?.close || "-")}</td>
              <td>${escapeHtml(stock?.price_change || stock?.change || "-")}</td>
              <td>${escapeHtml(stock?.daily_change || stock?.change_percent || "-")}</td>
              <td>${escapeHtml(stock?.volume || "-")}</td>
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

function renderStock() {
  renderHeader("stock");
  const params = new URLSearchParams(location.search);
  const initialCode = normalizeCode(params.get("code") || "");
  const main = $("#app");
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>個股查詢</h2></div>
      <div class="filters stock-search-form"><label>股票代號<input id="stockSearch" value="${escapeHtml(initialCode)}" placeholder="請輸入股票代號"></label></div>
    </section>
    <section id="stockResult"></section>
  `;
  const render = () => {
    const code = normalizeCode($("#stockSearch").value);
    const stock = stockByCode(code);
    const name = displayStockName(code);
    if (!code) {
      $("#stockResult").innerHTML = `<div class="empty">請輸入股票代號</div>`;
      return;
    }
    if (!knownStock(code)) {
      $("#stockResult").innerHTML = `<div class="empty">找不到此股票代號，請確認是否輸入錯誤。</div>`;
      return;
    }
    if (!stock) {
      $("#stockResult").innerHTML = `
        <section class="panel">
          <div class="section-title"><h2>${escapeHtml(code)} ${escapeHtml(name)}</h2>${chip("今日未入選雷達", "warn")}</div>
          ${stockMasterDetail(code, stock)}
          <p class="muted">尚無內部雷達資料。</p>
        </section>
        <section class="panel"><div class="section-title"><h2>技術圖表</h2></div>${externalLinks(code)}</section>
      `;
      return;
    }
    const relatedNews = state.news.filter((event) => (event.related_stocks || []).map(normalizeCode).includes(code));
    const relatedThemes = themeEntries().filter((theme) => (theme.related_stocks || []).map(normalizeCode).includes(code));
    const tech = state.technical[code];
    $("#stockResult").innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>${escapeHtml(code)} ${escapeHtml(name)}</h2>${chip("命中今日雷達", "good")}</div>
        ${stockMasterDetail(code, stock)}
        ${stockRadarDetail(stock)}
      </section>
      <section class="panel"><div class="section-title"><h2>阿斯拉方針</h2></div>${chip(asuradaStance(stock), "warn")}</section>
      <section class="panel"><div class="section-title"><h2>技術圖表</h2></div>${externalLinks(code)}</section>
      <section class="panel"><div class="section-title"><h2>相關重大新聞</h2></div>${relatedNews.length ? relatedNews.map(eventCard).join("") : `<div class="empty">目前沒有該股相關重大新聞</div>`}</section>
      <section class="panel"><div class="section-title"><h2>相關題材</h2></div><div class="chip-row">${relatedThemes.length ? relatedThemes.map((x) => chip(x.theme_name)).join("") : chip("暫無題材對應")}</div></section>
      <section class="panel"><div class="section-title"><h2>技術面欄位</h2></div>${tech ? `<pre>${escapeHtml(JSON.stringify(tech, null, 2))}</pre>` : `<div class="empty">技術面資料尚未建立</div>`}</section>
    `;
  };
  $("#stockSearch").addEventListener("input", render);
  render();
}

function renderPortfolio() {
  renderHeader("portfolio");
  const main = $("#app");
  const holdings = readStoredCodes(HOLDINGS_KEY);
  const watchlist = readStoredCodes(WATCHLIST_KEY);
  main.innerHTML = `
    <section class="panel">
      <div class="section-title"><h2>我的持股與觀察清單</h2><span>儲存在此瀏覽器 localStorage</span></div>
      <div class="grid cols-2">
        <label>我的持股<textarea id="holdingsInput" placeholder="2337,2313 或每行一檔">${escapeHtml(holdings.join("\n"))}</textarea></label>
        <label>觀察清單<textarea id="watchlistInput" placeholder="2383,2368 或每行一檔">${escapeHtml(watchlist.join("\n"))}</textarea></label>
      </div>
      <div class="button-row">
        <button id="savePortfolio">儲存</button>
        <button id="clearPortfolio" class="secondary">清除</button>
        <button id="exportPortfolio" class="secondary">匯出設定</button>
        <button id="importPortfolio" class="secondary">匯入設定</button>
        <input id="importFile" type="file" accept="application/json,.json" hidden>
      </div>
    </section>
    <section class="panel"><div class="section-title"><h2>持股命中</h2></div><div id="holdingsResult"></div></section>
    <section class="panel"><div class="section-title"><h2>觀察清單命中</h2></div><div id="watchlistResult"></div></section>
  `;
  const renderHits = () => {
    renderCodeHits("#holdingsResult", readStoredCodes(HOLDINGS_KEY));
    renderCodeHits("#watchlistResult", readStoredCodes(WATCHLIST_KEY));
  };
  $("#savePortfolio").addEventListener("click", () => {
    writeStoredCodes(HOLDINGS_KEY, parseCodes($("#holdingsInput").value));
    writeStoredCodes(WATCHLIST_KEY, parseCodes($("#watchlistInput").value));
    renderHits();
  });
  $("#clearPortfolio").addEventListener("click", () => {
    localStorage.removeItem(HOLDINGS_KEY);
    localStorage.removeItem(WATCHLIST_KEY);
    $("#holdingsInput").value = "";
    $("#watchlistInput").value = "";
    renderHits();
  });
  $("#exportPortfolio").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ holdings: parseCodes($("#holdingsInput").value), watchlist: parseCodes($("#watchlistInput").value) }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "asurada_portfolio.json";
    link.click();
    URL.revokeObjectURL(url);
  });
  $("#importPortfolio").addEventListener("click", () => $("#importFile").click());
  $("#importFile").addEventListener("change", () => {
    const file = $("#importFile").files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || "{}"));
        const holdingsCodes = Array.isArray(parsed.holdings) ? parsed.holdings : parsed.codes || [];
        const watchCodes = Array.isArray(parsed.watchlist) ? parsed.watchlist : [];
        writeStoredCodes(HOLDINGS_KEY, holdingsCodes.map(normalizeCode).filter(Boolean));
        writeStoredCodes(WATCHLIST_KEY, watchCodes.map(normalizeCode).filter(Boolean));
        $("#holdingsInput").value = readStoredCodes(HOLDINGS_KEY).join("\n");
        $("#watchlistInput").value = readStoredCodes(WATCHLIST_KEY).join("\n");
        renderHits();
      } catch {
        alert("匯入失敗，請確認 JSON 格式是否正確。");
      }
    };
    reader.readAsText(file, "utf-8");
  });
  renderHits();
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
        ${stock ? `<p class="muted">雷達評分 ${escapeHtml(radarScore(stock))}｜收盤價 ${escapeHtml(stock.close)}｜成交量 ${escapeHtml(stock.volume)} 張</p>` : ""}
        ${newsHits.length ? `<div class="news-hit-list"><p><span class="label">命中重大新聞</span></p>${newsListHtml(newsHits, "來源待補")}</div>` : ""}
      </article>
    `;
  }).join("");
}

async function boot(page) {
  renderHeader(page);
  await loadAllData();
  const missing = [];
  if (!state.stocks.length) missing.push("data/stocks-latest.json");
  if (!state.master || !Object.keys(state.master).length) missing.push("data/stock-master.json");
  if (!Array.isArray(state.news)) missing.push("data/news-events.json");
  if (missing.length) {
    renderError("#app", `資料載入失敗或尚未建立：${missing.join("、")}`);
    return;
  }
  if (page === "index") renderHome();
  if (page === "radar") renderRadar();
  if (page === "news") renderNews();
  if (page === "themes") renderThemes();
  if (page === "concepts") await renderConcepts();
  if (page === "stock") renderStock();
  if (page === "portfolio") renderPortfolio();
}
