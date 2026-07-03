export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function renderEmpty(message = "目前沒有資料") {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

export function normalizeText(value) {
  return String(value ?? "").trim().toLowerCase();
}

export function bySymbol(stocks = []) {
  return new Map(
    stocks
      .map((stock) => [String(stock.symbol ?? stock.code ?? stock.stock_id ?? "").trim(), stock])
      .filter(([symbol]) => symbol)
  );
}

export function stockLabel(stockOrSymbol, maybeName) {
  if (typeof stockOrSymbol === "object" && stockOrSymbol !== null) {
    const symbol = stockOrSymbol.symbol ?? stockOrSymbol.code ?? stockOrSymbol.stock_id ?? "";
    return `${stockOrSymbol.name ?? stockOrSymbol.stock_name ?? ""} ${symbol}`.trim();
  }
  return `${maybeName ?? ""} ${stockOrSymbol ?? ""}`.trim();
}

export function stockLink(symbol, name = "") {
  const safeSymbol = encodeURIComponent(symbol ?? "");
  return `<a class="stock-link" href="./stock.html?symbol=${safeSymbol}">${escapeHtml(stockLabel(symbol, name))}</a>`;
}

export function stockChipList(stocks = [], limit = 6) {
  if (!stocks.length) return `<span class="chip">--</span>`;
  return stocks
    .slice(0, limit)
    .map((stock) => {
      const symbol = stock.symbol ?? stock.code ?? stock.stock_id;
      return `<span class="chip">${stockLink(symbol, stock.name ?? stock.stock_name)}</span>`;
    })
    .join("");
}

export function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

export function clamp(value, min = 0, max = 100) {
  const number = Number(value);
  if (Number.isNaN(number)) return min;
  return Math.max(min, Math.min(max, number));
}

export function initTableFreezeToggles() {
  const toggles = document.querySelectorAll("[data-table-freeze-toggle]");

  toggles.forEach((toggle) => {
    const targetSelector = toggle.getAttribute("data-table-freeze-toggle");
    const label = toggle.getAttribute("data-freeze-label") || "凍結欄位";
    const table = targetSelector ? document.querySelector(targetSelector) : null;
    if (!table) return;

    const setFreezeState = (enabled) => {
      table.classList.toggle("is-freeze-enabled", enabled);
      toggle.classList.toggle("is-active", enabled);
      toggle.setAttribute("aria-pressed", String(enabled));
      toggle.textContent = enabled ? `${label}：開` : `${label}：關`;
    };

    setFreezeState(!toggle.classList.contains("is-off"));
    toggle.addEventListener("click", () => {
      setFreezeState(!toggle.classList.contains("is-active"));
    });
  });
}

export function updateStickyTableHeaderOffsets() {
  const header = document.querySelector(".app-header");
  const offset =
    header && getComputedStyle(header).position === "sticky"
      ? Math.ceil(header.getBoundingClientRect().height)
      : 0;

  document.documentElement.style.setProperty("--factor-table-sticky-top", `${offset}px`);
}
