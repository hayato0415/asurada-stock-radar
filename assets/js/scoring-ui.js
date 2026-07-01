import { escapeHtml } from "./utils.js";

export function scoreClass(score) {
  const number = Number(score);
  if (number >= 85) return "score-high";
  if (number >= 70) return "score-mid";
  return "score-low";
}

export function scoreBadge(score) {
  return `<span class="score-badge ${scoreClass(score)}">${escapeHtml(score ?? "--")}</span>`;
}

export function riskClass(risk) {
  if (risk === "低") return "good";
  if (risk === "中") return "warn";
  return "bad";
}

export function riskBadge(risk) {
  return `<span class="badge ${riskClass(risk)}">風險：${escapeHtml(risk ?? "--")}</span>`;
}

export function statusBadge(label, type = "good") {
  return `<span class="badge ${type}">${escapeHtml(label)}</span>`;
}
