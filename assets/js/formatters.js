export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (Number.isNaN(number)) return "--";
  return new Intl.NumberFormat("zh-Hant-TW", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(number);
}

export function formatPercent(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (Number.isNaN(number)) return "--";
  return `${formatNumber(number, digits)}%`;
}

export function formatSignedPercent(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (Number.isNaN(number)) return "--";
  const sign = number > 0 ? "+" : "";
  return `${sign}${formatNumber(number, digits)}%`;
}

export function formatDateTime(value) {
  if (!value) return "時間未標示";
  return String(value).replace("T", " ").replace("+08:00", "");
}

export function formatCurrency(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (Number.isNaN(number)) return "--";
  return formatNumber(number, digits);
}

export function valueClass(value) {
  const number = Number(value);
  if (Number.isNaN(number) || number === 0) return "value-flat";
  return number > 0 ? "value-up" : "value-down";
}
