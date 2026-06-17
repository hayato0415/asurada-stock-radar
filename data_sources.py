from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from config import DATA_DIR, MANUAL_FACTORS_PATH, REVENUE_PATH, STOCK_LIST_PATH


STOCK_DIRECTORY_ENDPOINTS = {
    "上市": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
}
REVENUE_ENDPOINTS = {
    "上市": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
}


def normalize_code(value: object) -> str:
    text = str(value).strip().upper()
    if text.endswith((".TW", ".TWO")):
        text = text.rsplit(".", 1)[0]
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(4)


def _number(value: object) -> float:
    text = str(value or "").replace(",", "").strip()
    return pd.to_numeric(text, errors="coerce")


def _roc_month(value: object) -> str:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 5:
        return ""
    return f"{int(digits[:-2]) + 1911:04d}-{int(digits[-2:]):02d}"


def _roc_date(value: object) -> pd.Timestamp | pd.NaT:
    parts = re.findall(r"\d+", str(value))
    if len(parts) < 3:
        return pd.NaT
    year = int(parts[0])
    if year < 1911:
        year += 1911
    return pd.Timestamp(year=year, month=int(parts[1]), day=int(parts[2]))


def _fetch_json(url: str) -> list[dict[str, object]]:
    response = requests.get(url, headers={"User-Agent": "asurada-radar/1.0"}, timeout=30)
    response.raise_for_status()
    return response.json()


@dataclass
class DataProvider:
    data_dir: Path = DATA_DIR

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch_stock_list(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        errors: list[str] = []
        for market, url in STOCK_DIRECTORY_ENDPOINTS.items():
            try:
                payload = _fetch_json(url)
            except Exception as exc:
                errors.append(f"{market}: {exc}")
                continue
            for item in payload:
                code = item.get("公司代號") or item.get("SecuritiesCompanyCode")
                name = item.get("公司簡稱") or item.get("CompanyAbbreviation")
                industry = item.get("產業別") or item.get("SecuritiesIndustryCode")
                if code and name:
                    rows.append(
                        {
                            "股票代號": normalize_code(code),
                            "股票名稱": str(name).strip(),
                            "市場": market,
                            "產業別": str(industry or "").strip(),
                        }
                    )
        if not rows:
            raise RuntimeError("無法取得台股股票清單：" + "；".join(errors))
        return pd.DataFrame(rows).drop_duplicates("股票代號", keep="last")

    def load_or_fetch_stock_list(self, refresh: bool = False) -> pd.DataFrame:
        self.ensure_dirs()
        if refresh or not STOCK_LIST_PATH.exists():
            stocks = self.fetch_stock_list()
            stocks.to_csv(STOCK_LIST_PATH, index=False, encoding="utf-8-sig")
            return stocks
        stocks = pd.read_csv(STOCK_LIST_PATH, dtype={"股票代號": str})
        return stocks[stocks["市場"].eq("上市")].reset_index(drop=True)

    def fetch_monthly_revenue(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        errors: list[str] = []
        for market, url in REVENUE_ENDPOINTS.items():
            try:
                payload = _fetch_json(url)
            except Exception as exc:
                errors.append(f"{market}: {exc}")
                continue
            for item in payload:
                code = item.get("公司代號")
                if not code:
                    continue
                rows.append(
                    {
                        "年月": _roc_month(item.get("資料年月")),
                        "股票代號": normalize_code(code),
                        "股票名稱": str(item.get("公司名稱", "")).strip(),
                        "市場": market,
                        "單月營收_千元": _number(item.get("營業收入-當月營收")),
                        "月營收年增率": _number(item.get("營業收入-去年同月增減(%)")),
                        "月營收月增率": _number(item.get("營業收入-上月比較增減(%)")),
                        "累計營收年增率": _number(item.get("累計營業收入-前期比較增減(%)")),
                    }
                )
        if not rows:
            raise RuntimeError("無法取得月營收資料：" + "；".join(errors))
        return pd.DataFrame(rows).drop_duplicates("股票代號", keep="last")

    def load_or_fetch_revenue(self, refresh: bool = False) -> pd.DataFrame:
        self.ensure_dirs()
        if refresh or not REVENUE_PATH.exists():
            revenue = self.fetch_monthly_revenue()
            revenue.to_csv(REVENUE_PATH, index=False, encoding="utf-8-sig")
            return revenue
        revenue = pd.read_csv(REVENUE_PATH, dtype={"股票代號": str})
        return revenue[revenue["市場"].eq("上市")].reset_index(drop=True)

    def load_manual_factors(self) -> pd.DataFrame:
        columns = [
            "股票代號",
            "題材分類",
            "關注原因",
            "催化時間",
            "EPS 是否轉虧為盈",
            "毛利率是否改善",
            "法人是否上修目標價",
            "風險說明",
        ]
        if not MANUAL_FACTORS_PATH.exists():
            template = pd.DataFrame(
                [
                    {
                        "股票代號": "2337",
                        "題材分類": "記憶體;低基期;AI邊緣需求",
                        "關注原因": "低基期後營收轉強，若價格與報價循環續揚，具重新估值空間",
                        "催化時間": "月營收連續公布與法說會",
                        "EPS 是否轉虧為盈": True,
                        "毛利率是否改善": True,
                        "法人是否上修目標價": False,
                        "風險說明": "記憶體價格循環反轉、庫存調整、匯率與終端需求不如預期",
                    }
                ],
                columns=columns,
            )
            template.to_csv(MANUAL_FACTORS_PATH, index=False, encoding="utf-8-sig")
            return template
        factors = pd.read_csv(MANUAL_FACTORS_PATH, dtype={"股票代號": str})
        for column in columns:
            if column not in factors:
                factors[column] = False if "是否" in column else ""
        factors["股票代號"] = factors["股票代號"].map(normalize_code)
        return factors[columns]

    def fetch_twse_price_history(self, code: str, months: int = 8) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        month_starts = pd.date_range(
            end=pd.Timestamp.today().replace(day=1).normalize(),
            periods=months,
            freq="MS",
        )
        for month_start in month_starts:
            url = (
                "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                f"?date={month_start:%Y%m%d}&stockNo={code}&response=json"
            )
            try:
                payload = _fetch_json(url)
            except Exception:
                continue
            if not isinstance(payload, dict) or payload.get("stat") != "OK":
                continue
            fields = payload.get("fields", [])
            for item in payload.get("data", []):
                record = dict(zip(fields, item))
                rows.append(
                    {
                        "Date": _roc_date(record.get("日期")),
                        "Close": _number(record.get("收盤價")),
                        "Volume": _number(record.get("成交股數")),
                    }
                )
        if not rows:
            return pd.DataFrame()
        history = pd.DataFrame(rows).dropna(subset=["Date", "Close", "Volume"])
        return history.sort_values("Date").drop_duplicates("Date", keep="last")

    def fallback_price_signal(self, stock: dict[str, object]) -> dict[str, object]:
        code = normalize_code(stock["股票代號"])
        seed = int(code)
        revenue_yoy = _number(stock.get("月營收年增率"))
        revenue_mom = _number(stock.get("月營收月增率"))
        base_price = 20 + seed % 80 + (seed % 7) * 0.35
        volume_ratio = 0.8 + min(max((revenue_yoy if pd.notna(revenue_yoy) else 0) / 200, 0), 0.9)
        volume_ratio += min(max((revenue_mom if pd.notna(revenue_mom) else 0) / 300, 0), 0.4)
        volume_ratio = round(float(volume_ratio), 2)
        latest_volume = 100_000 + seed * 137
        return {
            "股票代號": code,
            "收盤價": round(float(base_price), 2),
            "股價是否仍在低位階": False,
            "成交量是否溫和放大": 1.1 <= volume_ratio <= 2.5,
            "量比": volume_ratio,
            "當天成交量": latest_volume,
            "股價資料來源": "fallback 模擬資料",
            "股價最後日期": "無真實資料",
        }

    def fetch_price_signals(self, candidates: pd.DataFrame, limit: int = 180) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        scan = candidates.head(limit).copy()
        for stock in scan.to_dict("records"):
            code = stock["股票代號"]
            symbols = [f"{code}.TW"]
            history = pd.DataFrame()
            used_symbol = ""
            for symbol in symbols:
                try:
                    history = yf.Ticker(symbol).history(
                        period="6mo",
                        interval="1d",
                        auto_adjust=False,
                        actions=False,
                        timeout=20,
                    )
                    if not history.empty:
                        used_symbol = symbol
                        break
                except Exception:
                    continue
            if history.empty:
                try:
                    history = self.fetch_twse_price_history(code)
                    if not history.empty:
                        used_symbol = "TWSE STOCK_DAY"
                except Exception:
                    history = pd.DataFrame()
            if history.empty:
                rows.append(self.fallback_price_signal(stock))
                continue
            close = history["Close"].dropna()
            volume = history["Volume"].dropna()
            latest_close = float(close.iloc[-1])
            low = float(close.min())
            high = float(close.max())
            price_position = (latest_close - low) / (high - low) if high > low else 1
            avg_volume = float(volume.shift(1).tail(20).mean())
            latest_volume = float(volume.iloc[-1])
            volume_ratio = latest_volume / avg_volume if avg_volume else np.nan
            latest_date = (
                pd.to_datetime(history["Date"].iloc[-1]).strftime("%Y-%m-%d")
                if "Date" in history.columns
                else pd.to_datetime(close.index[-1]).strftime("%Y-%m-%d")
            )
            rows.append(
                {
                    "股票代號": code,
                    "收盤價": latest_close,
                    "股價是否仍在低位階": price_position <= 0.45,
                    "成交量是否溫和放大": 1.1 <= volume_ratio <= 2.5 if pd.notna(volume_ratio) else False,
                    "量比": volume_ratio,
                    "當天成交量": latest_volume,
                    "股價資料來源": used_symbol,
                    "股價最後日期": latest_date,
                }
            )
        return pd.DataFrame(rows)
