const app = document.querySelector("#app");

const state = {
  taxonomy: null,
  categories: [],
  activeTab: "listed",
  query: "",
};

const GROUPS = [
  ["listed", "上市類股", "listedIndustryList"],
  ["otc", "上櫃類股", "otcIndustryList"],
  ["electronics", "電子產業", "electronicsIndustryList"],
  ["supplyChain", "供應鏈分類", "supplyChainList"],
  ["themes", "概念股", "marketThemeList"],
  ["groups", "集團股", "groupStockList"],
  ["indices", "指數成分股", "indexComponentList"],
  ["manual", "手動新增題材", "manualThemeList"],
];

const GROUP_LABELS = Object.fromEntries(GROUPS.map(([id, label]) => [id, label]));

const CONFIDENCE_LABELS = {
  A: "A 高可信",
  B: "B 多來源確認",
  C: "C 題材觀察",
  D: "D 低可信",
  E: "E 不列入正式分類",
};

const QUALITY_LABELS = {
  complete: "complete",
  partial: "partial",
  needs_fill: "needs_fill",
  high: "high",
  medium: "medium",
  low: "low",
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

function validUrl(url) {
  return String(url || "").trim();
}

async function loadJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} HTTP ${response.status}`);
  return response.json();
}

function conceptDetailHref(category) {
  return category.url || `concept-detail.html?id=${encodeURIComponent(category.id)}`;
}

function stockHref(code) {
  return `stock.html?code=${encodeURIComponent(code)}`;
}

function confidenceBadge(value) {
  const confidence = value || "C";
  return `<span class="confidence-badge confidence-${escapeHtml(confidence)}">${escapeHtml(confidence)}</span>`;
}

function confidenceText(value) {
  return CONFIDENCE_LABELS[value] || `${value || "-"} 待確認`;
}

function categorySearchText(category) {
  const stocksText = [
    ...(category.representative_stocks || []),
    ...(category.all_stocks || []),
  ].map((stock) => `${stock.code} ${stock.name}`).join(" ");
  return normalizeText([
    category.id,
    category.name,
    category.type,
    category.display_group,
    (category.aliases || []).join(" "),
    stocksText,
  ].join(" "));
}

function categoryMatches(category, query = state.query) {
  const normalized = normalizeText(query);
  if (!normalized) return true;
  return categorySearchText(category).includes(normalized);
}

function categoriesForGroup(groupId) {
  return state.categories
    .filter((category) => category.display_group === groupId)
    .filter(categoryMatches)
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "zh-Hant"));
}

function renderConceptIndexLink(category) {
  return `
    <a class="concept-index-link" href="${escapeHtml(conceptDetailHref(category))}">
      <span class="concept-name">${escapeHtml(category.name)}</span>
      <span class="concept-meta">${escapeHtml(category.stock_count ?? (category.all_stocks || []).length ?? 0)} 檔</span>
      <span class="concept-source-count">${escapeHtml(category.source_count ?? (category.sources || []).length ?? 0)} 來源</span>
      ${confidenceBadge(category.confidence)}
      <span class="concept-quality">${escapeHtml(category.coverage_status || category.data_quality || "partial")}</span>
    </a>
  `;
}

function renderConceptIndexGroup(groupId, rootId) {
  const root = document.querySelector(`#${rootId}`);
  if (!root) return;
  const categories = categoriesForGroup(groupId);
  root.innerHTML = categories.map(renderConceptIndexLink).join("") ||
    `<div class="empty">目前沒有符合搜尋條件的${escapeHtml(GROUP_LABELS[groupId] || "分類")}。</div>`;
}

function renderSearchResults() {
  const root = document.querySelector("#conceptSearchResults");
  if (!root) return;
  const query = state.query.trim();
  if (!query) {
    root.innerHTML = "";
    return;
  }
  const results = state.categories.filter((category) => categoryMatches(category, query));
  root.innerHTML = `
    <section class="concept-index-panel is-active">
      <div class="section-title">
        <h2>搜尋結果</h2>
        <span>${results.length} 個分類</span>
      </div>
      <div class="concept-link-grid">
        ${results.map(renderConceptIndexLink).join("") || `<div class="empty">找不到符合的題材、產業或股票。</div>`}
      </div>
    </section>
  `;
}

function initConceptIndexTabs() {
  const tabs = Array.from(document.querySelectorAll(".concept-index-tab"));
  const panels = Array.from(document.querySelectorAll(".concept-index-panel"));
  if (!tabs.length) return;

  const activate = (tabId, updateHash = true) => {
    const target = GROUPS.some(([id]) => id === tabId) ? tabId : "listed";
    state.activeTab = target;
    tabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.conceptTab === target));
    panels.forEach((panel) => panel.classList.toggle("is-active", panel.dataset.conceptPanel === target));
    if (updateHash && window.location.hash.slice(1) !== target) {
      history.replaceState(null, "", `#${target}`);
    }
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activate(tab.dataset.conceptTab || "listed"));
  });
  const hash = window.location.hash.replace("#", "");
  activate(hash || "listed", Boolean(hash));
  window.addEventListener("hashchange", () => activate(window.location.hash.replace("#", "") || "listed", false));
}

function initConceptSearch() {
  const input = document.querySelector("#conceptSearchInput");
  if (!input) return;
  input.addEventListener("input", (event) => {
    state.query = event.target.value;
    GROUPS.forEach(([groupId, , rootId]) => renderConceptIndexGroup(groupId, rootId));
    renderSearchResults();
    const nextInput = document.querySelector("#conceptSearchInput");
    if (nextInput) {
      nextInput.focus();
      nextInput.setSelectionRange(state.query.length, state.query.length);
    }
  });
}

function renderConceptOverview() {
  app.innerHTML = `
    <section class="concept-overview">
      <div class="concept-overview-header">
        <div>
          <h1>產業題材庫</h1>
          <p>依官方產業、電子子產業、供應鏈、概念股與集團股整理。</p>
        </div>
        <span>更新：${escapeHtml(state.taxonomy?.generated_at || "-")}</span>
      </div>

      <div class="concept-search-bar">
        <input id="conceptSearchInput" type="search" placeholder="搜尋題材、產業、股票代號或名稱" value="${escapeHtml(state.query)}">
      </div>

      <nav class="concept-index-tabs" aria-label="產業題材分類">
        ${GROUPS.map(([id, label]) => `
          <button class="concept-index-tab ${state.activeTab === id ? "is-active" : ""}" type="button" data-concept-tab="${id}">
            ${escapeHtml(label)}
          </button>
        `).join("")}
      </nav>

      <div id="conceptSearchResults"></div>

      ${GROUPS.map(([id, , rootId]) => `
        <section class="concept-index-panel ${state.activeTab === id ? "is-active" : ""}" data-concept-panel="${id}">
          <div class="section-title">
            <h2>${escapeHtml(GROUP_LABELS[id])}</h2>
            <span>${categoriesForGroup(id).length} 個分類</span>
          </div>
          <div id="${escapeHtml(rootId)}" class="concept-link-grid"></div>
        </section>
      `).join("")}
    </section>
  `;
  GROUPS.forEach(([groupId, , rootId]) => renderConceptIndexGroup(groupId, rootId));
  initConceptIndexTabs();
  initConceptSearch();
  renderSearchResults();
}

function renderStockChips(stocks = []) {
  if (!stocks.length) return `<span class="muted">代表股待補</span>`;
  return stocks.map((stock) =>
    `<a class="concept-chip stock-chip" href="${stockHref(stock.code)}">${escapeHtml(stock.code)} ${escapeHtml(stock.name)}</a>`
  ).join("");
}

function renderSourceBreakdown(rows = []) {
  if (!rows.length) return `<div class="empty">來源比對資料待補。</div>`;
  return `
    <div class="table-wrap">
      <table class="concept-source-table">
        <thead>
          <tr><th>來源</th><th>狀態</th><th>說明</th></tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td data-label="來源">${escapeHtml(row.source || "-")}</td>
              <td data-label="狀態">${escapeHtml(row.status || "-")}</td>
              <td data-label="說明">${escapeHtml(row.note || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderDetailStockTable(stocks = []) {
  if (!stocks.length) return `<div class="empty">完整成分股待補，請先查看代表股與來源比對。</div>`;
  return `
    <div class="table-wrap">
      <table class="concept-stock-table">
        <thead>
          <tr>
            <th>股票代號</th>
            <th>股票名稱</th>
            <th>市場</th>
            <th>官方產業</th>
            <th>供應鏈分類</th>
            <th>市場題材</th>
            <th>可信度</th>
            <th>資料品質</th>
            <th>驗證依據</th>
          </tr>
        </thead>
        <tbody>
          ${stocks.map((stock) => `
            <tr>
              <td data-label="股票代號"><a class="stock-link" href="${stockHref(stock.code)}">${escapeHtml(stock.code)}</a></td>
              <td data-label="股票名稱"><a class="stock-link" href="${stockHref(stock.code)}">${escapeHtml(stock.name)}</a></td>
              <td data-label="市場">${escapeHtml(stock.market || "-")}</td>
              <td data-label="官方產業">${escapeHtml(stock.official_industry || "-")}</td>
              <td data-label="供應鏈分類">${escapeHtml(stock.supply_chain || "-")}</td>
              <td data-label="市場題材">${escapeHtml(stock.market_theme || "-")}</td>
              <td data-label="可信度">${confidenceBadge(stock.confidence)}</td>
              <td data-label="資料品質">${escapeHtml(stock.data_quality || "-")}</td>
              <td data-label="驗證依據">${escapeHtml((stock.evidence || []).join("、") || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderSourcesList(sources = []) {
  if (!sources.length) return `<span class="muted">來源待補</span>`;
  return sources.map((source) => {
    if (typeof source === "string") return `<span class="concept-chip">${escapeHtml(source)}</span>`;
    const name = escapeHtml(source.name || "來源");
    const url = validUrl(source.url);
    return url
      ? `<a class="concept-chip" href="${escapeHtml(url)}" target="_blank" rel="noopener">${name}</a>`
      : `<span class="concept-chip">${name}</span>`;
  }).join("");
}

async function renderConceptDetail() {
  const id = new URLSearchParams(window.location.search).get("id") || "";
  const category = state.categories.find((item) => item.id === id);
  if (!category) {
    app.innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>找不到此題材資料</h2><span>${escapeHtml(id || "未指定 id")}</span></div>
        <p class="mode-note">請回到產業題材庫重新選擇分類。</p>
        <a class="solid-link" href="concepts.html">回到產業題材庫</a>
      </section>
    `;
    return;
  }

  app.innerHTML = `
    <section class="panel concept-detail-layout">
      <a class="secondary-link" href="concepts.html#${escapeHtml(category.display_group || "listed")}">← 回到產業題材庫</a>
      <div class="section-title">
        <div>
          <h2>${escapeHtml(category.name)}</h2>
          <p class="mode-note">${escapeHtml(category.type || GROUP_LABELS[category.display_group] || "分類")}</p>
        </div>
        <span>更新：${escapeHtml(state.taxonomy?.generated_at || "-")}</span>
      </div>
      <div class="concept-detail-summary">
        <div><span>來源數</span><strong>${escapeHtml(category.source_count ?? (category.sources || []).length ?? 0)}</strong></div>
        <div><span>可信度</span><strong>${escapeHtml(confidenceText(category.confidence))}</strong></div>
        <div><span>資料完整度</span><strong>${escapeHtml(category.coverage_status || category.data_quality || "partial")}</strong></div>
        <div><span>成分股數</span><strong>${escapeHtml(category.stock_count ?? (category.all_stocks || []).length ?? 0)}</strong></div>
      </div>
      <div class="concept-detail-block">
        <h3>資料完整度警示</h3>
        <p>${escapeHtml(category.coverage_check?.note || "資料完整度待補。")}</p>
      </div>
      <div class="concept-detail-block">
        <h3>同義詞</h3>
        <div class="concept-chip-row">${(category.aliases || []).map((alias) => `<span class="concept-chip">${escapeHtml(alias)}</span>`).join("") || `<span class="muted">同義詞待補</span>`}</div>
      </div>
      <div class="concept-detail-block">
        <h3>代表股</h3>
        <div class="concept-chip-row">${renderStockChips(category.representative_stocks)}</div>
      </div>
      <div class="concept-detail-block">
        <h3>資料來源</h3>
        <div class="concept-chip-row">${renderSourcesList(category.sources)}</div>
      </div>
      <div class="concept-detail-block">
        <h3>來源比對</h3>
        ${renderSourceBreakdown(category.source_breakdown)}
      </div>
      <div class="concept-detail-block">
        <h3>完整成分股</h3>
        ${renderDetailStockTable(category.all_stocks)}
      </div>
    </section>
  `;
}

async function bootConcepts() {
  try {
    state.taxonomy = await loadJson("data/concepts-taxonomy.json");
    state.categories = Array.isArray(state.taxonomy.categories) ? state.taxonomy.categories : [];
    if (!state.categories.length) throw new Error("concepts-taxonomy.json 沒有 categories");
    const page = document.body.dataset.page || "concepts";
    if (page === "concept-detail") {
      await renderConceptDetail();
    } else {
      state.query = new URLSearchParams(window.location.search).get("q") || "";
      renderConceptOverview();
    }
  } catch (error) {
    app.innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>產業題材庫</h2><span>資料載入失敗</span></div>
        <div class="error">無法載入 concepts-taxonomy.json：${escapeHtml(error.message)}</div>
      </section>
    `;
  }
}

bootConcepts();
