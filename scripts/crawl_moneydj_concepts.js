#!/usr/bin/env node

const fs = require("node:fs/promises");
const path = require("node:path");

const MONEYDJ_SOURCE = "MoneyDJ";
const MONEYDJ_HOME = "https://www.moneydj.com";
const DEFAULT_SOURCE_URL = "https://www.moneydj.com/z/zg/zge/zge_E_E.djhtm";
const OUTPUT_DIR = path.resolve("data");
const SITE_DATA_DIR = path.resolve("docs", "data");
const CSV_NAME = "moneydj_concept_categories.csv";
const REPORT_NAME = "moneydj_concept_categories_report.json";
const COMPARE_NAME = "concept_source_compare.csv";

function nowIso() {
  return new Date().toISOString();
}

function decodeHtml(text) {
  return String(text || "")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function toCsv(rows, columns) {
  return [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvEscape(row[column])).join(",")),
  ].join("\n") + "\n";
}

function optionAttributes(rawAttrs) {
  const attrs = {};
  const pattern = /([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g;
  let match;
  while ((match = pattern.exec(rawAttrs || ""))) {
    attrs[match[1].toLowerCase()] = match[2] ?? match[3] ?? match[4] ?? "";
  }
  return attrs;
}

function conceptCodeFrom(value, text) {
  const raw = String(value || text || "").trim();
  const urlMatch = raw.match(/zge_([A-Za-z0-9]+)_\d+\.djhtm/i);
  if (urlMatch) return urlMatch[1].toUpperCase();
  const codeMatch = raw.match(/\b([A-Za-z]{1,4}\d{3,})\b/);
  if (codeMatch) return codeMatch[1].toUpperCase();
  return "";
}

function sourceUrlFor(code, rawValue) {
  const value = String(rawValue || "").trim();
  if (/^https?:\/\//i.test(value)) return value;
  if (/zge_[A-Za-z0-9]+_\d+\.djhtm/i.test(value)) {
    return new URL(value, MONEYDJ_HOME).href;
  }
  return code ? `${MONEYDJ_HOME}/z/zg/zge_${code}_1.djhtm` : DEFAULT_SOURCE_URL;
}

function parseOptionsFromHtml(html, updatedAt) {
  const rows = [];
  const seen = new Set();
  const optionPattern = /<option\b([^>]*)>([\s\S]*?)<\/option>/gi;
  let match;
  while ((match = optionPattern.exec(html))) {
    const attrs = optionAttributes(match[1]);
    const value = decodeHtml(attrs.value || "");
    const name = decodeHtml(match[2]);
    const code = conceptCodeFrom(value, name);
    if (!code || !name) continue;
    if (/請選擇|全部|--/.test(name)) continue;
    const key = `${code}:${name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({
      concept_code: code,
      concept_name: name,
      source: MONEYDJ_SOURCE,
      source_url: sourceUrlFor(code, value),
      updated_at: updatedAt,
      status: "active",
    });
  }
  return rows;
}

async function fetchHtml(url) {
  if (typeof fetch !== "function") {
    throw new Error("目前 Node.js 版本沒有內建 fetch，請使用 Node.js 18 以上。");
  }
  const response = await fetch(url, {
    headers: {
      "user-agent": "asurada-moneydj-concept-crawler/1.0",
      "accept-language": "zh-TW,zh;q=0.9,en;q=0.7",
    },
  });
  if (!response.ok) throw new Error(`MoneyDJ 回應狀態 ${response.status}`);
  return response.text();
}

async function parseWithPlaywright(url, updatedAt) {
  let chromium;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    throw new Error("HTML 找不到 option，且尚未安裝 Playwright。可執行：npm install playwright");
  }
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
    const options = await page.$$eval("select option", (nodes) =>
      nodes.map((node) => ({
        value: node.getAttribute("value") || "",
        text: node.textContent || "",
      }))
    );
    const html = options
      .map((option) => `<option value="${option.value}">${option.text}</option>`)
      .join("\n");
    return parseOptionsFromHtml(html, updatedAt);
  } finally {
    await browser.close();
  }
}

async function ensureOutputFiles() {
  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  await fs.mkdir(SITE_DATA_DIR, { recursive: true });
  const compareHeader = "concept_name,stock_id,stock_name,sources,source_count,confidence,status,updated_at,note\n";
  for (const filePath of [
    path.join(OUTPUT_DIR, COMPARE_NAME),
    path.join(SITE_DATA_DIR, COMPARE_NAME),
  ]) {
    try {
      await fs.access(filePath);
    } catch {
      await fs.writeFile(filePath, compareHeader, "utf8");
    }
  }
}

async function writeOutputs(rows, report) {
  const columns = ["concept_code", "concept_name", "source", "source_url", "updated_at", "status"];
  const csv = "\ufeff" + toCsv(rows, columns);
  const reportJson = JSON.stringify(report, null, 2);
  const targets = [
    [path.join(OUTPUT_DIR, CSV_NAME), csv],
    [path.join(SITE_DATA_DIR, CSV_NAME), csv],
    [path.join(OUTPUT_DIR, REPORT_NAME), reportJson],
    [path.join(SITE_DATA_DIR, REPORT_NAME), reportJson],
  ];
  for (const [filePath, content] of targets) {
    await fs.writeFile(filePath, content, "utf8");
  }
}

async function main() {
  const sourceUrl = process.argv[2] || DEFAULT_SOURCE_URL;
  const updatedAt = nowIso();
  const errors = [];
  let rows = [];

  await ensureOutputFiles();

  try {
    const html = await fetchHtml(sourceUrl);
    rows = parseOptionsFromHtml(html, updatedAt);
    if (!rows.length) {
      rows = await parseWithPlaywright(sourceUrl, updatedAt);
    }
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }

  rows.sort((a, b) => a.concept_name.localeCompare(b.concept_name, "zh-Hant"));
  const report = {
    total_categories: rows.length,
    success: rows.length,
    failed: errors.length,
    updated_at: updatedAt,
    error_messages: errors,
  };

  await writeOutputs(rows, report);

  console.log(`MoneyDJ 概念分類總數：${report.total_categories}`);
  console.log(`成功抓取數：${report.success}`);
  console.log(`失敗數：${report.failed}`);
  console.log(`CSV 輸出位置：${path.join(OUTPUT_DIR, CSV_NAME)}`);
  if (errors.length) {
    console.log(`錯誤訊息：${errors.join("；")}`);
  }

  if (!rows.length) {
    process.exitCode = 1;
  }
}

main();
