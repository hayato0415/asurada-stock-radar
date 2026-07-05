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
  const label = String(risk ?? "");
  if (["低", "正常", "穩健"].some((word) => label.includes(word))) return "good";
  if (["中", "觀察"].some((word) => label.includes(word))) return "warn";
  return "bad";
}

export function riskBadge(risk) {
  return `<span class="badge ${riskClass(risk)}">風險：${escapeHtml(risk ?? "--")}</span>`;
}

export function statusBadge(label, type = "good") {
  return `<span class="badge ${type}">${escapeHtml(label)}</span>`;
}
