const app = document.querySelector("#app");

const state = {
  moneydj: { updated_at: "", source: "MoneyDJ", concepts: [] },
  manualRows: [],
  aliases: {},
  sourceLinks: {},
  query: "",
  selectedId: "",
  siteVersion: { build_id: "", updated_at: "", status: "", datasets: {} },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeText(value) {
  return String(value ?? "").trim().toLowerCase();
}

function normalizeCode(value) {
  return String(value ?? "").trim().replace(/\.(TW|TWO)$/i, "");
}

function cleanConceptName(value) {
  return String(value ?? "").trim().replace(/概念股$/u, "");
}

function stockHref(code) {
  return `stock.html?code=${encodeURIComponent(normalizeCode(code))}`;
}

function sourceHref(url) {
  const text = String(url || "").trim();
  if (!text || text === "#" || /example\.com|demo|test/i.test(text)) return "";
  return text;
}

let siteVersionPromise = null;

function shouldVersionDataPath(path) {
  const text = String(path || "");
  return text.includes("data/") && !text.includes("site-version.json") && !text.includes("?") && !/^https?:/i.test(text);
}

function withBuildVersion(path) {
  if (!shouldVersionDataPath(path) || !state.siteVersion.build_id) return path;
  return `${path}?v=${encodeURIComponent(state.siteVersion.build_id)}`;
}

async function loadSiteVersion() {
  if (siteVersionPromise) return siteVersionPromise;
  siteVersionPromise = (async () => {
    try {
      const response = await fetch("data/site-version.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.siteVersion = data && typeof data === "object" ? { ...state.siteVersion, ...data } : state.siteVersion;
      return state.siteVersion;
    } catch (error) {
      console.warn("Failed to load data/site-version.json", error);
      return state.siteVersion;
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

async function loadText(path, fallback = "") {
  try {
    if (shouldVersionDataPath(path)) await loadSiteVersion();
    const response = await fetch(withBuildVersion(path), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } catch (error) {
    console.warn(`Failed to load ${path}`, error);
    return fallback;
  }
}

function siteVersionStatusHtml() {
  const updatedAt = state.siteVersion.updated_at ? String(state.siteVersion.updated_at).replace("T", " ").replace("+08:00", "") : "尚未取得";
  const buildId = state.siteVersion.build_id || "未標示";
  const status = state.siteVersion.status || "等待同步狀態";
  const conceptsStatus = state.siteVersion.datasets?.["concepts-moneydj.json"]?.status || "";
  const staleText = conceptsStatus === "stale" ? `<span class="site-version-warning">產業題材資料沿用上一版</span>` : "";
  return `
    <div class="site-version-bar">
      <span>全站更新：${escapeHtml(updatedAt)}</span>
      <span>版本：${escapeHtml(buildId)}</span>
      <span>狀態：${escapeHtml(status)}</span>
      ${staleText}
    </div>
  `;
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
    if (char === '"') inQuotes = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") field += char;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  const headers = (rows.shift() || []).map((item) => item.trim());
  return rows
    .filter((items) => items.some((item) => String(item || "").trim()))
    .map((items) => Object.fromEntries(headers.map((header, index) => [header, items[index] ?? ""])));
}

function conceptAliases(name) {
  const clean = cleanConceptName(name);
  const direct = state.aliases[clean] || state.aliases[name] || [];
  const reverse = Object.entries(state.aliases)
    .filter(([, aliases]) => Array.isArray(aliases) && aliases.some((alias) => normalizeText(alias) === normalizeText(clean)))
    .map(([key]) => key);
  return [...new Set([clean, ...direct, ...reverse])].filter(Boolean);
}

function conceptSearchText(concept) {
  const aliases = conceptAliases(concept.concept_name);
  const stocks = (concept.stocks || []).map((stock) => `${stock.stock_id} ${stock.stock_name}`).join(" ");
  return normalizeText([
    concept.concept_id,
    concept.concept_code,
    concept.concept_name,
    aliases.join(" "),
    stocks,
  ].join(" "));
}

function mergedConcepts() {
  const map = new Map();
  (state.moneydj.concepts || []).forEach((concept, index) => {
    const name = cleanConceptName(concept.concept_name);
    const conceptId = concept.concept_code || concept.concept_id || `moneydj_${index + 1}`;
    map.set(name, {
      ...concept,
      concept_id: conceptId,
      concept_name: name,
      source_tags: ["MoneyDJ 主資料"],
      stocks: (concept.stocks || []).map((stock) => ({
        stock_id: normalizeCode(stock.stock_id),
        stock_name: stock.stock_name || "",
        sources: ["MoneyDJ"],
        source_urls: [concept.source_url].filter(Boolean),
        note: "",
      })),
    });
  });

  state.manualRows.forEach((row) => {
    const name = cleanConceptName(row.concept_name);
    if (!name) return;
    if (!map.has(name)) {
      map.set(name, {
        concept_id: `manual_${name}`,
        concept_code: "",
        concept_name: name,
        source_url: "",
        source_tags: [],
        stocks: [],
      });
    }
    const concept = map.get(name);
    if (!concept.source_tags.includes("手動補充")) concept.source_tags.push("手動補充");
    const code = normalizeCode(row.stock_id);
    if (!code) return;
    const existing = concept.stocks.find((stock) => stock.stock_id === code);
    if (existing) {
      if (row.source && !existing.sources.includes(row.source)) existing.sources.push(row.source);
      if (row.source_url && !existing.source_urls.includes(row.source_url)) existing.source_urls.push(row.source_url);
      if (row.note) existing.note = [existing.note, row.note].filter(Boolean).join("；");
    } else {
      concept.stocks.push({
        stock_id: code,
        stock_name: row.stock_name || "",
        sources: [row.source || "手動補充"],
        source_urls: [row.source_url].filter(Boolean),
        note: row.note || "",
      });
    }
  });

  return Array.from(map.values()).sort((a, b) => a.concept_name.localeCompare(b.concept_name, "zh-Hant"));
}

function filteredConcepts() {
  const query = normalizeText(state.query);
  const concepts = mergedConcepts();
  if (!query) return concepts;
  return concepts.filter((concept) => conceptSearchText(concept).includes(query));
}

function selectedConcept() {
  const concepts = filteredConcepts();
  return concepts.find((concept) => concept.concept_id === state.selectedId)
    || concepts[0]
    || mergedConcepts()[0]
    || null;
}

function genericSourceLinks(conceptName, moneydjUrl = "") {
  const q = encodeURIComponent(conceptName);
  return {
    MoneyDJ: moneydjUrl || `https://www.moneydj.com/kmdj/search/list.aspx?_Query_=${q}`,
    CMoney: `https://www.cmoney.tw/forum/search?q=${q}`,
    Yahoo: `https://tw.stock.yahoo.com/search/result?q=${q}`,
    PChome: `https://pchome.megatime.com.tw/stock/search/${q}`,
    WantGoo: `https://www.wantgoo.com/search?q=${q}`,
  };
}

function externalLinks(concept) {
  const explicit = state.sourceLinks[concept.concept_name] || {};
  return { ...genericSourceLinks(concept.concept_name, concept.source_url), ...explicit };
}

function renderSourceButtons(concept) {
  const links = externalLinks(concept);
  return Object.entries(links).map(([label, href]) => {
    const url = sourceHref(href);
    if (!url) return "";
    return `<a class="solid-link concept-source-button" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
  }).join("");
}

function percentNumber(value) {
  const number = Number(String(value ?? "").replace(/[,%+]/g, ""));
  return Number.isFinite(number) ? number : null;
}

function positionStatus(row) {
  const change20 = percentNumber(row.change20);
  const change60 = percentNumber(row.change60);
  const distanceLow = percentNumber(row.distanceLow);
  if (change20 !== null && change20 > 30) return "已漲多";
  if (change20 !== null && change20 >= 10 && change20 <= 25) return "剛啟動";
  if (change60 !== null && distanceLow !== null && change60 < 10 && distanceLow < 25) return "低位階";
  return "觀察";
}

function reboundCandidate(status) {
  if (status === "低位階" || status === "剛啟動") return "是";
  if (status === "已漲多") return "否";
  return "--";
}

function renderStockRows(concept) {
  if (!concept?.stocks?.length) {
    return `<tr><td colspan="11" class="muted">此題材目前沒有 MoneyDJ 或手動補充成分股。</td></tr>`;
  }
  return concept.stocks.map((stock) => {
    const status = positionStatus(stock);
    const sourceText = (stock.sources || []).join(" / ") || "MoneyDJ";
    return `
      <tr>
        <td><a class="stock-link" href="${stockHref(stock.stock_id)}">${escapeHtml(stock.stock_id)}</a></td>
        <td><a class="stock-link" href="${stockHref(stock.stock_id)}">${escapeHtml(stock.stock_name || "")}</a></td>
        <td>${escapeHtml(sourceText)}</td>
        <td>--</td>
        <td>--</td>
        <td>--</td>
        <td>--</td>
        <td>--</td>
        <td>${escapeHtml(status)}</td>
        <td>${escapeHtml(reboundCandidate(status))}</td>
        <td>${escapeHtml(stock.note || "--")}</td>
      </tr>
    `;
  }).join("");
}

function renderConceptList(concepts) {
  if (!concepts.length) return `<div class="empty">找不到符合條件的題材或股票。</div>`;
  return concepts.slice(0, 80).map((concept) => `
    <button class="concept-lite-row ${concept.concept_id === selectedConcept()?.concept_id ? "is-active" : ""}" type="button" data-concept-id="${escapeHtml(concept.concept_id)}">
      <strong>${escapeHtml(concept.concept_name)}</strong>
      <span>${escapeHtml(concept.stocks.length)} 檔｜${escapeHtml(concept.source_tags.join(" + "))}</span>
    </button>
  `).join("");
}

function render() {
  const concepts = filteredConcepts();
  const concept = selectedConcept();
  const updated = state.moneydj.updated_at ? state.moneydj.updated_at.replace("T00:00:00+08:00", "") : "未標示";
  app.innerHTML = `
    ${siteVersionStatusHtml()}
    <section class="panel concept-lite-hero">
      <div class="section-title">
        <div>
          <h2>產業題材庫</h2>
          <p class="mode-note">MoneyDJ 作為主資料庫；其他網站只保留外部查詢與手動補充，不再全量複製。</p>
        </div>
        <span>最後更新：${escapeHtml(updated)}</span>
      </div>
      <div class="concept-lite-search">
        <label>搜尋題材 / 股票代號 / 股票名稱
          <input id="conceptSearch" value="${escapeHtml(state.query)}" placeholder="例如：AI眼鏡、玻璃基板、2379、瑞昱">
        </label>
      </div>
      <div class="concept-lite-source-note">
        <strong>資料來源</strong>
        <span>MoneyDJ 主資料</span>
        <span>手動補充 CSV</span>
        <span>外部連結查詢</span>
      </div>
    </section>

    <section class="concept-lite-layout">
      <aside class="panel concept-lite-sidebar">
        <div class="section-title">
          <h3>題材清單</h3>
          <span>${escapeHtml(concepts.length)} 組</span>
        </div>
        <div class="concept-lite-list">${renderConceptList(concepts)}</div>
      </aside>

      <section class="panel concept-lite-detail">
        ${concept ? `
          <div class="section-title">
            <div>
              <h2>${escapeHtml(concept.concept_name)}</h2>
              <p class="mode-note">${escapeHtml(concept.source_tags.join(" + "))}｜${escapeHtml(concept.stocks.length)} 檔成分股</p>
            </div>
            <span>${escapeHtml(state.moneydj.source || "MoneyDJ")}</span>
          </div>
          <div class="button-row concept-source-links">${renderSourceButtons(concept)}</div>
          <div class="table-wrap concept-lite-table-wrap">
            <table class="concept-stock-table concept-lite-table">
              <thead>
                <tr>
                  <th>代號</th>
                  <th>名稱</th>
                  <th>資料來源</th>
                  <th>今日漲幅</th>
                  <th>20日漲幅</th>
                  <th>60日漲幅</th>
                  <th>距離一年低點</th>
                  <th>成交量變化</th>
                  <th>位階狀態</th>
                  <th>補漲候選</th>
                  <th>備註</th>
                </tr>
              </thead>
              <tbody>${renderStockRows(concept)}</tbody>
            </table>
          </div>
        ` : `<div class="empty">MoneyDJ 主資料尚未載入。</div>`}
      </section>
    </section>
  `;
  bindEvents();
}

function bindEvents() {
  const search = document.querySelector("#conceptSearch");
  if (search) {
    search.addEventListener("input", (event) => {
      state.query = event.target.value;
      state.selectedId = "";
      render();
    });
  }
  document.querySelectorAll(".concept-lite-row").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedId = button.dataset.conceptId || "";
      render();
    });
  });
}

async function init() {
  const [moneydj, manualText, aliases, sourceLinks] = await Promise.all([
    loadJson("data/concepts-moneydj.json", { updated_at: "", source: "MoneyDJ", concepts: [] }),
    loadText("data/concepts-manual.csv", ""),
    loadJson("data/concept-aliases.json", {}),
    loadJson("data/concept-source-links.json", {}),
  ]);
  state.moneydj = {
    updated_at: moneydj.updated_at || "",
    source: moneydj.source || "MoneyDJ",
    concepts: Array.isArray(moneydj.concepts) ? moneydj.concepts : [],
  };
  state.manualRows = parseCsv(manualText);
  state.aliases = aliases && typeof aliases === "object" ? aliases : {};
  state.sourceLinks = sourceLinks && typeof sourceLinks === "object" ? sourceLinks : {};
  const params = new URLSearchParams(window.location.search);
  state.query = params.get("q") || "";
  render();
}

init().catch((error) => {
  console.error(error);
  app.innerHTML = `<section class="panel"><div class="error">產業題材庫載入失敗，請確認 MoneyDJ 主資料與手動補充檔案是否存在。</div></section>`;
});
