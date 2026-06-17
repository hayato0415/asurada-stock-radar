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

    styled = display_report.style.hide(axis="index").format(
        {
            "月營收年增率": "{:+.2f}%",
            "月營收月增率": "{:+.2f}%",
            "阿斯拉分數": "{:.1f}",
            "收盤價": "{:,.2f}",
            "當天成交量(張)": "{:,}",
        },
        na_rep="-",
    )
    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <title>阿斯拉台股主升段雷達</title>
  <style>
    body {{ font-family: "Microsoft JhengHei", Arial, sans-serif; margin: 24px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #152238; color: white; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #f8fafc; }}
    .note {{ color: #555; margin-bottom: 16px; }}
  </style>
</head>
<body>
  <h1>阿斯拉台股主升段雷達</h1>
  <p class="note">本報告僅供研究與風險控管，不構成投資建議，也不包含自動下單功能。</p>
  {styled.to_html()}
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    publish_static_site(csv_path, html_path, stamp)
    return csv_path, html_path
