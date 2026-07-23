const DATA_ROOT = "./data/processed/";
const SITE_META_PATH = "./data/site_meta.json";
const DEFAULT_FETCH_TIMEOUT_MS = 15000;

let siteMetaPromise = null;

function addVersion(path, version) {
  const joiner = path.includes("?") ? "&" : "?";
  return `${path}${joiner}v=${encodeURIComponent(version || Date.now())}`;
}

async function fetchWithTimeout(path, timeoutMs = DEFAULT_FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(path, { cache: "no-store", signal: controller.signal });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`資料讀取逾時：${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function loadSiteMeta() {
  if (!siteMetaPromise) {
    siteMetaPromise = fetchWithTimeout(addVersion(SITE_META_PATH, Date.now()))
      .then((response) => {
        if (!response.ok) {
          throw new Error(`site_meta.json HTTP ${response.status}`);
        }
        return response.json();
      })
      .catch((error) => {
        console.warn("Site meta not available; falling back to timestamp cache busting.", error);
        return null;
      });
  }
  return siteMetaPromise;
}

export function getDataVersion(meta) {
  return meta?.data_version || meta?.run_id || Date.now();
}

export async function fetchJsonPath(path, options = {}) {
  const meta = options.meta === undefined ? await loadSiteMeta() : options.meta;
  const timeoutMs = Number(options.timeoutMs || DEFAULT_FETCH_TIMEOUT_MS);
  const response = await fetchWithTimeout(addVersion(path, getDataVersion(meta)), timeoutMs);
  if (!response.ok) {
    throw new Error(`資料讀取失敗：${path} (${response.status})`);
  }
  return response.json();
}

export async function fetchJson(fileName) {
  return fetchJsonPath(`${DATA_ROOT}${fileName}`);
}

export async function loadProcessedData(fileNames) {
  const meta = await loadSiteMeta();
  const entries = await Promise.all(
    fileNames.map(async (fileName) => {
      try {
        return [fileName, await fetchJsonPath(`${DATA_ROOT}${fileName}`, { meta }), null];
      } catch (error) {
        return [fileName, null, error];
      }
    })
  );

  return entries.reduce((acc, [fileName, data, error]) => {
    acc[fileName] = { data, error };
    return acc;
  }, {});
}

export function getItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of ["items", "data", "scores", "stocks", "rows", "rankings", "events", "files"]) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}
