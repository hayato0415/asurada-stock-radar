from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, SITE_DIR


BOOLEAN_DISPLAY_COLUMNS = [
    "EPS 是否轉虧為盈",
    "毛利率是否改善",
    "法人是否上修目標價",
    "股價是否仍在低位階",
    "成交量是否溫和放大",
]


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


def format_report_for_output(report: pd.DataFrame) -> pd.DataFrame:
    """Format display-only values without changing scoring internals."""
    output = report.copy()
    for column in BOOLEAN_DISPLAY_COLUMNS:
        if column in output.columns:
            output[column] = output[column].map(_to_yes_no)
    for column in ["收盤價"]:
        if column in output.columns:
            output[column] = pd.to_numeric(output[column], errors="coerce").round(2)
    for column in ["月營收年增率", "月營收月增率"]:
        if column in output.columns:
            values = pd.to_numeric(output[column], errors="coerce")
            output[column] = values.map(lambda value: "-" if pd.isna(value) else f"{value:+.2f}%")
    if "阿斯拉分數" in output.columns:
        values = pd.to_numeric(output["阿斯拉分數"], errors="coerce")
        output["阿斯拉分數"] = values.map(lambda value: "-" if pd.isna(value) else f"{value:.1f}")
    if "當天成交量" in output.columns:
        output["當天成交量"] = (
            pd.to_numeric(output["當天成交量"], errors="coerce").div(1000).round(0).astype("Int64")
        )
        output = output.rename(columns={"當天成交量": "當天成交量(張)"})
    return output


def build_index_html(latest_report: str, latest_csv: str, stamp: str) -> str:
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={latest_report}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>阿斯拉台股主升段雷達</title>
  <style>
    body {{ font-family: "Microsoft JhengHei", Arial, sans-serif; margin: 32px; line-height: 1.6; }}
    a {{ color: #0f4c81; }}
  </style>
</head>
<body>
  <h1>阿斯拉台股主升段雷達</h1>
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


def build_mobile_cards(display_report: pd.DataFrame) -> str:
    cards: list[str] = []
    for _, row in display_report.iterrows():
        rank = _value(row, "排名")
        code = _value(row, "股票代號")
        name = _value(row, "股票名稱")
        rating = _value(row, "阿斯拉評級")
        score = _format_number(row, "阿斯拉分數", decimals=1)
        concept = _value(row, "概念股")
        reason = _value(row, "關注原因")
        business = _value(row, "公司業務")
        risk = _value(row, "風險說明")
        price = _format_number(row, "收盤價", decimals=2)
        volume = _value(row, "當天成交量(張)")
        yoy = _format_percent(row, "月營收年增率")
        mom = _format_percent(row, "月營收月增率")
        date = _value(row, "股價最後日期")
        slow_buy = _value(row, "是否適合慢慢買")
        cards.append(
            f"""
    <article class="stock-card">
      <div class="card-top">
        <div>
          <div class="rank">#{rank}</div>
          <h2>{code} {name}</h2>
        </div>
        <div class="badge">{rating}</div>
      </div>
      <div class="metrics">
        <div><span>分數</span><strong>{score}</strong></div>
        <div><span>收盤</span><strong>{price}</strong></div>
        <div><span>成交量</span><strong>{volume} 張</strong></div>
      </div>
      <div class="metrics">
        <div><span>年增</span><strong>{yoy}</strong></div>
        <div><span>月增</span><strong>{mom}</strong></div>
        <div><span>慢慢買</span><strong>{slow_buy}</strong></div>
      </div>
      <p class="concept"><span>概念股：</span>{concept}</p>
      <p><strong>關注：</strong>{reason}</p>
      <details>
        <summary>公司業務與風險</summary>
        <p>{business}</p>
        <p><strong>風險：</strong>{risk}</p>
        <p class="date">股價最後日期：{date}</p>
      </details>
    </article>
"""
        )
    return "\n".join(cards)


def build_desktop_summary_table(display_report: pd.DataFrame) -> str:
    columns = [
        "排名",
        "股票代號",
        "股票名稱",
        "概念股",
        "阿斯拉分數",
        "阿斯拉評級",
        "收盤價",
        "當天成交量(張)",
        "月營收年增率",
        "月營收月增率",
        "關注原因",
        "股價最後日期",
    ]
    available = [column for column in columns if column in display_report.columns]
    summary = display_report[available].copy()
    return summary.to_html(index=False, classes="summary-table", border=0)


def publish_static_site(csv_path: Path, html_path: Path, stamp: str, site_dir: Path = SITE_DIR) -> None:
    reports_dir = site_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    site_html = reports_dir / html_path.name
    site_csv = reports_dir / csv_path.name
    latest_html = site_dir / "latest.html"
    latest_csv = site_dir / "latest.csv"

    shutil.copy2(html_path, site_html)
    shutil.copy2(csv_path, site_csv)
    shutil.copy2(html_path, latest_html)
    shutil.copy2(csv_path, latest_csv)

    index_html = build_index_html("latest.html", "latest.csv", stamp)
    (site_dir / "index.html").write_text(index_html, encoding="utf-8")


def write_reports(report: pd.DataFrame, output_dir: Path = OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    csv_path = output_dir / f"asurada_candidates_{stamp}.csv"
    html_path = output_dir / f"asurada_candidates_{stamp}.html"
    display_report = format_report_for_output(report)
    display_report.to_csv(csv_path, index=False, encoding="utf-8-sig")

    desktop_table = build_desktop_summary_table(display_report)
    mobile_cards = build_mobile_cards(display_report)
    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>阿斯拉台股主升段雷達</title>
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
    .desktop-table {{
      background: var(--card);
      border-radius: 14px;
      overflow: hidden;
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
    .summary-table th {{ background: #152238; color: white; position: sticky; top: 0; }}
    .summary-table th:nth-child(1), .summary-table td:nth-child(1) {{ width: 42px; text-align: center; }}
    .summary-table th:nth-child(2), .summary-table td:nth-child(2) {{ width: 70px; }}
    .summary-table th:nth-child(3), .summary-table td:nth-child(3) {{ width: 86px; }}
    .summary-table th:nth-child(4), .summary-table td:nth-child(4) {{ width: 150px; }}
    .summary-table th:nth-child(5), .summary-table td:nth-child(5) {{ width: 70px; text-align: right; }}
    .summary-table th:nth-child(6), .summary-table td:nth-child(6) {{ width: 64px; text-align: center; }}
    .summary-table th:nth-child(7), .summary-table td:nth-child(7) {{ width: 76px; text-align: right; }}
    .summary-table th:nth-child(8), .summary-table td:nth-child(8) {{ width: 92px; text-align: right; }}
    .summary-table th:nth-child(9), .summary-table td:nth-child(9) {{ width: 88px; text-align: right; }}
    .summary-table th:nth-child(10), .summary-table td:nth-child(10) {{ width: 88px; text-align: right; }}
    .summary-table th:nth-child(12), .summary-table td:nth-child(12) {{ width: 92px; }}
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
    .actions a {{
      color: white;
      display: inline-block;
      border: 1px solid rgba(255,255,255,.45);
      border-radius: 999px;
      padding: 6px 12px;
      text-decoration: none;
      margin-right: 8px;
    }}
    @media (max-width: 768px) {{
      .page {{ padding: 12px; }}
      .hero {{ border-radius: 0 0 18px 18px; margin: -12px -12px 14px; padding: 18px 14px; }}
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
      <h1>阿斯拉台股主升段雷達</h1>
      <p class="note">本報告僅供研究與風險控管，不構成投資建議，也不包含自動下單功能。</p>
      <div class="actions">
        <a href="latest.csv">下載 CSV</a>
        <a href="https://github.com/hayato0415/jtgame-search">GitHub</a>
      </div>
    </section>
    <section class="mobile-cards">
      {mobile_cards}
    </section>
    <section class="desktop-table">
      {desktop_table}
    </section>
  </main>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    publish_static_site(csv_path, html_path, stamp)
    return csv_path, html_path
