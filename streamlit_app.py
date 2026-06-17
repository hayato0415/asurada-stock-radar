from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
SITE_DIR = BASE_DIR / "docs"


def latest_csv_path() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("asurada_candidates_*.csv"), reverse=True)
    if candidates:
        return candidates[0]
    site_latest = SITE_DIR / "latest.csv"
    return site_latest if site_latest.exists() else None


st.set_page_config(page_title="阿斯拉台股主升段雷達", layout="wide")
st.title("阿斯拉台股主升段雷達")
st.caption("本工具僅供研究與風險控管，不構成投資建議，也不包含自動下單功能。")

csv_path = latest_csv_path()
if csv_path is None:
    st.warning("尚未找到報告資料。請先執行 `python run_daily_scan.py --price-limit 60 --top-n 30`。")
    st.stop()

report = pd.read_csv(csv_path)
st.subheader(f"最新報告：{csv_path.name}")

keyword = st.text_input("搜尋股票代號、股票名稱、概念股或公司業務")
filtered = report.copy()
if keyword:
    text = filtered.astype(str).agg(" ".join, axis=1)
    filtered = filtered[text.str.contains(keyword, case=False, na=False)]

col1, col2, col3 = st.columns(3)
col1.metric("候選股數", len(filtered))
if "阿斯拉分數" in filtered:
    col2.metric("最高分", f"{filtered['阿斯拉分數'].max():.1f}" if not filtered.empty else "-")
if "股價最後日期" in filtered:
    latest_date = filtered["股價最後日期"].dropna().astype(str).max() if not filtered.empty else "-"
    col3.metric("股價最後日期", latest_date)

st.dataframe(filtered, use_container_width=True, hide_index=True)

st.download_button(
    "下載 CSV",
    data=filtered.to_csv(index=False, encoding="utf-8-sig"),
    file_name=csv_path.name,
    mime="text/csv",
)
