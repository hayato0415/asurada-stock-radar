# Codex 工程規則

## 適用範圍

本檔適用於整個正式專案。GitHub Pages 發布根目錄為 `docs/`，雷達資料契約記錄在 `DATA_SCHEMA.md`。

## 排版保護

1. 修改前必須先閱讀現有 HTML、`docs/app.js` 與相關 CSS，不可憑空重建。
2. 不可重寫整頁 HTML；只修改需求涉及的區塊。
3. 不可任意修改全站共用 CSS selector。新增樣式應使用頁面專用 class，例如 `radar-*`。
4. 不可打亂既有表格欄位順序，除非使用者明確指定新順序。
5. 不可把桌機表格改成卡片式；桌機應保留表格與水平滑動容器。
6. 手機版調整不得造成整頁水平溢出，也不得破壞桌機表格。
7. 修改資料顯示前先核對 `DATA_SCHEMA.md`，不得顯示 `undefined`、`null` 或 `NaN`。

## 資料與分類

1. 題材 taxonomy 集中在 `docs/js/themeTaxonomy.js`。
2. 雷達池與題材推斷集中在 `docs/js/stockClassifier.js`。
3. 不得在 render table 內散落新的分類關鍵字。
4. 不得為補畫面而編造題材、行情、營收、新聞或技術資料。

## 修改與驗證

1. 修改前執行 `git status -sb`，確認正式 repo 與既有工作樹狀態。
2. 修改後至少執行 JavaScript 語法檢查、`git diff --check` 與本機 HTTP 預覽。
3. 完成回報必須列出修改檔案、驗證結果與 `git diff --stat` 摘要。
4. 工作樹混有無關修改時，必須只 stage 本次檔案，不可直接提交全部內容。
