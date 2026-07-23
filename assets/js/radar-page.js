import { loadProcessedData } from "./api.js?v=20260723-top10";
import { formatDateTime, formatNumber, formatPercent, valueClass } from "./formatters.js";
import { $, escapeHtml, stockLink } from "./utils.js";

const FILES = [
  "ai-top10-daily.json",
  "ai-persistence-weekly.json",
  "ai-persistence-monthly.json",
];

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function emptyRow(colspan, message) {
  return `<tr><td colspan="${colspan}"><div class="empty-state">${escapeHtml(message)}</div></td></tr>`;
}

function rankChange(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return `<span class="rank-flat">--</span>`;
  if (number > 0) return `<span class="value-up">↑${number}</span>`;
  if (number < 0) return `<span class="value-down">↓${Math.abs(number)}</span>`;
  return `<span class="rank-flat">—</span>`;
}

function trendBadge(value) {
  const text = String(value || "資料不足");
  const className = text === "上升" ? "good" : text === "下降" ? "bad" : "warn";
  return `<span class="badge ${className}">${escapeHtml(text)}</span>`;
}

function statusBadges(labels = []) {
  if (!labels.length) return `<span class="badge">持續觀察</span>`;
  return labels
    .map((label) => {
      const className = ["新進榜", "重返榜", "排名上升", "月度常駐"].includes(label)
        ? "good"
        : ["排名下降", "分數轉弱", "單日爆發"].includes(label)
          ? "warn"
          : "";
      return `<span class="badge ${className}">${escapeHtml(label)}</span>`;
    })
    .join("");
}

function conceptsText(item) {
  const values = [item.industry, ...(Array.isArray(item.concepts) ? item.concepts : [])].filter(Boolean);
  return [...new Set(values)].join("／") || "未分類";
}

function renderStatus(daily, extraWarnings = []) {
  setText("#latestTradeDate", daily.latestTradeDate || daily.latest_trade_date || "--");
  setText("#siteGeneratedAt", formatDateTime(daily.generatedAt || daily.generated_at));
  setText("#scoreVersion", daily.scoreVersion || "--");
  setText("#validScoreCount", `${Number(daily.validScoreCount || 0).toLocaleString("zh-TW")} 檔`);
  setText("#top10Status", daily.ok === true && daily.items?.length === 10 ? "成功" : "異常");
  setText("#historyTradingDays", `${Number(daily.historyTradingDays || 0)} 日`);
  setText("#radarUpdatedAt", `資料更新：${formatDateTime(daily.generatedAt || daily.generated_at)}`);

  const warnings = [...(daily.warnings || []), ...extraWarnings].filter(Boolean);
  const root = $("#radarWarnings");
  if (!root) return;
  root.innerHTML = warnings.length
    ? warnings.map((warning) => `<div class="tracking-alert tracking-alert-warn">${escapeHtml(warning)}</div>`).join("")
    : `<div class="tracking-alert tracking-alert-ok">正式評分、Top 10 與歷史快照日期同步。</div>`;
}

function renderToday(daily) {
  const items = Array.isArray(daily.items) ? daily.items : [];
  setText("#todayCount", `${items.length} / 10`);
  const body = $("#todayTop10Body");
  const cards = $("#todayTop10Cards");
  if (!items.length) {
    if (body) body.innerHTML = emptyRow(18, "今日沒有可用的正式 Top 10。");
    if (cards) cards.innerHTML = `<div class="empty-state">今日沒有可用的正式 Top 10。</div>`;
    return;
  }

  if (body) {
    body.innerHTML = items.map((item) => `
      <tr>
        <td><strong>#${item.rank}</strong></td>
        <td>${rankChange(item.rankChange)}</td>
        <td>${stockLink(item.code, item.name)}</td>
        <td>${escapeHtml(item.market || "--")}</td>
        <td class="tracking-concepts">${escapeHtml(conceptsText(item))}</td>
        <td><span class="score-badge">${formatNumber(item.totalScore, 1)}</span></td>
        <td>${formatNumber(item.fundamentalScore, 1)}</td>
        <td>${formatNumber(item.technicalScore, 1)}</td>
        <td>${formatNumber(item.chipScore, 1)}</td>
        <td>${formatNumber(item.turnoverScore, 1)}</td>
        <td>${item.appearances5d ?? "--"}</td>
        <td>${item.appearances20d ?? "--"}</td>
        <td>${item.consecutiveDays ?? "--"}</td>
        <td>${trendBadge(item.scoreTrend)}</td>
        <td>${escapeHtml(item.tradeType || "--")}</td>
        <td><span class="badge ${item.riskLabel === "過熱" ? "warn" : ""}">${escapeHtml(item.riskLabel || "--")}</span></td>
        <td><div class="status-badge-list">${statusBadges(item.statusLabels)}</div></td>
        <td>${escapeHtml(item.dataDate || "--")}</td>
      </tr>
    `).join("");
  }

  if (cards) {
    cards.innerHTML = items.map((item) => `
      <article class="tracking-stock-card">
        <div class="tracking-card-head">
          <span class="tracking-rank">#${item.rank}</span>
          ${stockLink(item.code, item.name)}
          ${rankChange(item.rankChange)}
        </div>
        <p>${escapeHtml(item.market || "--")}・${escapeHtml(conceptsText(item))}</p>
        <div class="tracking-card-score">
          <strong>${formatNumber(item.totalScore, 1)}</strong>
          <span>基本 ${formatNumber(item.fundamentalScore, 1)}</span>
          <span>技術 ${formatNumber(item.technicalScore, 1)}</span>
          <span>籌碼 ${formatNumber(item.chipScore, 1)}</span>
          <span>熱度 ${formatNumber(item.turnoverScore, 1)}</span>
        </div>
        <div class="tracking-card-meta">
          <span>5 日 ${item.appearances5d ?? "--"} 次</span>
          <span>20 日 ${item.appearances20d ?? "--"} 次</span>
          <span>連續 ${item.consecutiveDays ?? "--"} 日</span>
          <span>${escapeHtml(item.scoreTrend || "資料不足")}</span>
        </div>
        <div class="status-badge-list">${statusBadges(item.statusLabels)}</div>
      </article>
    `).join("");
  }
}

function renderContinuous(daily) {
  const items = Array.isArray(daily.continuous) ? daily.continuous : [];
  setText("#continuousCount", `${items.length} 檔`);
  const root = $("#continuousList");
  if (!root) return;
  root.innerHTML = items.length
    ? items.map((item) => `
        <article class="persistence-card">
          <div class="tracking-card-head">
            ${stockLink(item.code, item.name)}
            <span class="score-badge">${formatNumber(item.totalScore, 1)}</span>
          </div>
          <strong>連續 ${item.consecutiveDays} 個交易日</strong>
          <p>近 5 日 ${item.appearances5d} 次・近 20 日 ${item.appearances20d} 次・目前第 ${item.rank} 名</p>
          <div class="status-badge-list">${statusBadges(item.statusLabels)}</div>
        </article>
      `).join("")
    : `<div class="empty-state">目前沒有連續 2 日以上入榜的股票。</div>`;
}

function renderWeekly(payload) {
  const body = $("#weeklyBody");
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const dates = Array.isArray(payload?.tradingDates) ? payload.tradingDates : [];
  setText(
    "#weeklyWindow",
    dates.length ? `使用 ${dates.length} 個有效交易日：${dates.join("、")}` : "尚無週榜交易日。",
  );
  if (!body) return;
  body.innerHTML = items.length
    ? items.map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${stockLink(item.code, item.name)}</td>
          <td><strong>${item.appearances5d}</strong></td>
          <td>${formatNumber(item.averageRank5d, 2)}</td>
          <td>${item.bestRank5d}</td>
          <td>${item.latestRank ?? "--"}</td>
          <td>${rankChange(item.rankChange)}</td>
          <td>${item.consecutiveDays}</td>
          <td>${formatNumber(item.averageScore5d, 2)}</td>
          <td>${formatNumber(item.latestScore, 1)}</td>
          <td>${trendBadge(item.scoreTrend)}</td>
          <td>${escapeHtml(item.firstSeenDate)}<br>${escapeHtml(item.lastSeenDate)}</td>
        </tr>
      `).join("")
    : emptyRow(12, "歷史快照不足，尚無近 5 日週榜。");
}

function renderMonthly(payload) {
  const body = $("#monthlyBody");
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const dates = Array.isArray(payload?.tradingDates) ? payload.tradingDates : [];
  setText(
    "#monthlyWindow",
    dates.length ? `使用 ${dates.length} 個有效交易日：${dates.join("、")}` : "尚無月榜交易日。",
  );
  if (!body) return;
  body.innerHTML = items.length
    ? items.map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${stockLink(item.code, item.name)}</td>
          <td><strong>${item.appearances20d}</strong></td>
          <td>${formatPercent(Number(item.appearanceRate20d || 0) * 100, 1)}</td>
          <td>${formatNumber(item.averageRank20d, 2)}</td>
          <td>${item.bestRank20d}</td>
          <td>${item.consecutiveDays}</td>
          <td>${formatNumber(item.averageScore20d, 2)}</td>
          <td>${formatNumber(item.latestScore, 1)}</td>
          <td>${trendBadge(item.scoreTrend20d)}</td>
          <td>${escapeHtml(item.firstSeenDate)}<br>${escapeHtml(item.lastSeenDate)}</td>
        </tr>
      `).join("")
    : emptyRow(11, "歷史快照不足，尚無近 20 日月榜。");
}

function renderChangeList(selector, items, emptyMessage) {
  const root = $(selector);
  if (!root) return;
  root.innerHTML = items.length
    ? items.map((item) => {
        const currentRank = item.latestRank ?? item.rank;
        const rankText = currentRank
          ? `今日第 ${currentRank} 名`
          : `昨日第 ${item.previousRank ?? "--"} 名`;
        return `
          <article class="change-item">
            <div>${stockLink(item.code, item.name)} <span class="badge">${escapeHtml(item.entryStatus)}</span></div>
            <span>${rankText}</span>
          </article>
        `;
      }).join("")
    : `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
}

function renderFailure(message) {
  setText("#top10Status", "失敗");
  setText("#radarUpdatedAt", "資料載入失敗");
  const warning = $("#radarWarnings");
  if (warning) {
    warning.innerHTML = `<div class="tracking-alert tracking-alert-bad">${escapeHtml(message)}</div>`;
  }
  const tables = [
    ["#todayTop10Body", 18],
    ["#weeklyBody", 12],
    ["#monthlyBody", 11],
  ];
  tables.forEach(([selector, colspan]) => {
    const body = $(selector);
    if (body) body.innerHTML = emptyRow(colspan, message);
  });
  ["#todayTop10Cards", "#continuousList", "#newEntrantsList", "#droppedList"].forEach((selector) => {
    const root = $(selector);
    if (root) root.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
  });
}

async function loadAndRender() {
  setText("#top10Status", "讀取中");
  const loaded = await loadProcessedData(FILES);
  const dailyResult = loaded["ai-top10-daily.json"];
  const weeklyResult = loaded["ai-persistence-weekly.json"];
  const monthlyResult = loaded["ai-persistence-monthly.json"];

  if (dailyResult.error || !dailyResult.data || dailyResult.data.ok !== true) {
    console.error(dailyResult.error || dailyResult.data);
    renderFailure("正式多因子評分資料載入失敗，保留上一版或停止更新。");
    return;
  }

  const daily = dailyResult.data;
  const extraWarnings = [];
  if (weeklyResult.error || !weeklyResult.data?.ok) {
    extraWarnings.push(`近 5 日週榜載入失敗：${weeklyResult.error?.message || "資料狀態異常"}`);
  }
  if (monthlyResult.error || !monthlyResult.data?.ok) {
    extraWarnings.push(`近 20 日月榜載入失敗：${monthlyResult.error?.message || "資料狀態異常"}`);
  }

  renderStatus(daily, extraWarnings);
  renderToday(daily);
  renderContinuous(daily);
  renderWeekly(weeklyResult.data);
  renderMonthly(monthlyResult.data);
  renderChangeList("#newEntrantsList", daily.newEntrants || [], "今日沒有新進榜或重返榜股票。");
  renderChangeList("#droppedList", daily.dropped || [], "今日沒有跌出榜股票。");
}

export function initRadarPage() {
  $("#reloadRadarData")?.addEventListener("click", loadAndRender);
  loadAndRender();
}

initRadarPage();
