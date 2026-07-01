const DATA_ROOT = "./data/processed/";

export async function fetchJson(fileName) {
  const response = await fetch(`${DATA_ROOT}${fileName}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`讀取資料失敗：${fileName} (${response.status})`);
  }
  return response.json();
}

export async function loadProcessedData(fileNames) {
  const entries = await Promise.all(
    fileNames.map(async (fileName) => {
      try {
        return [fileName, await fetchJson(fileName), null];
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
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.stocks)) return payload.stocks;
  if (Array.isArray(payload?.events)) return payload.events;
  if (Array.isArray(payload?.files)) return payload.files;
  return [];
}
