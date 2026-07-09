import { loadProcessedData, getItems, loadSiteMeta } from "./api.js";
import { $, escapeHtml, initTableFreezeToggles, renderEmpty, updateStickyTableHeaderOffsets } from "./utils.js";
import { formatDateTime, formatNumber, formatPercent, formatSignedPercent, valueClass } from "./formatters.js";

const WEIGHTS = {
  fundamentalScore: 0.3,
  technicalScore: 0.3,
  chipScore: 0.25,
  turnoverScore: 0.15
};

let factorRows = [];
let factorStatus = null;
let factorMeta = null;
let siteMeta = null;

function hasNumber(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function roundScore(value) {
  return Math.round(Number(value || 0) * 10) / 10;
}

function calculateTotalScore(item) {
  if (hasNumber(item.totalScore) && Number(item.totalScore) > 0) {
    return roundScore(item.totalScore);
  }

  return roundScore(
    Number(item.fundamentalScore || 0) * WEIGHTS.fundamentalScore
    + Number(item.technicalScore || 0) * WEIGHTS.technicalScore
    + Number(item.chipScore || 0) * WEIGHTS.chipScore
    + Number(item.turnoverScore || 0) * WEIGHTS.turnoverScore
  );
}

function scoreClass(score) {
  const number = Number(score);
  if (number >= 85) return "score-high";
  if (number >= 70) return "score-mid";
  return "score-low";
}

function factorScoreBadge(score) {
  return `<span class="score-badge ${scoreClass(score)}">${escapeHtml(formatNumber(score, 1))}</span>`;
}

function tradeTypeBadge(value) {
  const label = value || "未分類";
  const type = label === "短線" ? "short" : label === "中長期" ? "long" : "swing";
  return `<span class="trade-type-badge ${type}">${escapeHtml(label)}</span>`;
}

function riskLabelBadge(value) {
  const label = value || "正常";
  const typeMap = {
    "過熱": "hot",
    "正常": "normal",
    "冷門": "cold",
    "低流動": "illiquid"
  };
  return `<span class="risk-label-badge ${typeMap[label] || "normal"}">${escapeHtml(label)}</span>`;
}

function normalizeConcepts(item) {
  if (Array.isArray(item.concepts)) return item.concepts.filter(Boolean);
  if (typeof item.concepts === "string" && item.concepts.trim()) {
    return item.concepts.split(/[、,，/]/).map((text) => text.trim()).filter(Boolean);
  }
  return [];
}

function normalizeRow(item) {
  return {
    ...item,
    code: String(item.code ?? item.symbol ?? "").trim(),
    name: String(item.name ?? "").trim(),
    market: item.market || "--",
    industry: item.industry || "--",
    concepts: normalizeConcepts(item),
    close: item.close ?? item.trade_price ?? null,
    changePercent: item.changePercent ?? item.change_pct ?? null,
    volume: item.volume ?? null,
    tradeValue: item.tradeValue ?? item.trade_value ?? null,
    turnoverRate: item.turnoverRate ?? item.turnover_rate_pct ?? null,
    fundamentalScore: Number(item.fundamentalScore ?? item.fundamental_score ?? 0),
    technicalScore: Number(item.technicalScore ?? item.technical_score ?? 0),
    chipScore: Number(item.chipScore ?? item.chip_score ?? 0),
    turnoverScore: Number(item.turnoverScore ?? item.turnover_score ?? 0),
    tradeType: item.tradeType ?? item.trade_type ?? "波段",
    riskLabel: item.riskLabel ?? item.risk_label ?? "正常",
    updatedAt: item.updatedAt || item.updated_at || item.dataDate || item.data_date || "",
    dataDate: item.dataDate || item.data_date || item.updatedAt || item.updated_at || "",
    computedTotalScore: calculateTotalScore(item)
  };
}

function stockCodeLink(row) {
  return `<a class="stock-link" href="./stock.html?symbol=${encodeURIComponent(row.code)}">${escapeHtml(row.code)}</a>`;
}

function conceptsText(row) {
  if (!row.concepts.length) return "--";
  return row.concepts.map((concept) => `<span class="chip factor-concept-chip">${escapeHtml(concept)}</span>`).join("");
}

function formatVolume(value) {
  if (!hasNumber(value)) return "--";
  return formatNumber(value, 0);
}

function factorMetric(label, value, extraClass = "") {
  return `
    <div class="factor-card-metric ${extraClass}">
      <span>${escapeHtml(label)}</span>
      <strong>${value}</strong>
    </div>
  `;
}

function getSortValue(row, sortKey) {
  const map = {
    total: row.computedTotalScore,
    fundamental: row.fundamentalScore,
    technical: row.technicalScore,
    chip: row.chipScore,
    turnover: row.turnoverScore
  };
  return Number(map[sortKey] ?? row.computedTotalScore ?? 0);
}

function applyFilters() {
  const keyword = ($("#factorSearch")?.value || "").trim().toLowerCase();
  const tradeType = $("#tradeTypeFilter")?.value || "";
  const riskLabel = $("#factorRiskFilter")?.value || "";
  const sortKey = $("#factorSort")?.value || "total";

  return factorRows
    .filter((row) => {
      const haystack = [
        row.code,
        row.name,
        row.market,
        row.industry,
        row.tradeType,
        row.riskLabel,
        ...row.concepts
      ].join(" ").toLowerCase();
      return !keyword || haystack.includes(keyword);
    })
    .filter((row) => !tradeType || row.tradeType === tradeType)
    .filter((row) => !riskLabel || row.riskLabel === riskLabel)
    .sort((a, b) => getSortValue(b, sortKey) - getSortValue(a, sortKey));
}

function selectedLimit() {
  const value = Number($("#factorLimit")?.value || 10);
  return Number.isFinite(value) ? value : 10;
}

function renderStatusCard() {
  const panel = $("#factorStatusPanel");
  if (!panel) return;

  const ok = factorStatus?.ok === true;
  const warnings = factorStatus?.warnings || [];
  const failedReasons = factorStatus?.failed_reasons || [];
  const title = $("#factorStatusTitle");
  const badge = $("#factorStatusBadge");
  const text = $("#factorStatusText");
  const grid = $("#factorStatusGrid");
  const sources = $("#factorSourceList");

  panel.classList.toggle("status-ok", ok);
  panel.classList.toggle("status-warning", !ok || warnings.length > 0);

  if (title) title.textContent = ok ? "官方資料更新成功" : "官方資料更新未完成";
  if (badge) badge.textContent = ok ? "OK" : "保留上一版";
  if (text) {
    text.textContent = ok
      ? "本頁使用官方公開資料計算基本面、技術面、籌碼 / 交易力道與週轉率分數；新聞面不納入評分。"
      : "官方資料未成功更新，本頁保留上一版多因子評分資料，不以更新時間假裝內容已更新。";
  }

  if (grid) {
    const items = [
      ["行情日期", factorStatus?.latest_trade_date || "--"],
      ["產生時間", formatDateTime(factorStatus?.generated_at) || "--"],
      ["評分筆數", hasNumber(factorStatus?.rows_written) ? `${formatNumber(factorStatus.rows_written, 0)} 檔` : "--"],
      ["主檔股票數", hasNumber(factorStatus?.stock_master_count) ? formatNumber(factorStatus.stock_master_count, 0) : "--"],
      ["上市行情命中", hasNumber(factorStatus?.twse_quote_matched) ? formatNumber(factorStatus.twse_quote_matched, 0) : "--"],
      ["上櫃行情命中", hasNumber(factorStatus?.tpex_quote_matched) ? formatNumber(factorStatus.tpex_quote_matched, 0) : "--"]
    ];
    grid.innerHTML = items.map(([label, value]) => `
      <div class="factor-status-item">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(String(value))}</strong>
      </div>
    `).join("");
  }

  if (sources) {
    const sourceNames = Object.values(factorStatus?.official_source_used || {})
      .filter(Boolean)
      .map((value) => `<span class="chip">${escapeHtml(String(value))}</span>`)
      .join("");
    const notes = [...failedReasons, ...warnings]
      .map((value) => `<li>${escapeHtml(String(value))}</li>`)
      .join("");
    sources.innerHTML = `
      <div class="factor-source-row">
        <span>官方來源</span>
        <div>${sourceNames || "<span class=\"muted\">尚未標示</span>"}</div>
      </div>
      ${notes ? `<ul class="factor-status-notes">${notes}</ul>` : ""}
    `;
  }
}

function renderFactorRows() {
  const rows = applyFilters();
  const limit = selectedLimit();
  const visibleRows = rows.slice(0, limit);
  const body = $("#factorTableBody");
  const cardList = $("#factorCardList");
  const count = $("#factorCount");

  if (count) count.textContent = `${formatNumber(rows.length, 0)} 檔符合，顯示 ${formatNumber(visibleRows.length, 0)} 檔`;
  if (!body && !cardList) return;

  if (!factorRows.length) {
    if (body) body.innerHTML = `<tr><td colspan="18">${renderEmpty("目前尚無多因子評分資料")}</td></tr>`;
    if (cardList) cardList.innerHTML = renderEmpty("目前尚無多因子評分資料");
    return;
  }

  if (!rows.length) {
    if (body) body.innerHTML = `<tr><td colspan="18">${renderEmpty("沒有符合篩選條件的股票")}</td></tr>`;
    if (cardList) cardList.innerHTML = renderEmpty("沒有符合篩選條件的股票");
    return;
  }

  if (body) {
    body.innerHTML = visibleRows.map((row, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${stockCodeLink(row)}</td>
      <td>${escapeHtml(row.name || "--")}</td>
      <td>${escapeHtml(row.market || "--")}</td>
      <td>${escapeHtml(row.industry || "--")}</td>
      <td><div class="factor-concepts">${conceptsText(row)}</div></td>
      <td>${hasNumber(row.close) ? formatNumber(row.close, 2) : "--"}</td>
      <td class="${valueClass(row.changePercent)}">${hasNumber(row.changePercent) ? formatSignedPercent(row.changePercent, 2) : "--"}</td>
      <td>${formatVolume(row.volume)}</td>
      <td>${hasNumber(row.turnoverRate) ? formatPercent(row.turnoverRate, 2) : "--"}</td>
      <td>${factorScoreBadge(row.fundamentalScore)}</td>
      <td>${factorScoreBadge(row.technicalScore)}</td>
      <td>${factorScoreBadge(row.chipScore)}</td>
      <td>${factorScoreBadge(row.turnoverScore)}</td>
      <td class="factor-total-score">${factorScoreBadge(row.computedTotalScore)}</td>
      <td>${tradeTypeBadge(row.tradeType)}</td>
      <td>${riskLabelBadge(row.riskLabel)}</td>
      <td>${escapeHtml(formatDateTime(row.updatedAt || row.dataDate))}</td>
    </tr>
  `).join("");
  }

  if (cardList) {
    cardList.innerHTML = visibleRows.map((row, index) => `
      <article class="factor-card">
        <div class="factor-card-head">
          <div>
            <span class="factor-rank">#${index + 1}</span>
            <h3>${stockCodeLink(row)} ${escapeHtml(row.name || "--")}</h3>
            <p>${escapeHtml(row.market || "--")} · ${escapeHtml(row.industry || "--")}</p>
          </div>
          <div class="factor-card-score">
            <span>綜合</span>
            ${factorScoreBadge(row.computedTotalScore)}
          </div>
        </div>
        <div class="factor-card-tags">
          ${tradeTypeBadge(row.tradeType)}
          ${riskLabelBadge(row.riskLabel)}
        </div>
        <div class="factor-card-concepts">${conceptsText(row)}</div>
        <div class="factor-card-grid">
          ${factorMetric("收盤價", hasNumber(row.close) ? formatNumber(row.close, 2) : "--")}
          ${factorMetric("漲跌幅", hasNumber(row.changePercent) ? formatSignedPercent(row.changePercent, 2) : "--", valueClass(row.changePercent))}
          ${factorMetric("成交量", formatVolume(row.volume))}
          ${factorMetric("週轉率", hasNumber(row.turnoverRate) ? formatPercent(row.turnoverRate, 2) : "--")}
          ${factorMetric("基本面", factorScoreBadge(row.fundamentalScore))}
          ${factorMetric("技術面", factorScoreBadge(row.technicalScore))}
          ${factorMetric("籌碼", factorScoreBadge(row.chipScore))}
          ${factorMetric("週轉率分數", factorScoreBadge(row.turnoverScore))}
        </div>
        <div class="factor-card-date">更新日期：${escapeHtml(formatDateTime(row.updatedAt || row.dataDate) || "--")}</div>
      </article>
    `).join("");
  }
}

function bindFactorFilters() {
  ["factorSearch", "tradeTypeFilter", "factorRiskFilter", "factorSort", "factorLimit"].forEach((id) => {
    const element = $(`#${id}`);
    if (!element) return;
    element.addEventListener("input", renderFactorRows);
    element.addEventListener("change", renderFactorRows);
  });
}

function dataArrayFromLoaded(loaded, fileName) {
  if (loaded[fileName]?.error) return [];
  return getItems(loaded[fileName].data);
}

async function initFactorScorePage() {
  updateStickyTableHeaderOffsets();
  window.addEventListener("resize", updateStickyTableHeaderOffsets);
  initTableFreezeToggles();

  siteMeta = await loadSiteMeta();
  const loaded = await loadProcessedData([
    "factor-scores.json",
    "factor-scores.status.json",
    "factor-scores.meta.json"
  ]);

  factorStatus = loaded["factor-scores.status.json"]?.error ? null : loaded["factor-scores.status.json"].data;
  factorMeta = loaded["factor-scores.meta.json"]?.error ? null : loaded["factor-scores.meta.json"].data;
  renderStatusCard();

  if (loaded["factor-scores.json"].error) {
    $("#factorTableBody").innerHTML = `<tr><td colspan="18">${renderEmpty("多因子評分資料載入失敗，請確認 data/processed/factor-scores.json 是否存在。")}</td></tr>`;
    $("#factorUpdatedAt").textContent = "資料載入失敗";
    return;
  }

  factorRows = dataArrayFromLoaded(loaded, "factor-scores.json").map(normalizeRow);
  const factorDate = factorStatus?.latest_trade_date || factorRows.map((row) => row.updatedAt).filter(Boolean).sort().at(-1);
  const siteDate = siteMeta?.latest_trade_date || "";
  const syncNote = siteDate && factorDate && String(factorDate).slice(0, 10) !== String(siteDate).slice(0, 10)
    ? "｜多因子資料未同步"
    : "";
  $("#factorUpdatedAt").textContent = siteMeta?.generated_at
    ? `全站更新：${formatDateTime(siteMeta.generated_at)}｜多因子資料：${formatDateTime(factorDate)}${syncNote}`
    : (factorDate ? `資料日期：${formatDateTime(factorDate)}${syncNote}` : "更新時間未標示");

  if (factorMeta?.weights?.news === 0) {
    console.info("多因子評分：新聞面權重為 0，不參與分數、排名或篩選。");
  }

  bindFactorFilters();
  renderFactorRows();
}

initFactorScorePage().catch((error) => {
  console.error(error);
  $("#factorTableBody").innerHTML = `<tr><td colspan="18">${renderEmpty("多因子評分頁初始化失敗")}</td></tr>`;
  $("#factorUpdatedAt").textContent = "頁面初始化失敗";
});
