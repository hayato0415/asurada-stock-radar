(function registerStockClassifier(global) {
  "use strict";

  const INDUSTRY_CODE_NAMES = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織", "05": "電機機械", "06": "電器電纜",
    "07": "化學生技醫療", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠", "12": "汽車",
    "14": "營建", "15": "航運", "16": "觀光", "17": "金融保險", "18": "貿易百貨", "20": "其他",
    "21": "化學", "22": "生技醫療", "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊設備",
    "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子",
    "32": "文化創意", "33": "農業科技", "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
  };

  const NON_ELECTRONIC_POOL_KEYWORDS = [
    "金融", "壽險", "銀行", "金融保險", "輪胎", "橡膠", "橡膠材料", "營建", "營造", "資產", "都更",
    "生技醫療", "生技", "醫材", "新藥",
  ];

  const RADAR_POOL_OVERRIDES = {
    "1802": { industryName: "玻璃陶瓷", themeTags: ["AI玻璃基板", "TGV", "先進封裝", "AI材料"] },
    "1504": { industryName: "電機機械 / 重電", themeTags: ["AI電力", "資料中心", "重電"] },
    "1513": { industryName: "重電", themeTags: ["AI電力", "電網", "資料中心"] },
    "1605": { industryName: "電器電纜", themeTags: ["AI電力", "銅價", "資料中心"] },
  };

  function normalizeCode(value) {
    return String(value || "").trim().toUpperCase().replace(/\.(TW|TWO)$/i, "");
  }

  function splitThemeValues(value) {
    if (Array.isArray(value)) return value.flatMap(splitThemeValues);
    return String(value || "").split(/[;,、|/]+/).map((item) => item.trim()).filter(Boolean);
  }

  function themeKeywordMatches(text, keyword) {
    const value = String(keyword || "").toUpperCase();
    if (/^[A-Z0-9.]+$/.test(value) && value.length <= 3) {
      const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return new RegExp(`(^|[^A-Z0-9])${escaped}([^A-Z0-9]|$)`).test(text);
    }
    return text.includes(value);
  }

  function createStockClassifier(options = {}) {
    const getMasterRecord = options.getMasterRecord || (() => ({}));
    const getStockName = options.getStockName || ((code) => code);
    const themeTaxonomy = options.themeTaxonomy || {};

    function getIndustryName(stock) {
      const code = normalizeCode(stock?.code);
      if (RADAR_POOL_OVERRIDES[code]?.industryName) return RADAR_POOL_OVERRIDES[code].industryName;
      const master = getMasterRecord(code) || {};
      const values = [stock?.industryName, stock?.industry, stock?.sector, stock?.category, master.industryName, master.industry, master.sector, master.category];
      for (const value of values) {
        const text = String(value || "").trim();
        if (!text) continue;
        const codeMatch = text.match(/^0?(\d{1,2})(?:\D|$)/);
        if (!codeMatch) return text;
        const name = INDUSTRY_CODE_NAMES[codeMatch[1].padStart(2, "0")];
        if (name) return name;
      }
      return "";
    }

    function radarText(stock) {
      return [stock?.industryName, stock?.industry, stock?.sector, stock?.category, stock?.concept, stock?.themeTags, stock?.themes, stock?.reason, stock?.news, stock?.description, stock?.business, getIndustryName(stock)]
        .map((value) => {
          if (Array.isArray(value)) return value.join(" ");
          if (value && typeof value === "object") return JSON.stringify(value);
          return String(value || "");
        })
        .join(" ");
    }

    function getRadarPool(stock) {
      const code = normalizeCode(stock?.code);
      if (RADAR_POOL_OVERRIDES[code]) return "electronicTechPool";
      const text = radarText(stock);
      if (NON_ELECTRONIC_POOL_KEYWORDS.some((keyword) => text.includes(keyword))) return "nonElectronicPool";
      if (!text.trim()) {
        console.warn("雷達分類資料不足，預設歸入 electronicTechPool", {
          code,
          name: getStockName(code),
          industry: stock?.industryName || stock?.industry || stock?.sector || stock?.category || "",
        });
      }
      return "electronicTechPool";
    }

    function inferThemeTags(stock) {
      const tags = [];
      const add = (value) => {
        const text = String(value || "").trim();
        if (text && !tags.includes(text)) tags.push(text);
      };
      splitThemeValues(stock?.themeTags).forEach(add);
      splitThemeValues(stock?.themes).forEach(add);
      (RADAR_POOL_OVERRIDES[normalizeCode(stock?.code)]?.themeTags || []).forEach(add);
      const text = radarText(stock).toUpperCase();
      Object.entries(themeTaxonomy).forEach(([theme, keywords]) => {
        if (keywords.some((keyword) => themeKeywordMatches(text, keyword))) add(theme);
      });
      if (!tags.length) {
        const concept = String(stock?.concept || "").trim();
        add(concept && !/^\d+$/.test(concept) ? concept : getIndustryName(stock));
      }
      return tags;
    }

    return Object.freeze({ getIndustryName, getRadarPool, inferThemeTags });
  }

  global.AsuradaStockClassifier = Object.freeze({
    createStockClassifier,
    INDUSTRY_CODE_NAMES,
    NON_ELECTRONIC_POOL_KEYWORDS,
    RADAR_POOL_OVERRIDES,
  });
}(globalThis));
