from __future__ import annotations

from html import escape
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, REVENUE_PATH, SITE_DIR


BOOLEAN_DISPLAY_COLUMNS = [
    "EPS 是否轉虧為盈",
    "毛利率是否改善",
    "法人是否上修目標價",
    "股價是否仍在低位階",
    "成交量是否溫和放大",
]

DISPLAY_COLUMN_RENAMES = {
    "阿斯拉分數": "強度分數",
    "阿斯拉評級": "觀察評等",
    "關注原因": "入選理由",
    "收盤價": "收盤價",
}

def _to_yes_no(value: object) -> object:
    if pd.isna(value):
        return value
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value).strip()
    if text.lower() == "true":
        return "是"
    if text.lower() == "false":
        return "否"
    return value


def _parse_number(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).replace("%", "").replace(",", "").strip()
    if text in {"", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _build_risk_tags(row: pd.Series) -> str:
    tags: list[str] = []
    yoy = _parse_number(row.get("月營收年增率"))
    mom = _parse_number(row.get("月營收月增率"))
    volume = _parse_number(row.get("當天成交量(張)"))
    score = _parse_number(row.get("強度分數"))
    rating = str(row.get("觀察評等", "")).strip()

    if mom is not None and mom < 0:
        tags.append("月增轉弱")
    if yoy is not None and yoy > 300 and mom is not None and mom < 10:
        tags.append("低基期需確認")
    if volume is not None and volume > 50000:
        tags.append("爆量股")
    if rating == "B" and score is not None and score < 60:
        tags.append("觀察順位較後")
    return "、".join(tags) if tags else "一般觀察"


def _filter_attrs(row: pd.Series) -> str:
    code = _value(row, "股票代號")
    name = _value(row, "股票名稱")
    rating = _value(row, "雷達等級")
    concept = _value(row, "概念股")
    mom = _parse_number(row.get("月營收月增率"))
    yoy = _parse_number(row.get("月營收年增率"))
    score = _parse_number(row.get("雷達強度"))
    volume = _parse_number(row.get("當天成交量(張)"))
    daily_change = _parse_number(row.get("今日漲跌幅"))
    mom_value = "" if mom is None else f"{mom:.4f}"
    yoy_value = "" if yoy is None else f"{yoy:.4f}"
    score_value = "" if score is None else f"{score:.4f}"
    volume_value = "" if volume is None else f"{volume:.4f}"
    daily_change_value = "" if daily_change is None else f"{daily_change:.4f}"
    search = f"{code} {name}".lower()
    return (
        f'data-code="{escape(code)}" '
        f'data-name="{escape(name)}" '
        f'data-search="{escape(search)}" '
        f'data-rating="{escape(rating)}" '
        f'data-concept="{escape(concept.lower())}" '
        f'data-mom="{escape(mom_value)}" '
        f'data-yoy="{escape(yoy_value)}" '
        f'data-score="{escape(score_value)}" '
        f'data-volume="{escape(volume_value)}" '
        f'data-change="{escape(daily_change_value)}"'
    )


def format_report_for_output(report: pd.DataFrame) -> pd.DataFrame:
    """Format display-only values without changing scoring internals."""
    output = report.copy()
    input_aliases = {
        "雷達強度": "強度分數",
        "雷達等級": "觀察評等",
        "追蹤狀態": "觀察節奏",
    }
    for source, target in input_aliases.items():
        if source in output.columns and target not in output.columns:
            output = output.rename(columns={source: target})
    for column in BOOLEAN_DISPLAY_COLUMNS:
        if column in output.columns:
            output[column] = output[column].map(_to_yes_no)
    for column in ["收盤價"]:
        if column in output.columns:
            output[column] = pd.to_numeric(output[column], errors="coerce").round(2)
    output = _enrich_revenue_amount(output)
    if "單月營收_千元" in output.columns:
        output["月營收金額"] = output["單月營收_千元"].map(_format_revenue_amount)
    else:
        output["月營收金額"] = "-"
    for column in ["月營收年增率", "月營收月增率"]:
        if column in output.columns:
            values = output[column].map(_parse_number)
            output[column] = values.map(lambda value: "-" if pd.isna(value) else f"{value:+.2f}%")
    output["去年同月營收"] = output.apply(_previous_year_revenue_amount, axis=1)
    if "阿斯拉分數" in output.columns:
        values = pd.to_numeric(output["阿斯拉分數"], errors="coerce")
        output["阿斯拉分數"] = values.map(lambda value: "-" if pd.isna(value) else f"{value:.1f}")
    if "當天成交量" in output.columns:
        output["當天成交量"] = (
            pd.to_numeric(output["當天成交量"], errors="coerce").div(1000).round(0).astype("Int64")
        )
        output = output.rename(columns={"當天成交量": "當天成交量(張)"})
    if "年月" in output.columns:
        output["月資料"] = output["年月"].map(_month_data_label)
        output["revenue_month"] = output["年月"].map(
            lambda value: "" if pd.isna(value) or str(value).strip() in {"", "-"} else str(value).strip()
        )
    else:
        output["月資料"] = "最新月營收"
        output["revenue_month"] = ""
    if "收盤價" in output.columns and "股價最後日期" in output.columns:
        dates = pd.to_datetime(output["股價最後日期"], errors="coerce")
        market_dates = dates.dt.strftime("%Y-%m-%d")
        output["market_date"] = market_dates.fillna("")
        output["日資料"] = market_dates.map(_day_data_label)
        latest_date = dates.max()
        if pd.notna(latest_date):
            output.attrs["price_date_label"] = latest_date.strftime("%m/%d")
            output.attrs["market_date"] = latest_date.strftime("%Y-%m-%d")
        output = output.drop(columns=["股價最後日期"])
    else:
        if "日資料" in output.columns:
            output["market_date"] = output["日資料"].map(_extract_iso_date)
            parsed_dates = pd.to_datetime(output["market_date"], errors="coerce")
            latest_date = parsed_dates.max()
            if pd.notna(latest_date):
                output.attrs["price_date_label"] = latest_date.strftime("%m/%d")
                output.attrs["market_date"] = latest_date.strftime("%Y-%m-%d")
        else:
            output["日資料"] = "資料日期未標示"
            output["market_date"] = ""
    output["資料版本"] = [
        _data_version_label(revenue_month, market_date)
        for revenue_month, market_date in zip(output["revenue_month"], output["market_date"])
    ]
    revenue_versions = [value for value in output["revenue_month"].astype(str).tolist() if value]
    if revenue_versions or output.attrs.get("market_date"):
        output.attrs["data_version_label"] = _data_version_label(
            max(revenue_versions) if revenue_versions else "最新月營收",
            output.attrs.get("market_date", "資料日期未標示"),
        )
    output = output.rename(columns=DISPLAY_COLUMN_RENAMES)
    if "是否適合慢慢買" in output.columns:
        output = output.drop(columns=["是否適合慢慢買"])
    output["觀察節奏"] = "研究觀察"
    output["風險標籤"] = output.apply(_build_risk_tags, axis=1)
    previous_rank_column = next(
        (column for column in ["前次排名", "昨日排名"] if column in output.columns),
        None,
    )
    if previous_rank_column and "排名" in output.columns:
        output["較前次排名"] = [
            _rank_change_label(current_rank, previous_rank)
            for current_rank, previous_rank in zip(output["排名"], output[previous_rank_column])
        ]
    output = output.rename(
        columns={
            "強度分數": "雷達強度",
            "觀察評等": "雷達等級",
            "觀察節奏": "追蹤狀態",
        }
    )
    return output


def build_index_html(latest_report: str, latest_csv: str, stamp: str) -> str:
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={latest_report}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>阿斯拉台股月營收轉強雷達</title>
  <style>
    body {{ font-family: "Microsoft JhengHei", Arial, sans-serif; margin: 32px; line-height: 1.6; }}
    a {{ color: #0f4c81; }}
  </style>
</head>
<body>
  <h1>阿斯拉台股月營收轉強雷達</h1>
  <p>正在開啟最新盤後報告：{stamp}</p>
  <p><a href="{latest_report}">如果沒有自動開啟，請點這裡查看最新報告</a></p>
  <p><a href="{latest_csv}">下載最新 CSV</a></p>
  <p>本報告僅供研究與風險控管，不構成投資建議。</p>
</body>
</html>
"""


def _value(row: pd.Series, column: str, default: str = "-") -> str:
    if column not in row or pd.isna(row[column]):
        return default
    return str(row[column])


def _format_percent(row: pd.Series, column: str) -> str:
    if column not in row or pd.isna(row[column]):
        return "-"
    if isinstance(row[column], str) and row[column].strip().endswith("%"):
        return row[column]
    value = pd.to_numeric(row[column], errors="coerce")
    if pd.isna(value):
        return str(row[column])
    return f"{value:+.2f}%"


def _format_number(row: pd.Series, column: str, decimals: int = 1) -> str:
    if column not in row or pd.isna(row[column]):
        return "-"
    value = pd.to_numeric(row[column], errors="coerce")
    if pd.isna(value):
        return str(row[column])
    return f"{value:,.{decimals}f}"


def _format_revenue_amount(value: object) -> str:
    amount_thousand = _parse_number(value)
    if amount_thousand is None:
        return "-"
    amount_ntd = amount_thousand * 1000
    if abs(amount_ntd) >= 100_000_000:
        return f"{amount_ntd / 100_000_000:,.2f}億元"
    if abs(amount_ntd) >= 10_000:
        return f"{amount_ntd / 10_000:,.0f}萬元"
    return f"{amount_ntd:,.0f}元"


def _format_revenue_with_percent(row: pd.Series, percent_column: str) -> str:
    amount = _value(row, "月營收金額")
    percent = _format_percent(row, percent_column)
    if amount == "-":
        return percent
    return f"{amount} / {percent}"


def _previous_year_revenue_amount(row: pd.Series) -> str:
    amount_thousand = _parse_number(row.get("單月營收_千元"))
    yoy = _parse_number(row.get("月營收年增率"))
    if amount_thousand is None or yoy is None or yoy <= -100:
        return "-"
    previous_amount_thousand = amount_thousand / (1 + yoy / 100)
    return _format_revenue_amount(previous_amount_thousand)


def _risk_tag_html(tags: str) -> str:
    return "".join(f'<span class="risk-pill">{escape(tag.strip())}</span>' for tag in tags.split("、") if tag.strip())


def _build_radar_data_json(display_report: pd.DataFrame) -> str:
    records: list[dict[str, str]] = []
    for _, row in display_report.iterrows():
        records.append(
            {
                "code": _value(row, "股票代號"),
                "name": _value(row, "股票名稱"),
                "rank": _value(row, "排名"),
                "rating": _value(row, "雷達等級"),
                "score": _value(row, "雷達強度"),
                "price": _value(row, "收盤價"),
                "volume": _value(row, "當天成交量(張)"),
                "revenueYoy": _value(row, "月營收年增率"),
                "revenueMom": _value(row, "月營收月增率"),
                "currentRevenue": _value(row, "月營收金額"),
                "previousYearRevenue": _value(row, "去年同月營收"),
                "concept": _value(row, "概念股"),
                "riskTags": _value(row, "風險標籤"),
            }
        )
    return json.dumps(records, ensure_ascii=False)


def publish_interactive_data(display_report: pd.DataFrame, site_dir: Path = SITE_DIR) -> None:
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    profiles: dict[str, dict[str, str]] = {}
    for _, row in display_report.iterrows():
        code = _value(row, "股票代號")
        record = {
            "rank": int(_parse_number(row.get("排名")) or 0),
            "code": code,
            "name": _value(row, "股票名稱"),
            "concept": _value(row, "概念股"),
            "business": _value(row, "公司業務"),
            "reason": _value(row, "入選理由"),
            "revenue_yoy": _value(row, "月營收年增率"),
            "revenue_yoy_value": _parse_number(row.get("月營收年增率")),
            "revenue_mom": _value(row, "月營收月增率"),
            "revenue_mom_value": _parse_number(row.get("月營收月增率")),
            "rating": _value(row, "雷達等級"),
            "score": _value(row, "雷達強度"),
            "score_value": _parse_number(row.get("雷達強度")),
            "close": _value(row, "收盤價"),
            "volume": _value(row, "當天成交量(張)"),
            "volume_value": _parse_number(row.get("當天成交量(張)")),
            "current_revenue": _value(row, "月營收金額"),
            "previous_year_revenue": _value(row, "去年同月營收"),
            "revenue_month": _value(row, "revenue_month"),
            "market_date": _value(row, "market_date"),
            "data_version": _value(row, "資料版本"),
            "risk_tags": _value(row, "風險標籤"),
            "tracking_status": _value(row, "追蹤狀態"),
            "market": _value(row, "市場"),
            "daily_change": _value(row, "今日漲跌幅"),
        }
        records.append(record)
        profiles[code] = {
            "code": code,
            "name": record["name"],
            "business": record["business"],
            "concept": record["concept"],
            "market": record["market"],
        }
    (data_dir / "stocks-latest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_dir / "stock-profiles.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    technical_path = data_dir / "technical-latest.json"
    if not technical_path.exists():
        technical_path.write_text("{}", encoding="utf-8")


def _month_data_label(value: object) -> str:
    if pd.isna(value) or str(value).strip() in {"", "-"}:
        return "最新月營收"
    return f"{str(value).strip()} 月營收"


def _day_data_label(value: object) -> str:
    if pd.isna(value) or str(value).strip() in {"", "-"}:
        return "資料日期未標示"
    return f"{str(value).strip()} 收盤價/成交量"


def _data_version_label(revenue_month: object, market_date: object) -> str:
    revenue = "最新月營收" if pd.isna(revenue_month) or str(revenue_month).strip() in {"", "-"} else str(revenue_month).strip()
    market = "資料日期未標示" if pd.isna(market_date) or str(market_date).strip() in {"", "-"} else str(market_date).strip()
    return f"營收 {revenue}｜行情 {market}"


def _extract_iso_date(value: object) -> str:
    if pd.isna(value):
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    return match.group(0) if match else ""


def _rank_change_label(current_rank: object, previous_rank: object) -> str:
    current = _parse_number(current_rank)
    previous = _parse_number(previous_rank)
    if current is None:
        return ""
    if previous is None:
        return "新進"
    diff = int(previous - current)
    if diff > 0:
        return f"上升 {diff} 名"
    if diff < 0:
        return f"下降 {abs(diff)} 名"
    return "持平"


def _enrich_revenue_amount(output: pd.DataFrame) -> pd.DataFrame:
    if "單月營收_千元" in output.columns or "股票代號" not in output.columns or not REVENUE_PATH.exists():
        return output
    try:
        revenue = pd.read_csv(REVENUE_PATH, dtype={"股票代號": str})
    except Exception:
        return output
    if "單月營收_千元" not in revenue.columns:
        return output
    keys = ["股票代號"]
    if "年月" in output.columns and "年月" in revenue.columns:
        keys.append("年月")
    lookup = revenue[keys + ["單月營收_千元"]].drop_duplicates(keys, keep="last")
    output = output.merge(lookup, on=keys, how="left")
    return output


def _revenue_month_header_label(display_report: pd.DataFrame) -> str:
    month_value = ""
    for column in ["revenue_month", "年月"]:
        if column in display_report.columns:
            values = [str(value).strip() for value in display_report[column].dropna() if str(value).strip() not in {"", "-"}]
            if values:
                month_value = max(values)
                break
    match = re.search(r"(?:\d{4}-)?0?(\d{1,2})$", month_value)
    if match:
        return f"{int(match.group(1))}月營收"
    return "月營收"


def build_mobile_cards(display_report: pd.DataFrame) -> str:
    cards: list[str] = []
    for _, row in display_report.iterrows():
        rank = _value(row, "排名")
        code = _value(row, "股票代號")
        name = _value(row, "股票名稱")
        rating = _value(row, "雷達等級")
        score = _format_number(row, "雷達強度", decimals=1)
        concept = _value(row, "概念股")
        reason = _value(row, "入選理由")
        business = _value(row, "公司業務")
        risk = _value(row, "風險說明")
        price = _value(row, "收盤價")
        volume = _value(row, "當天成交量(張)")
        current_revenue = _value(row, "月營收金額")
        yoy = _format_percent(row, "月營收年增率")
        mom = _format_percent(row, "月營收月增率")
        previous_year_revenue = _value(row, "去年同月營收")
        tracking_status = _value(row, "追蹤狀態")
        risk_tags = _value(row, "風險標籤")
        attrs = _filter_attrs(row)
        cards.append(
            f"""
    <article class="stock-card radar-item" {attrs}>
      <div class="card-top">
        <div>
          <div class="rank">#{escape(rank)}</div>
          <h2>{escape(code)} {escape(name)}</h2>
        </div>
        <div class="badge">{escape(rating)}</div>
      </div>
      <div class="metrics">
        <div><span>雷達強度</span><strong class="score-value">{escape(score)}</strong></div>
        <div><span>收盤價</span><strong>{escape(price)}</strong></div>
        <div><span>成交量</span><strong>{escape(volume)} 張</strong></div>
      </div>
      <div class="metrics">
        <div><span>當月營收</span><strong>{escape(current_revenue)}</strong></div>
        <div><span>月增率%</span><strong>{escape(mom)}</strong></div>
        <div><span>去年同月營收</span><strong>{escape(previous_year_revenue)}</strong></div>
        <div><span>年增率%</span><strong>{escape(yoy)}</strong></div>
      </div>
      <p class="mode-label">雷達模式標籤：<strong class="mode-tag">主升段</strong></p>
      <p class="mode-penalty-note" hidden>主升段模式降權：族群非當前高動能主流，需等待政策、利率或量價確認。</p>
      <p class="status-line"><strong>追蹤狀態：</strong>{escape(tracking_status)}</p>
      <p class="risk-label">風險標籤：</p>
      <div class="risk-tags">{_risk_tag_html(risk_tags)}</div>
      <p class="concept"><span>概念股：</span>{escape(concept)}</p>
      <p><strong>入選理由：</strong>{escape(reason)}</p>
      <details>
        <summary>公司業務與風險</summary>
        <p>{escape(business)}</p>
        <p><strong>風險：</strong>{escape(risk)}</p>
      </details>
    </article>
"""
        )
    return "\n".join(cards)


def build_desktop_summary_table(display_report: pd.DataFrame) -> str:
    previous_rank_column = next(
        (column for column in ["較前次排名", "前次排名", "昨日排名"] if column in display_report.columns),
        None,
    )
    columns = [
        "排名",
        "股票代號",
        "股票名稱",
        "概念股",
        "雷達強度",
        "雷達等級",
        "收盤價",
        "當天成交量(張)",
        "月營收金額",
        "月營收月增率",
        "去年同月營收",
        "月營收年增率",
        "風險標籤",
        "追蹤狀態",
        "入選理由",
    ]
    if previous_rank_column:
        columns.insert(1, previous_rank_column)
    available = [column for column in columns if column in display_report.columns]
    summary = display_report[available].copy()
    price_date = display_report.attrs.get("price_date_label")
    price_header = f"收盤價<br>{price_date}" if price_date else "收盤價"
    header_labels = {
        "股票代號": "股票<br>代號",
        "股票名稱": "股票<br>名稱",
        "雷達強度": "雷達<br>強度",
        "雷達等級": "雷達<br>等級",
        "收盤價": price_header,
        "當天成交量(張)": "當天成交量<br>(張)",
        "月營收金額": "當月<br>營收",
        "月營收月增率": "月增率<br>%",
        "去年同月營收": "去年同月<br>營收",
        "月營收年增率": "年增率<br>%",
        "風險標籤": "風險<br>標籤",
        "追蹤狀態": "追蹤<br>狀態",
        "前次排名": "較前次<br>排名",
        "昨日排名": "較前次<br>排名",
    }
    headers = "".join(f"<th>{header_labels.get(column, escape(column))}</th>" for column in available)
    rows: list[str] = []
    for _, row in summary.iterrows():
        attrs = _filter_attrs(row)
        cells: list[str] = []
        for column in available:
            value = _value(row, column)
            if column == "風險標籤":
                cells.append(f"<td>{_risk_tag_html(value)}</td>")
            elif column == "雷達強度":
                cells.append(f'<td class="score-cell"><span class="score-value">{escape(value)}</span><span class="score-penalty-chip" hidden>降權</span></td>')
            else:
                cells.append(f"<td>{escape(value)}</td>")
        rows.append(f'<tr class="radar-item" {attrs}>{"".join(cells)}</tr>')
    return f"""<table class="summary-table">
  <thead>
    <tr>{headers}</tr>
  </thead>
  <tbody>
    {"".join(rows)}
  </tbody>
</table>"""


def build_overview_section(display_report: pd.DataFrame) -> str:
    total = len(display_report)
    rating = display_report["雷達等級"].astype(str) if "雷達等級" in display_report.columns else pd.Series(dtype=str)
    a_count = int((rating == "A").sum())
    a_minus_count = int((rating == "A-").sum())
    b_count = int((rating == "B").sum())
    concepts: list[str] = []
    if "概念股" in display_report.columns:
        for value in display_report["概念股"].dropna():
            concepts.extend([item.strip() for item in str(value).split(";") if item.strip()])
    top_concepts = pd.Series(concepts).value_counts().head(5).index.tolist() if concepts else []
    concept_text = "、".join(top_concepts) if top_concepts else "暫無明顯集中題材"
    cards = [
        ("今日入選檔數", f"{total} 檔"),
        ("A級以上檔數", f"{a_count} 檔"),
        ("A-級檔數", f"{a_minus_count} 檔"),
        ("B級檔數", f"{b_count} 檔"),
    ]
    stats = "".join(
        f'<div class="overview-card"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in cards
    )
    return f"""
    <section class="panel overview-panel">
      <div class="section-title">
        <h2>今日雷達總覽</h2>
        <span>依目前前 30 名報告統計</span>
      </div>
      <div class="overview-grid">{stats}</div>
      <div class="theme-strip"><span>今日主要強勢題材</span><strong>{escape(concept_text)}</strong></div>
    </section>
"""


def build_news_events_section() -> str:
    return """
    <section class="panel news-events-panel">
      <div class="section-title">
        <h2>今日重大事件雷達</h2>
        <span>讀取 news-events.json，自動比對雷達與我的持股</span>
      </div>
      <p class="panel-note">僅顯示事件摘要、連動邏輯與原文連結，不收錄新聞全文。</p>
      <div id="newsEventsList" class="news-events-list">
        <div class="empty-events">事件資料載入中...</div>
      </div>
    </section>
"""


def build_radar_mode_section() -> str:
    return """
    <section class="panel radar-mode-panel">
      <div class="section-title">
        <h2>雷達模式</h2>
        <span>切換觀察角度，不刪除原始股票資料</span>
      </div>
      <div class="mode-toggle" role="radiogroup" aria-label="雷達模式">
        <label><input type="radio" name="radarMode" value="main" checked> 主升段模式</label>
        <label><input type="radio" name="radarMode" value="market"> 全市場模式</label>
        <label><input type="radio" name="radarMode" value="defensive"> 資產防守模式</label>
      </div>
      <p id="radarModeNote" class="mode-note">主升段模式：優先觀察 AI、半導體、記憶體、PCB、CPO、光通訊、散熱、電源、低軌衛星、玻璃基板、被動元件、機器人、重電、軍工；防守族群不刪除，但未放量或未命中事件時會降權顯示。</p>
    </section>
"""


def build_filter_section() -> str:
    return """
    <section class="panel filter-panel">
      <div class="section-title">
        <h2>搜尋與篩選</h2>
        <span id="filter-count">顯示全部</span>
      </div>
      <div class="filter-grid">
        <label>股票搜尋
          <input id="searchInput" type="search" placeholder="輸入代號或名稱，例如 2337、旺宏">
        </label>
        <label>雷達等級
          <select id="ratingFilter">
            <option value="">全部</option>
            <option value="A">A</option>
            <option value="A-">A-</option>
            <option value="B">B</option>
          </select>
        </label>
        <label>概念股關鍵字
          <input id="conceptInput" type="search" placeholder="例如 PCB、AI伺服器、記憶體">
        </label>
        <label class="check-row">
          <input id="positiveMomOnly" type="checkbox">
          <span>只看營收月增為正</span>
        </label>
      </div>
    </section>
"""


def build_data_basis_section() -> str:
    items = [
        ("月營收年增率", "每月更新"),
        ("月營收月增率", "每月更新"),
        ("收盤價", "交易日更新"),
        ("成交量", "交易日更新"),
        ("雷達強度", "依最新資料重新排序"),
        ("風險標籤", "依營收、量能與雷達強度條件產生"),
    ]
    rows = "".join(
        f'<div class="basis-item"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in items
    )
    return f"""
    <section class="panel basis-panel">
      <div class="section-title">
        <h2>資料依據與更新頻率</h2>
        <span>說明各欄位更新節奏</span>
      </div>
      <div class="basis-grid">{rows}</div>
    </section>
"""


def build_score_explanation_section() -> str:
    weights = [
        ("營收動能", "40%"),
        ("量能活躍", "20%"),
        ("題材關聯", "15%"),
        ("股價位置", "15%"),
        ("風險扣分", "10%"),
    ]
    rows = "".join(
        f'<div class="score-weight"><span>{escape(label)}</span><strong>{escape(weight)}</strong></div>'
        for label, weight in weights
    )
    return f"""
    <section class="panel score-explanation-panel">
      <div class="section-title">
        <h2>雷達強度說明</h2>
        <span>僅供研究排序，不構成投資建議</span>
      </div>
      <p class="panel-note">雷達強度為 0–100 分，僅作為候選股觀察排序使用。目前不顯示每檔股票的細項拆分，避免把研究排序誤解為精準投資建議。</p>
      <div class="score-weight-grid">{rows}</div>
    </section>
"""


def build_v3_placeholder_section(display_report: pd.DataFrame) -> str:
    columns = [
        "昨日排名",
        "排名變化",
        "分數變化",
        "連續入選天數",
        "5日漲跌幅",
        "20日漲跌幅",
        "股價距20日線",
        "股價距60日線",
        "成交量倍率",
    ]
    headers = "".join(f"<th>{escape(column)}</th>" for column in ["股票代號", "股票名稱", *columns])
    rows: list[str] = []
    for _, row in display_report.iterrows():
        code = _value(row, "股票代號")
        name = _value(row, "股票名稱")
        placeholders = "".join("<td>N/A</td>" for _ in columns)
        rows.append(f"<tr><td>{escape(code)}</td><td>{escape(name)}</td>{placeholders}</tr>")
    return f"""
    <section class="panel v3-panel">
      <div class="section-title">
        <h2>V3 預留：排名變化與技術面確認</h2>
        <span>待歷史資料建立後啟用</span>
      </div>
      <p class="panel-note">目前尚未建立可驗證的歷史排名資料與完整歷史股價資料，因此以下欄位先顯示 N/A，不自行編造數字。</p>
      <div class="v3-table-wrap">
        <table class="v3-table">
          <thead><tr>{headers}</tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </section>
"""


def build_holdings_section(display_report: pd.DataFrame) -> str:
    return """
    <section class="panel holdings-panel">
      <div class="section-title">
        <h2>我的持股設定</h2>
        <span>資料儲存在此瀏覽器 localStorage</span>
      </div>
      <p class="panel-note">輸入股票代號，可用逗號分隔或每行一檔。範例：2337,2313,3673</p>
      <textarea id="holdingsInput" class="holdings-input" rows="4" placeholder="2337,2313,3673"></textarea>
      <div class="holding-actions">
        <button type="button" id="saveHoldings">儲存持股</button>
        <button type="button" id="clearHoldings">清除持股</button>
        <button type="button" id="exportHoldings">匯出設定</button>
        <button type="button" id="importHoldings">匯入設定</button>
        <input id="importHoldingsFile" type="file" accept="application/json,.json" hidden>
      </div>
      <div class="section-title holdings-result-title">
        <h2>我的持股命中</h2>
        <span id="holdingsSummary">尚未設定持股</span>
      </div>
      <div id="holdingsResults" class="holdings-grid holdings-results"></div>
    </section>
"""


def publish_static_site(csv_path: Path, html_path: Path, stamp: str, site_dir: Path = SITE_DIR) -> None:
    reports_dir = site_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    site_html = reports_dir / html_path.name
    site_csv = reports_dir / csv_path.name
    latest_html = site_dir / "latest.html"
    latest_csv = site_dir / "latest.csv"
    app_site_exists = (site_dir / "app.js").exists()

    shutil.copy2(html_path, site_html)
    shutil.copy2(csv_path, site_csv)
    if not app_site_exists:
        shutil.copy2(html_path, latest_html)
    shutil.copy2(csv_path, latest_csv)

    index_path = site_dir / "index.html"
    existing_index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    if "boot(\"index\")" not in existing_index:
        index_html = build_index_html("latest.html", "latest.csv", stamp)
        index_path.write_text(index_html, encoding="utf-8")


def write_reports(
    report: pd.DataFrame,
    output_dir: Path = OUTPUT_DIR,
    interactive_report: pd.DataFrame | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    csv_path = output_dir / f"asurada_candidates_{stamp}.csv"
    html_path = output_dir / f"asurada_candidates_{stamp}.html"
    display_report = format_report_for_output(report)
    interactive_display_report = (
        format_report_for_output(interactive_report)
        if interactive_report is not None
        else display_report
    )
    display_report.to_csv(csv_path, index=False, encoding="utf-8-sig")
    publish_interactive_data(interactive_display_report)

    desktop_table = build_desktop_summary_table(display_report)
    mobile_cards = build_mobile_cards(display_report)
    overview_section = build_overview_section(display_report)
    news_events_section = build_news_events_section()
    radar_mode_section = build_radar_mode_section()
    data_basis_section = build_data_basis_section()
    score_explanation_section = build_score_explanation_section()
    v3_placeholder_section = build_v3_placeholder_section(display_report)
    filter_section = build_filter_section()
    holdings_section = build_holdings_section(display_report)
    radar_data_json = _build_radar_data_json(display_report).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>阿斯拉台股月營收轉強雷達</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3f6fb;
      --card: #ffffff;
      --ink: #152238;
      --muted: #64748b;
      --line: #dbe3ef;
      --accent: #0f4c81;
      --good: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft JhengHei", Arial, sans-serif;
      margin: 0;
      line-height: 1.55;
    }}
    .page {{ padding: 24px; }}
    .hero {{
      background: linear-gradient(135deg, #152238, #0f4c81);
      color: white;
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: 0 12px 30px rgba(15, 35, 70, 0.18);
    }}
    h1 {{ margin: 0 0 8px; font-size: clamp(24px, 5vw, 36px); }}
    .note {{ color: #dbeafe; margin: 0; }}
    .disclaimer {{ margin-top: 10px; }}
    .score-note {{
      color: #e0f2fe;
      font-size: 13px;
      margin: 10px 0 0;
    }}
    .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 24px rgba(15, 35, 70, 0.08);
      margin-bottom: 16px;
      padding: 16px;
    }}
    .section-title {{
      align-items: baseline;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .section-title h2 {{
      color: var(--ink);
      font-size: 20px;
      margin: 0;
    }}
    .section-title span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .overview-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }}
    .overview-card {{
      background: #f8fafc;
      border-radius: 14px;
      padding: 14px;
    }}
    .overview-card span,
    .theme-strip span {{
      color: var(--muted);
      display: block;
      font-size: 13px;
    }}
    .overview-card strong {{
      color: var(--accent);
      display: block;
      font-size: 24px;
      margin-top: 4px;
    }}
    .theme-strip {{
      background: linear-gradient(135deg, #e0f2fe, #f8fafc);
      border-radius: 14px;
      margin-top: 10px;
      padding: 14px;
    }}
    .theme-strip strong {{
      color: var(--ink);
      display: block;
      font-size: 16px;
      margin-top: 4px;
    }}
    .news-events-list {{
      display: grid;
      gap: 12px;
    }}
    .event-card {{
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
    }}
    .event-card h3 {{
      color: var(--ink);
      font-size: 18px;
      margin: 8px 0;
    }}
    .event-meta,
    .event-chip-row,
    .event-hit-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }}
    .event-chip,
    .stock-chip {{
      background: white;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      display: inline-flex;
      font-size: 13px;
      font-weight: 800;
      padding: 5px 9px;
    }}
    .event-chip.positive {{ background: #ecfdf5; border-color: #bbf7d0; color: #166534; }}
    .event-chip.negative {{ background: #fef2f2; border-color: #fecaca; color: #991b1b; }}
    .event-chip.neutral {{ background: #f8fafc; border-color: var(--line); color: var(--muted); }}
    .event-chip.strong {{ background: #fff7ed; border-color: #fed7aa; color: #9a3412; }}
    .event-logic {{
      color: var(--ink);
      line-height: 1.65;
      margin: 10px 0;
    }}
    .event-label {{
      color: var(--muted);
      display: block;
      font-size: 13px;
      font-weight: 800;
      margin-top: 10px;
    }}
    .event-source {{
      background: #152238;
      border-radius: 999px;
      color: white;
      display: inline-block;
      font-size: 13px;
      font-weight: 800;
      margin-top: 12px;
      padding: 7px 12px;
      text-decoration: none;
    }}
    .empty-events {{
      background: #f8fafc;
      border: 1px dashed var(--line);
      border-radius: 14px;
      color: var(--muted);
      font-weight: 800;
      padding: 14px;
    }}
    .mode-toggle {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .mode-toggle label {{
      align-items: center;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      cursor: pointer;
      display: inline-flex;
      font-weight: 800;
      gap: 6px;
      padding: 8px 12px;
    }}
    .mode-toggle label:has(input:checked) {{
      background: #152238;
      border-color: #152238;
      color: white;
    }}
    .mode-toggle input {{
      accent-color: var(--accent);
    }}
    .mode-note {{
      color: var(--muted);
      line-height: 1.65;
      margin: 12px 0 0;
    }}
    .basis-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }}
    .basis-item {{
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
    }}
    .basis-item span {{
      color: var(--muted);
      display: block;
      font-size: 13px;
      font-weight: 700;
    }}
    .basis-item strong {{
      color: var(--accent);
      display: block;
      font-size: 15px;
      margin-top: 4px;
    }}
    .panel-note {{
      color: var(--muted);
      margin: 0 0 12px;
    }}
    .score-weight-grid {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 10px;
    }}
    .score-weight {{
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      text-align: center;
    }}
    .score-weight span {{
      color: var(--muted);
      display: block;
      font-size: 13px;
      font-weight: 700;
    }}
    .score-weight strong {{
      color: var(--accent);
      display: block;
      font-size: 22px;
      margin-top: 4px;
    }}
    .v3-table-wrap {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    .v3-table {{
      border-collapse: collapse;
      min-width: 980px;
      width: 100%;
      font-size: 13px;
    }}
    .v3-table th,
    .v3-table td {{
      border: 1px solid var(--line);
      padding: 8px;
      text-align: center;
      white-space: nowrap;
    }}
    .v3-table th {{
      background: #152238;
      color: white;
      font-weight: 800;
    }}
    .v3-table td {{
      background: #ffffff;
      color: var(--muted);
      font-weight: 700;
    }}
    .v3-table td:nth-child(1),
    .v3-table td:nth-child(2) {{
      color: var(--ink);
      font-weight: 800;
    }}
    .filter-grid {{
      display: grid;
      grid-template-columns: 1.2fr .7fr 1fr .8fr;
      gap: 10px;
      align-items: end;
    }}
    .filter-grid label {{
      color: var(--muted);
      display: block;
      font-size: 13px;
      font-weight: 700;
    }}
    .filter-grid input,
    .filter-grid select {{
      border: 1px solid var(--line);
      border-radius: 12px;
      color: var(--ink);
      font-family: inherit;
      font-size: 15px;
      margin-top: 6px;
      padding: 10px 12px;
      width: 100%;
    }}
    .check-row {{
      align-items: center;
      background: #f8fafc;
      border-radius: 12px;
      display: flex !important;
      gap: 8px;
      padding: 10px 12px;
    }}
    .check-row input {{
      margin: 0;
      width: auto;
    }}
    .holdings-grid {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 10px;
    }}
    .holdings-input {{
      border: 1px solid var(--line);
      border-radius: 14px;
      color: var(--ink);
      font-family: inherit;
      font-size: 15px;
      min-height: 96px;
      padding: 12px;
      resize: vertical;
      width: 100%;
    }}
    .holding-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0 14px;
    }}
    .holding-actions button {{
      background: #152238;
      border: 1px solid #152238;
      border-radius: 999px;
      color: white;
      cursor: pointer;
      font-family: inherit;
      font-weight: 800;
      padding: 8px 12px;
    }}
    .holding-actions button:nth-child(2) {{
      background: #f8fafc;
      color: var(--ink);
      border-color: var(--line);
    }}
    .holdings-result-title {{
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 12px;
    }}
    .holding-card {{
      border-radius: 14px;
      padding: 12px;
    }}
    .holding-card strong,
    .holding-card span {{
      display: block;
    }}
    .holding-card span {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }}
    .holding-card.hit {{
      background: #e0f2fe;
      border: 1px solid #bae6fd;
    }}
    .holding-card.muted-hit {{
      background: #f8fafc;
      border: 1px solid var(--line);
    }}
    .holding-card .holding-detail {{
      color: var(--ink);
      font-size: 13px;
      margin-top: 6px;
    }}
    .holding-card .holding-concept {{
      color: var(--good);
      font-weight: 800;
    }}
    .risk-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }}
    .status-line,
    .risk-label,
    .mode-label {{
      color: var(--muted);
      font-size: 13px;
      margin: 10px 0 0;
    }}
    .status-line strong,
    .risk-label,
    .mode-label strong {{
      color: var(--ink);
      font-weight: 800;
    }}
    .mode-penalty-note {{
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 12px;
      color: #9a3412;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.5;
      margin: 8px 0 0;
      padding: 8px 10px;
    }}
    .risk-pill {{
      background: #eef2ff;
      border: 1px solid #c7d2fe;
      border-radius: 999px;
      color: #3730a3;
      display: inline-block;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.2;
      padding: 4px 8px;
      white-space: nowrap;
    }}
    .date-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }}
    .date-tags span {{
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      padding: 4px 8px;
    }}
    .no-results {{
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 14px;
      color: #9a3412;
      display: none;
      font-weight: 800;
      margin-bottom: 14px;
      padding: 14px;
      text-align: center;
    }}
    .desktop-table {{
      background: var(--card);
      border-radius: 14px;
      overflow: visible;
      box-shadow: 0 8px 24px rgba(15, 35, 70, 0.08);
    }}
    table.summary-table {{
      border-collapse: collapse;
      table-layout: fixed;
      width: 100%;
      font-size: 13px;
    }}
    .summary-table th, .summary-table td {{
      border: 1px solid #ddd;
      padding: 8px;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    .summary-table th {{
      background: #152238;
      color: white;
      font-size: 13px;
      letter-spacing: .03em;
      line-height: 1.25;
      position: sticky;
      text-align: center;
      top: 0;
      vertical-align: middle;
      white-space: nowrap;
      z-index: 5;
      box-shadow: 0 2px 0 rgba(15, 35, 70, 0.18);
    }}
    .summary-table th:nth-child(1), .summary-table td:nth-child(1) {{ width: 3%; text-align: center; }}
    .summary-table th:nth-child(2), .summary-table td:nth-child(2) {{ width: 5%; text-align: center; }}
    .summary-table th:nth-child(3), .summary-table td:nth-child(3) {{ width: 6%; text-align: center; }}
    .summary-table th:nth-child(4), .summary-table td:nth-child(4) {{ width: 10%; }}
    .summary-table th:nth-child(5), .summary-table td:nth-child(5) {{ width: 5%; text-align: right; }}
    .summary-table th:nth-child(6), .summary-table td:nth-child(6) {{ width: 5%; text-align: center; }}
    .summary-table th:nth-child(7), .summary-table td:nth-child(7) {{ width: 6%; text-align: right; }}
    .summary-table th:nth-child(8), .summary-table td:nth-child(8) {{ width: 7%; text-align: right; }}
    .summary-table th:nth-child(9), .summary-table td:nth-child(9) {{ width: 8%; text-align: right; }}
    .summary-table th:nth-child(10), .summary-table td:nth-child(10) {{ width: 6%; text-align: right; }}
    .summary-table th:nth-child(11), .summary-table td:nth-child(11) {{ width: 8%; text-align: right; }}
    .summary-table th:nth-child(12), .summary-table td:nth-child(12) {{ width: 6%; text-align: right; }}
    .summary-table th:nth-child(13), .summary-table td:nth-child(13) {{ width: 8%; text-align: center; }}
    .summary-table th:nth-child(14), .summary-table td:nth-child(14) {{ width: 6%; text-align: center; }}
    .summary-table th:nth-child(15), .summary-table td:nth-child(15) {{ width: 11%; }}
    .summary-table td:nth-child(4),
    .summary-table td:nth-child(15) {{
      line-height: 1.45;
    }}
    .score-cell .score-value {{
      display: block;
    }}
    .score-penalty-chip {{
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 999px;
      color: #9a3412;
      display: inline-block;
      font-size: 11px;
      font-weight: 800;
      margin-top: 3px;
      padding: 2px 6px;
    }}
    tr:nth-child(even) {{ background: #f8fafc; }}
    .mobile-cards {{ display: none; }}
    .stock-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      margin-bottom: 14px;
      box-shadow: 0 8px 22px rgba(15, 35, 70, 0.08);
    }}
    .card-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }}
    .rank {{ color: var(--muted); font-size: 13px; font-weight: 700; }}
    .stock-card h2 {{ margin: 2px 0 0; font-size: 21px; }}
    .badge {{
      background: #e0f2fe;
      color: #075985;
      border-radius: 999px;
      padding: 6px 10px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 12px;
    }}
    .metrics div {{
      background: #f8fafc;
      border-radius: 12px;
      padding: 10px;
      min-width: 0;
    }}
    .metrics span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metrics strong {{ display: block; color: var(--ink); font-size: 16px; margin-top: 2px; overflow-wrap: anywhere; }}
    .concept {{
      color: var(--good);
      font-weight: 800;
      margin: 14px 0 8px;
    }}
    .concept span {{ color: var(--muted); font-weight: 700; }}
    details {{
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 10px;
    }}
    summary {{ color: var(--accent); font-weight: 800; cursor: pointer; }}
    .date {{ color: var(--muted); font-size: 13px; }}
    .actions {{ margin-top: 12px; }}
    .actions a,
    .actions button {{
      background: transparent;
      color: white;
      display: inline-block;
      border: 1px solid rgba(255,255,255,.45);
      border-radius: 999px;
      cursor: pointer;
      font-family: inherit;
      font-size: 14px;
      padding: 6px 12px;
      text-decoration: none;
      margin-right: 8px;
    }}
    @media (max-width: 768px) {{
      .page {{ padding: 12px; }}
      .hero {{ border-radius: 0 0 18px 18px; margin: -12px -12px 14px; padding: 18px 14px; }}
      .panel {{ border-radius: 14px; padding: 14px; }}
      .section-title {{ align-items: flex-start; flex-direction: column; gap: 2px; }}
      .overview-grid,
      .basis-grid,
      .score-weight-grid,
      .filter-grid,
      .holdings-grid {{ grid-template-columns: 1fr; }}
      .desktop-table {{ display: none; }}
      .mobile-cards {{ display: block; }}
      .metrics {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .metrics strong {{ font-size: 15px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>阿斯拉台股月營收轉強雷達</h1>
      <p class="note">本雷達以最新月營收年增率、月增率作為基本面初篩，再結合當日收盤價、成交量、題材分類與風險標籤進行排序。月營收通常不會每日變動，股價與成交量則依交易日更新，因此每日排名可能小幅變動，月營收公告期則可能大幅變動。</p>
      <p class="note disclaimer">本報告僅供研究與風險控管，不構成投資建議，也不包含自動下單功能。</p>
      <p class="score-note">雷達強度為 0-100 分，用來排序候選股強弱；雷達等級依分數分級，方便快速判斷觀察優先順序。</p>
      <div class="actions">
        <a href="latest.csv">下載 CSV</a>
        <button type="button" onclick="alert('本雷達依據營收成長、成交量、股價位置、題材概念與技術強度進行初步篩選，僅供研究與風險控管參考，不構成投資建議。')">資料說明</button>
      </div>
    </section>
{data_basis_section}
{score_explanation_section}
{v3_placeholder_section}
{overview_section}
{news_events_section}
{radar_mode_section}
{holdings_section}
{filter_section}
    <div id="noResults" class="no-results">目前篩選條件下沒有符合的股票</div>
    <section class="mobile-cards">
      {mobile_cards}
    </section>
    <section class="desktop-table">
      {desktop_table}
    </section>
  </main>
  <script>
    const radarData = {radar_data_json};
    const holdingsStorageKey = 'asurada_holdings';
    const searchInput = document.getElementById('searchInput');
    const ratingFilter = document.getElementById('ratingFilter');
    const conceptInput = document.getElementById('conceptInput');
    const positiveMomOnly = document.getElementById('positiveMomOnly');
    const filterCount = document.getElementById('filter-count');
    const noResults = document.getElementById('noResults');
    const holdingsInput = document.getElementById('holdingsInput');
    const holdingsResults = document.getElementById('holdingsResults');
    const holdingsSummary = document.getElementById('holdingsSummary');
    const saveHoldings = document.getElementById('saveHoldings');
    const clearHoldings = document.getElementById('clearHoldings');
    const exportHoldings = document.getElementById('exportHoldings');
    const importHoldings = document.getElementById('importHoldings');
    const importHoldingsFile = document.getElementById('importHoldingsFile');
    const newsEventsList = document.getElementById('newsEventsList');
    const newsEventsUrl = window.location.pathname.includes('/reports/') ? '../news-events.json' : 'news-events.json';
    const modeInputs = Array.from(document.querySelectorAll('input[name="radarMode"]'));
    const radarModeNote = document.getElementById('radarModeNote');
    let latestNewsEvents = [];
    let majorEventCodes = new Set();

    const radarByCode = new Map(radarData.map((stock) => [stock.code, stock]));
    const mainThemeKeywords = ['AI', '半導體', '記憶體', 'PCB', 'CPO', '光通訊', '散熱', '電源', '低軌衛星', '玻璃基板', '被動元件', '機器人', '重電', '軍工'];
    const constructionKeywords = ['營建', '資產', '都更'];
    const financeKeywords = ['金融', '壽險', '銀行'];
    const modeLabels = {{
      main: '主升段',
      market: '全市場',
      defensive: '資產防守',
    }};
    const modeNotes = {{
      main: '主升段模式：優先觀察 AI、半導體、記憶體、PCB、CPO、光通訊、散熱、電源、低軌衛星、玻璃基板、被動元件、機器人、重電、軍工；防守族群不刪除，但未放量或未命中事件時會降權顯示。',
      market: '全市場模式：不降權，所有股票照原始雷達強度排序。',
      defensive: '資產防守模式：只顯示營建、資產、都更、金融、壽險、銀行相關股票，並依雷達強度、成交量、營收年增、營收月增排序。',
    }};

    function escapeHtml(value) {{
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }}

    function normalizeHoldingCode(value) {{
      return String(value || '')
        .trim()
        .toUpperCase()
        .replace(/\\.(TW|TWO)$/i, '');
    }}

    function parseHoldings(text) {{
      const seen = new Set();
      return String(text || '')
        .split(/[\\s,\\uFF0C\\u3001]+/)
        .map(normalizeHoldingCode)
        .filter((code) => {{
          if (!code || seen.has(code)) return false;
          seen.add(code);
          return true;
        }});
    }}

    function getStoredHoldings() {{
      const raw = localStorage.getItem(holdingsStorageKey);
      if (!raw) return [];
      try {{
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed.map(normalizeHoldingCode).filter(Boolean);
        if (Array.isArray(parsed.codes)) return parsed.codes.map(normalizeHoldingCode).filter(Boolean);
      }} catch (error) {{
        return parseHoldings(raw);
      }}
      return [];
    }}

    function setStoredHoldings(codes) {{
      localStorage.setItem(holdingsStorageKey, JSON.stringify({{ codes }}));
    }}

    function riskTagHtml(tags) {{
      const parts = String(tags || '一般觀察').split('、').map((tag) => tag.trim()).filter(Boolean);
      return parts.map((tag) => `<span class="risk-pill">${{escapeHtml(tag)}}</span>`).join('');
    }}

    function eventChipClass(value) {{
      if (value === '偏多') return 'positive';
      if (value === '偏空') return 'negative';
      return 'neutral';
    }}

    function eventStrengthClass(value) {{
      return value === '高' ? 'strong' : 'neutral';
    }}

    function stockLabel(code) {{
      const normalized = normalizeHoldingCode(code);
      const stock = radarByCode.get(normalized);
      return stock ? `${{normalized}} ${{stock.name}}` : normalized;
    }}

    function stockChips(codes, emptyText = '無') {{
      const normalizedCodes = (codes || []).map(normalizeHoldingCode).filter(Boolean);
      if (!normalizedCodes.length) return `<span class="stock-chip">${{escapeHtml(emptyText)}}</span>`;
      return normalizedCodes.map((code) => `<span class="stock-chip">${{escapeHtml(stockLabel(code))}}</span>`).join('');
    }}

    function renderNewsEvents(events) {{
      if (!newsEventsList) return;
      if (!Array.isArray(events) || !events.length) {{
        newsEventsList.innerHTML = '<div class="empty-events">今日尚無重大事件資料</div>';
        return;
      }}

      const holdingSet = new Set(getStoredHoldings());
      newsEventsList.innerHTML = events.map((event) => {{
        const relatedStocks = (event.related_stocks || []).map(normalizeHoldingCode).filter(Boolean);
        const radarHits = relatedStocks.filter((code) => radarByCode.has(code));
        const holdingHits = relatedStocks.filter((code) => holdingSet.has(code));
        const sourceUrl = String(event.url || '').trim();
        const sourceName = String(event.source_name || '查看來源').trim();
        const sourceButton = sourceUrl
          ? `<a class="event-source" href="${{escapeHtml(sourceUrl)}}" target="_blank" rel="noopener noreferrer">查看來源</a>`
          : '';

        return `
          <article class="event-card">
            <div class="event-meta">
              <span class="event-chip">${{escapeHtml(event.date || '日期未標示')}}</span>
              <span class="event-chip">${{escapeHtml(event.region || '地區未標示')}}</span>
              <span class="event-chip ${{eventChipClass(event.impact)}}">影響方向：${{escapeHtml(event.impact || '中性')}}</span>
              <span class="event-chip ${{eventStrengthClass(event.event_strength)}}">事件強度：${{escapeHtml(event.event_strength || '未標示')}}</span>
            </div>
            <h3>${{escapeHtml(event.title || '未命名事件')}}</h3>
            <div class="event-chip-row">
              <span class="event-chip">題材分類：${{escapeHtml(event.category || '未分類')}}</span>
              <span class="event-chip">來源：${{escapeHtml(sourceName)}}</span>
            </div>
            <p class="event-logic">${{escapeHtml(event.logic || '尚無連動邏輯說明')}}</p>
            <span class="event-label">相關台股</span>
            <div class="event-hit-row">${{stockChips(relatedStocks, '無相關台股')}}</div>
            <span class="event-label">雷達命中股票</span>
            <div class="event-hit-row">${{stockChips(radarHits, '未命中今日雷達')}}</div>
            <span class="event-label">我的持股命中股票</span>
            <div class="event-hit-row">${{stockChips(holdingHits, '未命中我的持股')}}</div>
            ${{sourceButton}}
          </article>
        `;
      }}).join('');
    }}

    async function loadNewsEvents() {{
      try {{
        const response = await fetch(newsEventsUrl, {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        latestNewsEvents = await response.json();
      }} catch (error) {{
        console.warn('Unable to load news events', error);
        latestNewsEvents = [];
      }}
      majorEventCodes = new Set(
        (Array.isArray(latestNewsEvents) ? latestNewsEvents : [])
          .flatMap((event) => event.related_stocks || [])
          .map(normalizeHoldingCode)
          .filter(Boolean)
      );
      renderNewsEvents(latestNewsEvents);
      applyFilters();
    }}

    function renderHoldings(codes) {{
      if (!holdingsResults || !holdingsSummary) return;
      if (!codes.length) {{
        holdingsSummary.textContent = '尚未設定持股';
        holdingsResults.innerHTML = '<div class="holding-card muted-hit"><strong>尚未設定持股</strong><span>請在上方輸入股票代號後儲存。</span></div>';
        return;
      }}

      const hits = codes.filter((code) => radarByCode.has(code)).length;
      holdingsSummary.textContent = `已設定 ${{codes.length}} 檔，今日命中 ${{hits}} 檔`;
      holdingsResults.innerHTML = codes.map((code) => {{
        const stock = radarByCode.get(code);
        if (!stock) {{
          return `
            <div class="holding-card muted-hit">
              <strong>${{escapeHtml(code)}}</strong>
              <span>${{escapeHtml(code)}} 今日未入選雷達</span>
            </div>
          `;
        }}
        return `
          <div class="holding-card hit">
            <strong>${{escapeHtml(stock.code)}} ${{escapeHtml(stock.name)}}</strong>
            <span>排名 #${{escapeHtml(stock.rank)}}｜雷達等級 ${{escapeHtml(stock.rating)}}｜雷達強度 ${{escapeHtml(stock.score)}}</span>
            <div class="holding-detail">收盤價：${{escapeHtml(stock.price)}}｜成交量：${{escapeHtml(stock.volume)}} 張</div>
            <div class="holding-detail">營收年增：${{escapeHtml(stock.revenueYoy)}}｜營收月增：${{escapeHtml(stock.revenueMom)}}</div>
            <div class="holding-detail holding-concept">概念股：${{escapeHtml(stock.concept)}}</div>
            <div class="risk-tags">${{riskTagHtml(stock.riskTags)}}</div>
          </div>
        `;
      }}).join('');
    }}

    function loadHoldings() {{
      const codes = getStoredHoldings();
      if (holdingsInput) holdingsInput.value = codes.join('\\n');
      renderHoldings(codes);
    }}

    saveHoldings?.addEventListener('click', () => {{
      const codes = parseHoldings(holdingsInput?.value || '');
      setStoredHoldings(codes);
      if (holdingsInput) holdingsInput.value = codes.join('\\n');
      renderHoldings(codes);
      renderNewsEvents(latestNewsEvents);
    }});

    clearHoldings?.addEventListener('click', () => {{
      localStorage.removeItem(holdingsStorageKey);
      if (holdingsInput) holdingsInput.value = '';
      renderHoldings([]);
      renderNewsEvents(latestNewsEvents);
    }});

    exportHoldings?.addEventListener('click', () => {{
      const codes = parseHoldings(holdingsInput?.value || '').length
        ? parseHoldings(holdingsInput?.value || '')
        : getStoredHoldings();
      const blob = new Blob([JSON.stringify({{ codes }}, null, 2)], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'asurada_holdings.json';
      link.click();
      URL.revokeObjectURL(url);
    }});

    importHoldings?.addEventListener('click', () => {{
      importHoldingsFile?.click();
    }});

    importHoldingsFile?.addEventListener('change', () => {{
      const file = importHoldingsFile.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {{
        try {{
          const parsed = JSON.parse(String(reader.result || '{{}}'));
          const codes = Array.isArray(parsed) ? parsed : parsed.codes;
          if (!Array.isArray(codes)) throw new Error('Invalid holdings file');
          const normalized = parseHoldings(codes.join('\\n'));
          setStoredHoldings(normalized);
          if (holdingsInput) holdingsInput.value = normalized.join('\\n');
          renderHoldings(normalized);
          renderNewsEvents(latestNewsEvents);
        }} catch (error) {{
          alert('匯入失敗，請確認 JSON 格式是否正確。');
        }} finally {{
          importHoldingsFile.value = '';
        }}
      }};
      reader.readAsText(file, 'utf-8');
    }});

    function getRadarMode() {{
      return modeInputs.find((input) => input.checked)?.value || 'main';
    }}

    function hasAnyKeyword(text, keywords) {{
      const normalized = String(text || '').toUpperCase();
      return keywords.some((keyword) => normalized.includes(String(keyword).toUpperCase()));
    }}

    function itemMetrics(item) {{
      return {{
        code: item.dataset.code || '',
        concept: item.dataset.concept || '',
        originalScore: Number(item.dataset.score || 'NaN'),
        volume: Number(item.dataset.volume || 'NaN'),
        yoy: Number(item.dataset.yoy || 'NaN'),
        mom: Number(item.dataset.mom || 'NaN'),
        dailyChange: Number(item.dataset.change || 'NaN'),
        originalIndex: Number(item.dataset.originalIndex || '0'),
      }};
    }}

    function downgradeInfo(item) {{
      const metrics = itemMetrics(item);
      const isMainTheme = hasAnyKeyword(metrics.concept, mainThemeKeywords);
      const isConstruction = hasAnyKeyword(metrics.concept, constructionKeywords);
      const isFinance = hasAnyKeyword(metrics.concept, financeKeywords);
      const isDefensive = isConstruction || isFinance;
      let penalty = 0;
      if (isConstruction) penalty = Math.max(penalty, 10);
      if (isFinance) penalty = Math.max(penalty, 15);

      const cancelPenalty =
        metrics.volume > 3000 ||
        majorEventCodes.has(metrics.code) ||
        metrics.dailyChange > 3;

      const shouldDowngrade = isDefensive && penalty > 0 && !cancelPenalty;
      const originalScore = Number.isFinite(metrics.originalScore) ? metrics.originalScore : 0;
      const adjustedScore = shouldDowngrade ? Math.max(0, originalScore - penalty) : originalScore;
      return {{
        ...metrics,
        isMainTheme,
        isDefensive,
        shouldDowngrade,
        adjustedScore,
      }};
    }}

    function sortItems(items, mode) {{
      return [...items].sort((a, b) => {{
        const aInfo = downgradeInfo(a);
        const bInfo = downgradeInfo(b);
        if (mode === 'defensive') {{
          return (
            (bInfo.originalScore - aInfo.originalScore) ||
            ((Number.isFinite(bInfo.volume) ? bInfo.volume : -Infinity) - (Number.isFinite(aInfo.volume) ? aInfo.volume : -Infinity)) ||
            ((Number.isFinite(bInfo.yoy) ? bInfo.yoy : -Infinity) - (Number.isFinite(aInfo.yoy) ? aInfo.yoy : -Infinity)) ||
            ((Number.isFinite(bInfo.mom) ? bInfo.mom : -Infinity) - (Number.isFinite(aInfo.mom) ? aInfo.mom : -Infinity)) ||
            (aInfo.originalIndex - bInfo.originalIndex)
          );
        }}
        if (mode === 'market') {{
          return (bInfo.originalScore - aInfo.originalScore) || (aInfo.originalIndex - bInfo.originalIndex);
        }}
        return (
          (Number(bInfo.isMainTheme) - Number(aInfo.isMainTheme)) ||
          (bInfo.adjustedScore - aInfo.adjustedScore) ||
          (aInfo.originalIndex - bInfo.originalIndex)
        );
      }});
    }}

    function updateItemModeDisplay(item, mode) {{
      const info = downgradeInfo(item);
      const displayScore = mode === 'main' ? info.adjustedScore : info.originalScore;
      const scoreText = Number.isFinite(displayScore) ? displayScore.toFixed(1) : '';
      const label = modeLabels[mode] || '主升段';
      item.dataset.modeVisible = mode === 'defensive' ? String(info.isDefensive) : 'true';
      item.dataset.modeScore = scoreText;

      item.querySelectorAll('.score-value').forEach((node) => {{
        node.textContent = scoreText;
      }});
      item.querySelectorAll('.score-penalty-chip').forEach((node) => {{
        node.hidden = !(mode === 'main' && info.shouldDowngrade);
      }});
      item.querySelectorAll('.mode-tag').forEach((node) => {{
        node.textContent = label;
      }});
      item.querySelectorAll('.mode-penalty-note').forEach((node) => {{
        node.hidden = !(mode === 'main' && info.shouldDowngrade);
      }});
    }}

    function applyRadarMode() {{
      const mode = getRadarMode();
      if (radarModeNote) radarModeNote.textContent = modeNotes[mode] || modeNotes.main;
      const rows = Array.from(document.querySelectorAll('tr.radar-item'));
      const cards = Array.from(document.querySelectorAll('article.radar-item'));

      rows.forEach((row, index) => {{
        if (!row.dataset.originalIndex) row.dataset.originalIndex = String(index);
        updateItemModeDisplay(row, mode);
      }});
      cards.forEach((card, index) => {{
        if (!card.dataset.originalIndex) card.dataset.originalIndex = String(index);
        updateItemModeDisplay(card, mode);
      }});

      const tbody = document.querySelector('.summary-table tbody');
      if (tbody) {{
        sortItems(rows, mode).forEach((row) => tbody.appendChild(row));
      }}
      const mobileSection = document.querySelector('.mobile-cards');
      if (mobileSection) {{
        sortItems(cards, mode).forEach((card) => mobileSection.appendChild(card));
      }}
    }}

    function applyFilters() {{
      applyRadarMode();
      const search = (searchInput?.value || '').trim().toLowerCase();
      const rating = ratingFilter?.value || '';
      const concept = (conceptInput?.value || '').trim().toLowerCase();
      const positiveOnly = Boolean(positiveMomOnly?.checked);
      const rows = Array.from(document.querySelectorAll('tr.radar-item'));
      const cards = Array.from(document.querySelectorAll('article.radar-item'));
      let visibleRows = 0;

      function shouldShow(item) {{
        const itemSearch = item.dataset.search || '';
        const itemRating = item.dataset.rating || '';
        const itemConcept = item.dataset.concept || '';
        const itemMom = Number(item.dataset.mom || 'NaN');
        const modeVisible = item.dataset.modeVisible !== 'false';
        if (!modeVisible) return false;
        if (search && !itemSearch.includes(search)) return false;
        if (rating && itemRating !== rating) return false;
        if (concept && !itemConcept.includes(concept)) return false;
        if (positiveOnly && !(itemMom > 0)) return false;
        return true;
      }}

      rows.forEach((row) => {{
        const show = shouldShow(row);
        row.style.display = show ? '' : 'none';
        if (show) visibleRows += 1;
      }});
      cards.forEach((card) => {{
        card.style.display = shouldShow(card) ? '' : 'none';
      }});
      if (filterCount) {{
        filterCount.textContent = `顯示 ${{visibleRows}} 檔`;
      }}
      if (noResults) {{
        noResults.style.display = visibleRows === 0 ? 'block' : 'none';
      }}
    }}

    [searchInput, ratingFilter, conceptInput, positiveMomOnly].forEach((control) => {{
      control?.addEventListener('input', applyFilters);
      control?.addEventListener('change', applyFilters);
    }});
    modeInputs.forEach((control) => {{
      control.addEventListener('change', applyFilters);
    }});
    loadHoldings();
    loadNewsEvents();
    applyFilters();
  </script>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    publish_static_site(csv_path, html_path, stamp)
    return csv_path, html_path
