import { loadProcessedData, getItems } from "./api.js";
import { $, bySymbol, escapeHtml, renderEmpty, stockChipList, stockLink } from "./utils.js";
import { formatNumber, formatSignedPercent, formatDateTime, valueClass } from "./formatters.js";
import { riskBadge, scoreBadge } from "./scoring-ui.js";

const FILES = [
  "stocks_master.json",
  "market_snapshot.json",
  "ai_scores_daily.json",
  "news_events.json",
  "theme_stats.json"
];

const TRANSPARENCY_CARDS = [
  {
    title: "首頁",
    purpose: "快速檢查大盤收盤、漲跌、成交金額、市場溫度與漲跌家數。",
    source: "data/processed/market_snapshot.json",
    canJudge: "盤勢方向、市場熱度、漲跌家數是否擴散。",
    cannotJudge: "不能單獨判斷個股買賣點，也不能替代即時行情。",
    limits: "若官方行情尚未更新或抓取失敗，會顯示資料尚未更新或沿用上一版狀態。"
  },
  {
    title: "AI 選股清單",
    purpose: "用全市場量化欄位排序，首頁只顯示 Top 5，完整排名在 AI 選股清單頁。",
    source: "data/processed/ai_scores_daily.json、stocks_master.json、stock_metrics_daily.json",
    canJudge: "可觀察哪些股票在基本面、技術面、成交熱度與資料覆蓋下排名較前。",
    cannotJudge: "不是推薦買進名單；未進前 100 的股票仍可在個股 AI 分析查詢。",
    limits: "AI 選股清單是獨立量化排序，和多因子評分頁的 30/30/25/15 權重不是同一張表。"
  },
  {
    title: "多因子評分",
    purpose: "拆解每檔股票的基本面、技術面、籌碼/市場交易力道、週轉率/交易熱度。",
    source: "data/processed/factor-scores.json、factor-scores.meta.json、scripts/update_factor_scores.py",
    canJudge: "目前多因子權重為基本面 30%、技術面 30%、籌碼/市場交易力道 25%、週轉率/交易熱度 15%。",
    cannotJudge: "新聞面權重為 0%，不參與多因子分數，也不作為多因子篩選條件。",
    limits: "目前專案未找到 scoring_model.py；多因子公式以 update_factor_scores.py 與 factor-scores.meta.json 為準。"
  },
  {
    title: "重點新聞雷達",
    purpose: "整理市場事件、來源等級、新聞有效分數、AI 判斷與操作意義。",
    source: "data/processed/news_events.json",
    canJudge: "可輔助理解題材催化、個股事件與利多/利空方向。",
    cannotJudge: "新聞不納入多因子評分；新聞熱度高不代表分數一定高。",
    limits: "新聞必須附來源連結；抓不到新新聞時不得只更新時間假裝內容已更新。"
  },
  {
    title: "題材資金輪動",
    purpose: "觀察題材強度、題材漲幅、成交金額、上漲家數、漲停家數與代表股。",
    source: "data/processed/theme_stats.json",
    canJudge: "可看資金集中在哪些題材，以及題材內股票是否擴散。",
    cannotJudge: "題材與概念股只作標籤與分組參考，不直接納入多因子分數。",
    limits: "若題材分類無法辨識，應列為未分類，不應用 04、05、06 等代碼冒充題材。"
  },
  {
    title: "個股 AI 分析",
    purpose: "用股票代號或名稱查詢單一股票的分數拆解、題材、新聞事件與條件說明。",
    source: "stocks_master.json、stock_metrics_daily.json、ai_scores_daily.json、news_events.json",
    canJudge: "可檢查個股目前資料是否完整、是否進入排名、分數與風險標籤為何。",
    cannotJudge: "不能把缺漏資料自動補成 0；停牌或缺資料應顯示 N/A 或 --。",
    limits: "若 EPS、毛利率、週轉率等資料源缺漏，個股頁會保留查詢但標示缺值。"
  },
  {
    title: "追蹤驗證",
    purpose: "追蹤每日 AI 前 30 名後續 5 日、10 日、20 日表現與命中率。",
    source: "data/processed/backtest_results.json",
    canJudge: "可回頭檢查模型排名後的實際報酬、最大漲幅與最大回撤。",
    cannotJudge: "歷史回測不代表未來一定有效，也不是獲利保證。",
    limits: "若歷史行情不足，應標示資料不足，不應推估出完整績效。"
  },
  {
    title: "資料更新狀態",
    purpose: "檢查每個 processed JSON 的更新時間、筆數、狀態與錯誤訊息。",
    source: "data/processed/update_log.json 與各資料檔 metadata",
    canJudge: "可確認哪個資料集已更新、哪個資料集保留上一版或失敗。",
    cannotJudge: "updated_at 新不代表內容一定新，仍要看 content_latest_at 或資料日期。",
    limits: "若資料內容時間舊但未標 stale，應視為資料品質問題並修正更新流程。"
  }
];

function metric(label, value, className = "") {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong class="${className}">${value}</strong></article>`;
}

function renderTransparencyCards() {
  const root = $("#transparencyCards");
  if (!root) return;

  root.innerHTML = TRANSPARENCY_CARDS.map((item) => `
    <article class="transparency-card">
      <h3>${escapeHtml(item.title)}</h3>
      <dl>
        <div>
          <dt>功能用途</dt>
          <dd>${escapeHtml(item.purpose)}</dd>
        </div>
        <div>
          <dt>資料依據</dt>
          <dd>${escapeHtml(item.source)}</dd>
        </div>
        <div>
          <dt>可判斷</dt>
          <dd>${escapeHtml(item.canJudge)}</dd>
        </div>
        <div>
          <dt>不可判斷</dt>
          <dd>${escapeHtml(item.cannotJudge)}</dd>
        </div>
        <div>
          <dt>限制說明</dt>
          <dd>${escapeHtml(item.limits)}</dd>
        </div>
      </dl>
    </article>
  `).join("");
}

function renderMarket(snapshot) {
  const root = $("#marketSnapshot");
  if (!root) return;
  if (!snapshot) {
    root.innerHTML = renderEmpty("市場快照資料尚未建立");
    return;
  }

  $("#dashboardUpdatedAt").textContent = `更新：${formatDateTime(snapshot.updated_at)}`;
  root.innerHTML = [
    metric("加權指數", formatNumber(snapshot.taiex_close, 2), valueClass(snapshot.taiex_change)),
    metric("漲跌", formatNumber(snapshot.taiex_change, 2), valueClass(snapshot.taiex_change)),
    metric("漲跌幅", formatSignedPercent(snapshot.taiex_change_pct), valueClass(snapshot.taiex_change_pct)),
    metric("成交金額", `${formatNumber(snapshot.turnover_billion, 0)} 億`),
    metric("市場溫度", `${formatNumber(snapshot.market_temperature, 0)} / 100`),
    metric("上漲家數", formatNumber(snapshot.up_count), "value-up"),
    metric("下跌家數", formatNumber(snapshot.down_count), "value-down"),
    metric("漲停 / 跌停", `${formatNumber(snapshot.limit_up_count)} / ${formatNumber(snapshot.limit_down_count)}`)
  ].join("");
}

function renderSummary(aiItems, newsItems, themeItems) {
  const root = $("#dashboardSummary");
  if (!root) return;
  const topStock = aiItems[0];
  const topTheme = themeItems[0];
  const highRiskNews = newsItems.filter((item) => item.impact === "偏空").length;
  root.innerHTML = [
    metric("最強題材", topTheme ? escapeHtml(topTheme.theme) : "--"),
    metric("AI 最高分", topStock ? `${stockLink(topStock.symbol, topStock.name)} ${scoreBadge(topStock.total_score)}` : "--"),
    metric("今日重大新聞", `${newsItems.length} 則`),
    metric("利空風險事件", `${highRiskNews} 則`, highRiskNews ? "value-down" : "value-flat")
  ].join("");
}

function renderRadarRows(aiItems) {
  const tbody = $("#dashboardRadarRows");
  if (!tbody) return;
  const topFive = aiItems.slice(0, 5);
  tbody.innerHTML = topFive.length
    ? topFive.map((item, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${stockLink(item.symbol, item.name)}</td>
        <td>${escapeHtml(item.theme)}</td>
        <td>${scoreBadge(item.total_score)}</td>
        <td>${escapeHtml(item.pattern)}</td>
        <td>${riskBadge(item.risk_level)}</td>
        <td>${escapeHtml(item.entry_reason)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="7">${renderEmpty("目前沒有 AI 選股資料")}</td></tr>`;
}

function renderNews(newsItems) {
  const root = $("#dashboardNewsList");
  if (!root) return;
  const topNews = newsItems
    .slice()
    .sort((a, b) => Number(b.news_score) - Number(a.news_score))
    .slice(0, 5);

  root.innerHTML = topNews.length
    ? topNews.map((item) => `
      <article class="news-compact-item">
        <small>${formatDateTime(item.published_at)}</small>
        <div>
          ${item.source_url
            ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>`
            : `<strong>${escapeHtml(item.title)}</strong>`}
          <small>${escapeHtml(item.theme)} · ${escapeHtml(item.source_name)} · 來源等級 ${escapeHtml(item.source_grade)}</small>
        </div>
        <span class="score-badge">${escapeHtml(item.news_score)}</span>
      </article>
    `).join("")
    : renderEmpty("重大新聞資料尚未建立");
}

async function initDashboard() {
  renderTransparencyCards();
}

initDashboard().catch((error) => {
  console.error(error);
});
