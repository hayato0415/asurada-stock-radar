# Codex 專案規則

## 網站架構

- GitHub Pages 正式發布資料夾是 `docs/`。
- 正式首頁入口是 `docs/index.html`。
- 共用 JavaScript 是 `docs/app.js`，各頁透過 `boot("頁面名稱")` 控制渲染。
- 共用樣式是 `docs/app.css`。
- 全股篩選正式主頁是 `docs/radar.html`。
- 概念股資料庫正式主頁是 `docs/concepts.html`，專用程式是 `docs/concepts.js`。
- `docs/latest.html`、`docs/concept-category.html`、`docs/themes.html` 是舊入口相容轉址頁，不得恢復為獨立功能頁。

## 資料權責

- 新聞前台唯一資料源是 `docs/data/news-events.json`。
- 不要新增 `news.js` 或 `news.json`。
- 不要任意修改既有資料格式或建立重複資料源。

## 本機參考檔

- `codex-v2-盤點報告.txt` 僅供本機參考，不得加入 Git 追蹤或提交。

## Git 操作

- 不要自動執行 `git push`。
- 不要自動合併 `main`。
- 提交或推送前必須由使用者明確要求。
