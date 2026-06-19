const app = document.querySelector("#app");

const state = {
  categories: [],
  stocks: [],
  activeCode: "",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toNumber(value) {
  const number = Number(String(value ?? "").replace(/,/g, ""));
  return Number.isFinite(number) ? number : 0;
}

async function loadText(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} HTTP ${response.status}`);
  return response.text();
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  const csvText = String(text || "").replace(/^\uFEFF/, "");

  for (let index = 0; index < csvText.length; index += 1) {
    const char = csvText[index];
    const next = csvText[index + 1];
    if (inQuotes) {
      if (char === '"' && next === '"') {
        field += '"';
        index += 1;
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

function stocksForConcept(conceptCode) {
  return state.stocks
    .filter((stock) => stock.concept_code === conceptCode)
    .sort((a, b) => toNumber(a.stock_order) - toNumber(b.stock_order));
}

function quoteDate() {
  return state.stocks.find((stock) => stock.quote_date)?.quote_date || "-";
}

function conceptMatches(category, query) {
  const text = `${category.concept_code} ${category.concept_name}`.toLowerCase();
  return text.includes(query.toLowerCase());
}

function selectConcept(conceptCode) {
  state.activeCode = conceptCode;
  const select = document.querySelector("#conceptSelect");
  if (select) select.value = conceptCode;
  renderActiveConcept();
  renderConceptList();
}

function renderLayout() {
  const options = state.categories.map((category) =>
    `<option value="${escapeHtml(category.concept_code)}">${escapeHtml(category.concept_name)}</option>`
  ).join("");

  app.innerHTML = `
    <section class="panel">
      <div class="section-title">
        <h2>概念股資料庫</h2>
        <span>資料日期 ${escapeHtml(quoteDate())}</span>
      </div>
      <div class="grid cols-3">
        <div class="metric"><span>概念分類數量</span><strong>${state.categories.length}</strong></div>
        <div class="metric"><span>目前成分股數</span><strong id="activeStockCount">-</strong></div>
        <div class="metric"><span>資料日期</span><strong>${escapeHtml(quoteDate())}</strong></div>
      </div>
      <div class="filters">
        <label>概念搜尋<input id="conceptSearch" placeholder="AI、Apple、CoWoS、Google TPU、HDI、IC基板、眼鏡、3D全息投影"></label>
        <label>概念名稱<select id="conceptSelect">${options}</select></label>
      </div>
    </section>
    <section class="grid cols-2">
      <div class="panel">
        <div class="section-title"><h2>概念名稱</h2><span id="conceptListCount"></span></div>
        <div id="conceptList" class="chip-row"></div>
      </div>
      <div id="conceptDetail" class="panel"></div>
    </section>
  `;

  document.querySelector("#conceptSearch").addEventListener("input", renderConceptList);
  document.querySelector("#conceptSelect").addEventListener("change", (event) => {
    state.activeCode = event.target.value;
    renderConceptList();
    renderActiveConcept();
  });
}

function renderConceptList() {
  const query = document.querySelector("#conceptSearch")?.value.trim() || "";
  const filtered = query
    ? state.categories.filter((category) => conceptMatches(category, query))
    : state.categories;
  const list = document.querySelector("#conceptList");
  const count = document.querySelector("#conceptListCount");
  if (count) count.textContent = `${filtered.length} 個概念`;
  if (!list) return;
  list.innerHTML = filtered.map((category) => `
    <button class="secondary ${category.concept_code === state.activeCode ? "active" : ""}" data-code="${escapeHtml(category.concept_code)}">
      ${escapeHtml(category.concept_name)}
    </button>
  `).join("") || `<div class="empty">找不到符合關鍵字的概念名稱</div>`;
  list.querySelectorAll("button[data-code]").forEach((button) => {
    button.addEventListener("click", () => selectConcept(button.dataset.code));
  });
}

function renderActiveConcept() {
  const detail = document.querySelector("#conceptDetail");
  const count = document.querySelector("#activeStockCount");
  if (!detail) return;
  const category = state.categories.find((item) => item.concept_code === state.activeCode) || state.categories[0];
  if (!category) {
    detail.innerHTML = `<div class="error">沒有可顯示的概念資料。</div>`;
    return;
  }
  state.activeCode = category.concept_code;
  const stocks = stocksForConcept(category.concept_code);
  if (count) count.textContent = `${stocks.length}`;
  detail.innerHTML = `
    <div class="section-title">
      <h2>${escapeHtml(category.concept_name)}</h2>
      <span>成分股數 ${stocks.length}</span>
    </div>
    <div class="grid cols-2">
      <div class="metric"><span>資料日期</span><strong>${escapeHtml(stocks[0]?.quote_date || quoteDate())}</strong></div>
      <div class="metric"><span>成分股數</span><strong>${stocks.length}</strong></div>
    </div>
    ${renderStockTable(stocks)}
  `;
}

function renderStockTable(stocks) {
  if (!stocks.length) {
    return `<div class="empty">此概念暫無可用資料或抓取失敗</div>`;
  }
  return `
    <div class="table-wrap">
      <table class="concept-stock-table">
        <thead>
          <tr>
            <th>股票代號</th>
            <th>股票名稱</th>
            <th>收盤價</th>
            <th>漲跌</th>
            <th>漲跌幅</th>
            <th>成交量</th>
          </tr>
        </thead>
        <tbody>
          ${stocks.map((stock) => `
            <tr>
              <td><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.stock_id)}">${escapeHtml(stock.stock_id)}</a></td>
              <td><a class="stock-link" href="stock.html?code=${encodeURIComponent(stock.stock_id)}">${escapeHtml(stock.stock_name)}</a></td>
              <td>${escapeHtml(stock.close_price || "-")}</td>
              <td>${escapeHtml(stock.price_change || "-")}</td>
              <td>${escapeHtml(stock.change_pct || "-")}</td>
              <td>${escapeHtml(stock.volume || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function bootConcepts() {
  try {
    const [categories, stocks] = await Promise.all([
      loadCsv("data/moneydj_concept_categories.csv"),
      loadCsv("data/moneydj_concept_stocks.csv"),
    ]);
    state.categories = categories
      .filter((category) => category.concept_code && category.concept_name)
      .sort((a, b) => toNumber(a.display_order) - toNumber(b.display_order));
    state.stocks = stocks
      .filter((stock) => stock.concept_code && stock.stock_id)
      .sort((a, b) =>
        toNumber(a.display_order) - toNumber(b.display_order) ||
        toNumber(a.stock_order) - toNumber(b.stock_order)
      );
    state.activeCode = state.categories[0]?.concept_code || "";
    renderLayout();
    renderConceptList();
    renderActiveConcept();
  } catch (error) {
    app.innerHTML = `
      <section class="panel">
        <div class="section-title"><h2>概念股資料庫</h2><span>CSV 載入失敗</span></div>
        <div class="error">無法載入概念股資料：${escapeHtml(error.message)}</div>
      </section>
    `;
  }
}

bootConcepts();
