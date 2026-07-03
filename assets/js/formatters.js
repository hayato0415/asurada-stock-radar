export function formatNumber(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toLocaleString("zh-TW", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
}

export function formatPercent(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number.toFixed(digits)}%`;
}

export function formatSignedPercent(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(digits)}%`;
}

export function formatDateTime(value) {
  if (!value) return "時間未標示";
  return String(value).replace("T", " ").replace("+08:00", "");
}

export function formatCurrency(value, unit = "") {
  const formatted = formatNumber(value, 2);
  return formatted === "--" ? formatted : `${formatted}${unit}`;
}

export function valueClass(value) {
  const number = Number(value);
  if (number > 0) return "value-up";
  if (number < 0) return "value-down";
  return "value-flat";
}
