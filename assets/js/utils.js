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

export function bySymbol(stocks) {
  return new Map(stocks.map((stock) => [String(stock.symbol), stock]));
}

export function stockLabel(stockOrSymbol, maybeName) {
  if (typeof stockOrSymbol === "object") {
    return `${stockOrSymbol.name ?? ""} ${stockOrSymbol.symbol ?? stockOrSymbol.code ?? ""}`.trim();
  }
  return `${maybeName ?? ""} ${stockOrSymbol ?? ""}`.trim();
}

export function stockLink(symbol, name = "") {
  const safeSymbol = encodeURIComponent(symbol);
  return `<a class="stock-link" href="./stock.html?symbol=${safeSymbol}">${escapeHtml(stockLabel(symbol, name))}</a>`;
}

export function stockChipList(stocks = []) {
  if (!stocks.length) return `<span class="chip">無資料</span>`;
  return stocks
    .map((stock) => {
      const symbol = stock.symbol ?? stock.code;
      return `<span class="chip">${stockLink(symbol, stock.name)}</span>`;
    })
    .join("");
}

export function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
