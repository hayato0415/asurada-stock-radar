import { normalizeText, unique } from "./utils.js";

export function populateSelect(select, values, allLabel) {
  select.innerHTML = [
    `<option value="">${allLabel}</option>`,
    ...unique(values).sort().map((value) => `<option value="${value}">${value}</option>`)
  ].join("");
}

export function textMatches(item, query, fields) {
  const needle = normalizeText(query);
  if (!needle) return true;
  return fields.some((field) => normalizeText(item[field]).includes(needle));
}

export function minScoreMatches(score, minScore) {
  return Number(score) >= Number(minScore || 0);
}
