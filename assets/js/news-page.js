import { loadProcessedData, getItems } from "./api.js";
import { $, escapeHtml, renderEmpty, stockChipList } from "./utils.js";
import { formatDateTime } from "./formatters.js";
import { scoreBadge, statusBadge } from "./scoring-ui.js";

function newsCard(item) {
  const link = item.source_url
    ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>`
    : escapeHtml(item.title);

  return `
    <article class="news-card">
      <h3>${link}</h3>
      <div class="news-meta">
        <span>${formatDateTime(item.published_at)}</span>
        <span>${escapeHtml(item.source_name)}</span>
        <span>來源等級 ${escapeHtml(item.source_grade)}</span>
        <span>${scoreBadge(item.news_score)}</span>
        <span>${statusBadge(item.impact, item.impact === "偏空" ? "bad" : "good")}</span>
      </div>
      <p>${escapeHtml(item.summary)}</p>
      <p><strong>AI 判斷：</strong>${escapeHtml(item.ai_judgement)}</p>
      <p><strong>操作意義：</strong>${escapeHtml(item.operation_meaning)}</p>
      <div class="stock-chip-list">${stockChipList(item.stocks ?? [])}</div>
    </article>
  `;
}

function renderList(root, items, emptyText) {
  root.innerHTML = items.length ? items.map(newsCard).join("") : renderEmpty(emptyText);
}

function renderCatalysts(items) {
  const counts = items.reduce((acc, item) => {
    acc[item.theme] = (acc[item.theme] || 0) + Number(item.news_score || 0);
    return acc;
  }, {});
  $("#themeCatalystList").innerHTML = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([theme, score]) => `<span class="chip">${escapeHtml(theme)} · ${Math.round(score)}</span>`)
    .join("");
}

async function initNews() {
  const loaded = await loadProcessedData(["news_events.json"]);
  const payload = loaded["news_events.json"].data;
  const items = getItems(payload).sort((a, b) => Number(b.news_score) - Number(a.news_score));
  $("#newsUpdatedAt").textContent = `資料更新：${formatDateTime(payload?.updated_at)}`;

  renderList($("#topNewsList"), items.slice(0, 5), "目前沒有重點新聞");
  renderCatalysts(items);
  renderList($("#stockNewsList"), items.filter((item) => item.stocks?.length).slice(0, 8), "目前沒有個股新聞");
  renderList($("#riskNewsList"), items.filter((item) => item.impact === "偏空").slice(0, 8), "目前沒有利空風險新聞");
  renderList($("#overseasNewsList"), items.filter((item) => item.region === "國際").slice(0, 8), "目前沒有海外連動新聞");
}

initNews().catch((error) => {
  console.error(error);
  $("#topNewsList").innerHTML = renderEmpty("新聞資料載入失敗");
});
