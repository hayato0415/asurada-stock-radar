from __future__ import annotations

import numpy as np
import pandas as pd

from config import REPORT_COLUMNS


BOOLEAN_COLUMNS = [
    "EPS 是否轉虧為盈",
    "毛利率是否改善",
    "法人是否上修目標價",
    "股價是否仍在低位階",
    "成交量是否溫和放大",
]

MIN_REPORT_VOLUME_SHARES = 1_000_000

INDUSTRY_NAMES = {
    "1": "水泥工業",
    "2": "食品工業",
    "3": "塑膠工業",
    "4": "紡織纖維",
    "5": "電機機械",
    "6": "電器電纜",
    "8": "玻璃陶瓷",
    "9": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "20": "其他",
    "21": "化學工業",
    "22": "生技醫療",
    "23": "油電燃氣",
    "24": "半導體",
    "25": "電腦及週邊設備",
    "26": "光電業",
    "27": "通信網路",
    "28": "電子零組件",
    "29": "電子通路",
    "30": "資訊服務",
    "31": "其他電子",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
    "91": "存託憑證",
}

CONCEPT_BY_INDUSTRY = {
    "水泥工業": "水泥;營建循環;資產題材",
    "食品工業": "食品消費;內需",
    "塑膠工業": "塑化;原物料循環",
    "紡織纖維": "紡織;成衣代工;機能布料",
    "電機機械": "電機機械;自動化;能源設備",
    "電器電纜": "電線電纜;重電;電網",
    "玻璃陶瓷": "玻璃陶瓷;建材",
    "造紙工業": "造紙;包材",
    "鋼鐵工業": "鋼鐵;原物料循環",
    "橡膠工業": "輪胎;橡膠材料",
    "汽車工業": "汽車零組件;電動車",
    "建材營造": "營建;資產;都更",
    "航運業": "航運;景氣循環",
    "觀光餐旅": "觀光;餐飲;內需",
    "金融保險": "金融;壽險;銀行",
    "貿易百貨": "通路;百貨;內需",
    "化學工業": "化工材料;特用化學",
    "生技醫療": "生技醫療;醫材;新藥",
    "油電燃氣": "能源;油電燃氣",
    "半導體": "半導體;AI供應鏈;先進製程",
    "電腦及週邊設備": "AI伺服器;PC/NB;邊緣運算",
    "光電業": "光電;面板;光通訊/CPO",
    "通信網路": "網通;光通訊;CPO",
    "電子零組件": "PCB;被動元件;電子零組件",
    "電子通路": "電子通路;半導體通路",
    "資訊服務": "資訊服務;資安;雲端",
    "其他電子": "AI伺服器供應鏈;設備;電子製造服務",
    "綠能環保": "綠能環保;循環經濟",
    "數位雲端": "雲端服務;系統整合;AI應用",
    "運動休閒": "運動休閒;品牌代工",
    "居家生活": "居家生活;消費",
}

BUSINESS_BY_INDUSTRY = {
    "半導體": "半導體設計、製造、封測、材料或設備相關公司。",
    "電腦及週邊設備": "PC、筆電、伺服器、AI伺服器或週邊設備相關公司。",
    "光電業": "面板、LED、光學元件、光通訊或顯示相關公司。",
    "通信網路": "網通設備、通訊模組、光通訊或電信設備相關公司。",
    "電子零組件": "PCB、被動元件、連接器、機構件或其他電子零組件公司。",
    "資訊服務": "企業資訊服務、系統整合、軟體、資安或雲端服務公司。",
    "數位雲端": "雲端平台、數位服務、系統整合或AI應用服務公司。",
    "其他電子": "電子製造服務、設備、材料或AI伺服器供應鏈公司。",
    "建材營造": "建設開發、營造工程、資產開發或不動產相關公司。",
    "綠能環保": "再生能源、環保處理、循環經濟或節能相關公司。",
    "生技醫療": "醫療器材、藥品、生技服務或醫療通路相關公司。",
}

STOCK_CONCEPT_OVERRIDES = {
    "2337": ("記憶體;低基期;NOR Flash;AI邊緣需求", "旺宏主要做 NOR Flash、NAND Flash 與唯讀記憶體。"),
    "2327": ("被動元件;MLCC;車用電子", "國巨主要做 MLCC、晶片電阻等被動元件。"),
    "2492": ("被動元件;MLCC;車用電子", "華新科主要做 MLCC、晶片電阻與保護元件。"),
    "2456": ("被動元件;電感;車用電子", "奇力新主要做電感、磁性元件與被動元件。"),
    "2382": ("AI伺服器;雲端資料中心;EMS", "廣達主要做筆電、伺服器與雲端資料中心硬體。"),
    "3231": ("AI伺服器;雲端資料中心;EMS", "緯創主要做資通訊產品代工、伺服器與AI伺服器。"),
    "2356": ("AI伺服器;伺服器代工;PC/NB", "英業達主要做筆電、伺服器與企業運算設備。"),
    "6669": ("AI伺服器;雲端資料中心;伺服器整機", "緯穎主要做雲端資料中心與伺服器整機解決方案。"),
    "2317": ("AI伺服器;EMS;消費電子", "鴻海主要做電子製造服務，涵蓋伺服器、消費電子與電動車。"),
    "3037": ("PCB;ABF載板;AI/HPC", "欣興主要做 PCB、IC載板與高階載板。"),
    "8046": ("PCB;IC載板;ABF載板", "南電主要做 PCB 與 IC載板。"),
    "2313": ("PCB;HDI;車用電子", "華通主要做 PCB、HDI板與電子電路板。"),
    "2368": ("PCB;AI伺服器;高階板材", "金像電主要做伺服器與網通用 PCB。"),
    "6274": ("PCB材料;銅箔基板;AI伺服器", "台燿主要做銅箔基板與高頻高速材料。"),
    "2345": ("網通;光通訊;CPO概念", "智邦主要做交換器、網通設備與資料中心網路設備。"),
    "3450": ("光通訊;CPO概念;光收發模組", "聯鈞主要做光通訊元件與光收發相關產品。"),
    "3042": ("石英;頻率元件;車用電子", "晶技主要做石英晶體、振盪器與頻率控制元件。"),
    "2484": ("石英;頻率元件;網通/車用", "希華主要做石英晶體、振盪器與頻率控制元件。"),
    "3017": ("AI伺服器;散熱;機構件", "奇鋐主要做散熱模組、風扇與伺服器散熱。"),
    "3324": ("AI伺服器;散熱;水冷", "雙鴻主要做散熱模組與伺服器散熱方案。"),
    "3653": ("AI伺服器;高速傳輸;連接器", "健策主要做導線架、散熱與高速連接相關零組件。"),
    "6614": ("數位雲端;資訊服務;系統整合", "資拓宏宇主要做資訊系統整合、軟體開發與數位政府服務。"),
}


def _as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin(["true", "1", "yes", "y", "是"])


def _industry_label(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return INDUSTRY_NAMES.get(text, text or "未分類")


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", ""} else text


def _concept_and_business(row: pd.Series) -> pd.Series:
    code = str(row.get("股票代號", "")).zfill(4)
    industry = _industry_label(row.get("產業別"))
    manual_topic = _clean_text(row.get("手動題材分類"))
    override = STOCK_CONCEPT_OVERRIDES.get(code)
    if override:
        concept, business = override
    else:
        concept = CONCEPT_BY_INDUSTRY.get(industry, industry or "未分類")
        business = BUSINESS_BY_INDUSTRY.get(industry, f"{industry}相關公司，需再追蹤產品組合與主要客戶。")
    if manual_topic:
        concept = manual_topic
    return pd.Series({"概念股": concept, "公司業務": business})


def prefilter_by_revenue(revenue: pd.DataFrame, limit: int = 180) -> pd.DataFrame:
    frame = revenue.copy()
    frame["月營收年增率"] = pd.to_numeric(frame["月營收年增率"], errors="coerce")
    frame["月營收月增率"] = pd.to_numeric(frame["月營收月增率"], errors="coerce")
    frame["營收預篩分數"] = (
        frame["月營收年增率"].clip(-30, 100).fillna(-30)
        + frame["月營收月增率"].clip(-20, 50).fillna(-20) * 0.8
    )
    return frame.sort_values("營收預篩分數", ascending=False).head(limit)


def build_candidates(
    stocks: pd.DataFrame,
    revenue: pd.DataFrame,
    manual: pd.DataFrame,
    price_signals: pd.DataFrame,
) -> pd.DataFrame:
    frame = revenue.merge(
        stocks[["股票代號", "股票名稱", "市場", "產業別"]],
        on=["股票代號", "市場"],
        how="left",
        suffixes=("", "_清單"),
    )
    frame["股票名稱"] = frame["股票名稱_清單"].fillna(frame["股票名稱"])
    frame = frame.drop(columns=["股票名稱_清單"], errors="ignore")
    frame = frame.merge(manual, on="股票代號", how="left")
    frame = frame.merge(price_signals, on="股票代號", how="left")

    frame["手動題材分類"] = frame["題材分類"]
    industry_topics = frame["產業別"].map(_industry_label)
    frame["題材分類"] = frame["題材分類"].fillna(industry_topics).map(_industry_label)
    frame[["概念股", "公司業務"]] = frame.apply(_concept_and_business, axis=1)
    frame["關注原因"] = frame["關注原因"].fillna("")
    frame["催化時間"] = frame["催化時間"].fillna("未設定")
    frame["風險說明"] = frame["風險說明"].fillna(
        "需追蹤營收延續性、產業循環、籌碼與大盤系統性風險"
    )
    for column in BOOLEAN_COLUMNS:
        if column not in frame:
            frame[column] = False
        frame[column] = _as_bool(frame[column])

    # Heuristic defaults until real EPS/margin/institutional data is connected.
    frame["EPS 是否轉虧為盈"] = frame["EPS 是否轉虧為盈"] | (
        frame["月營收年增率"].fillna(0) >= 80
    )
    frame["毛利率是否改善"] = frame["毛利率是否改善"] | (
        (frame["月營收年增率"].fillna(0) >= 30)
        & (frame["月營收月增率"].fillna(0) >= 10)
    )

    yoy_points = frame["月營收年增率"].clip(0, 100).fillna(0) / 100 * 25
    mom_points = frame["月營收月增率"].clip(0, 50).fillna(0) / 50 * 15
    score = (
        yoy_points
        + mom_points
        + frame["EPS 是否轉虧為盈"].astype(int) * 10
        + frame["毛利率是否改善"].astype(int) * 10
        + frame["法人是否上修目標價"].astype(int) * 10
        + frame["股價是否仍在低位階"].astype(int) * 15
        + frame["成交量是否溫和放大"].astype(int) * 10
        + frame["概念股"].astype(str).str.len().gt(0).astype(int) * 5
    )
    frame["阿斯拉分數"] = score.clip(0, 100).round(1)
    frame["阿斯拉評級"] = pd.cut(
        frame["阿斯拉分數"],
        bins=[-1, 50, 65, 75, 85, 101],
        labels=["觀察", "B", "A-", "A", "S"],
    ).astype(str)
    frame["是否適合慢慢買"] = np.where(
        (frame["阿斯拉分數"] >= 70)
        & frame["股價是否仍在低位階"]
        & frame["成交量是否溫和放大"],
        "是",
        "否",
    )
    frame.loc[frame["關注原因"].eq(""), "關注原因"] = (
        "營收年增 "
        + frame["月營收年增率"].round(1).astype(str)
        + "%，月增 "
        + frame["月營收月增率"].round(1).astype(str)
        + "%，符合低基期轉強預篩"
    )
    return frame.sort_values("阿斯拉分數", ascending=False)


def top_report(frame: pd.DataFrame, limit: int | None = 30) -> pd.DataFrame:
    filtered = frame.copy()
    if "當天成交量" in filtered.columns:
        filtered["當天成交量"] = pd.to_numeric(filtered["當天成交量"], errors="coerce")
        filtered = filtered[filtered["當天成交量"].ge(MIN_REPORT_VOLUME_SHARES)]

    ranked_source = filtered.sort_values(
        ["阿斯拉分數", "月營收年增率", "月營收月增率"],
        ascending=False,
    )
    if limit is not None:
        ranked_source = ranked_source.head(limit)
    ranked = ranked_source.copy()
    ranked.insert(0, "排名", range(1, len(ranked) + 1))
    columns = [column for column in REPORT_COLUMNS if column in filtered.columns]
    columns.insert(0, "排名")
    extra = ["阿斯拉分數", "收盤價", "當天成交量", "股價最後日期", "市場", "年月", "單月營收_千元"]
    columns.extend([column for column in extra if column in filtered.columns])
    return ranked[columns]
