# DESIGN-LOG — upload.pg72.tw 視覺統一到 morden_dark

目標:把 `static/` 前端(公開 upload 頁 `index.html` + admin 頁 `admin.html`,共用 `static/css/style.css`)的視覺統一到 `morden_dark`(Linear / Modern)設計語言。**只改視覺,不動 Authlib OIDC / session / CSRF / upload 邏輯與任何後端。**

參考:`/Users/pgpenguin72/sso.pg72.tw/morden_dark.txt`、`docs/design-system.md`。

> 2026-07-17 security follow-up:下方 Inter / JetBrains Mono 記錄保留當時的
> 視覺遷移決策；目前 runtime 已移除 Google Fonts，改用本機 system sans / mono
> stacks，避免瀏覽器向第三方字型服務發出請求。其餘 morden_dark token 與版面
> 決策不變。

## 範圍與邊界

- 可改:`static/css/style.css`、`static/index.html`、`static/admin.html`(僅 `<link>`/`<meta theme-color>`/class 等視覺標記)。
- 不改:`routes/`、`main.py`、`utils/`、`static/js/*`(admin.js / admin_security.js / upload.js 都保持原樣,避免動到 CSRF/OIDC 與被測試鎖定的渲染邏輯)。
- admin 「登入頁」是純 OIDC redirect(`/admin/login` 直接轉址到 IdP),沒有可套版的 HTML;錯誤頁是 `PlainTextResponse`。因此可套版的靜態頁只有 `index.html` 與 `admin.html`。

## 基線

- `./.venv/bin/python -m pytest -q` → 13 passed(視覺改動理論上不影響)。

## Token 對應(舊 → morden_dark)

| 舊 | 新 |
|---|---|
| `--bg #0b0b12` | `--background-base #050506`(+ `--background-deep #020203`、`--background-elevated #0a0a0c`) |
| `--primary #6366f1` | `--accent #5E6AD2` |
| `--primary-h #4f46e5` | `--accent-bright #6872D9` |
| `--primary-glow rgba(99,102,241,.28)` | `--accent-glow rgba(94,106,210,.30)` |
| `--accent #8b5cf6`(紫) | 收斂進單一靛藍家族(morden_dark 為單一飽和靛藍) |
| `--text #e2e8f0` | `--foreground #EDEDEF` |
| `--text-2 #94a3b8` | `--foreground-muted #8A8F98` |
| `--border .07 / .13` | `--border-default .06 / --border-hover .10` |
| body font system-ui | Inter(mono 保留給 code/label) |

舊變數名以 alias 方式保留指向新 token,避免遺漏引用造成回退。

## 步驟紀錄

1. **Scaffold**:新增本 DESIGN-LOG.md,記錄範圍/邊界/token 對應/基線。
2. **style.css 全面遷移**(單一共用樣式檔,index + admin 皆吃):
   - `:root` 收斂為 morden_dark tokens(近黑底、單一靛藍、accent-glow、分層 shadow 變數、`--ease-expo` expo-out),舊變數名保留為 alias 指向新 token。
   - 字體:body 改 **Inter**;code/label/表頭/badge 保留 **JetBrains Mono**(mono 大寫小標,`letter-spacing` 加寬,技術感)。
   - 背景:`body::before` 分層環境光(頂部徑向 + 多顆 accent blob + `ambient-float` 緩動),`body::after` 64px grid overlay(徑向 mask 淡出);admin 版 blob 另組。
   - 卡片:`from-white/.05 → /.02` 玻璃漸層 + 多層陰影(邊框高光 + 擴散暗 + 上緣內高光),hover 加 accent glow。
   - 按鈕:primary 實心 `#5E6AD2` + 多層 accent glow + 上緣內高光 + hover shine sweep + `scale(.98)` active;outline/danger 用 inset 邊 + 微光;全部 expo-out。
   - 輸入:`#0F0F12` 底、`white/.10` 邊、focus accent 邊 + glow ring。
   - Admin:stat-card / table-card 玻璃面 + 陰影 + 頂部 accent 線;表頭與 stat label 轉 mono 大寫;code/status badge、modal 換 accent 家族色與多層陰影。
   - a11y:新增 `:focus-visible` accent outline;新增 `prefers-reduced-motion` 收斂動畫;保留原有 mobile RWD 斷點與觸控尺寸。
3. **HTML**:兩頁 `<meta name="theme-color">` 由 `#0b0b12` → `#050506`(對齊 base 底色)。標記結構、a11y 屬性、JS hook 皆未動。

## 驗證

- `./.venv/bin/python -m pytest -q` → **13 passed**(改動前後一致)。
- 靜態伺服煙霧測試(`python -m http.server` 於 `static/`):`index.html` / `admin.html` / `css/style.css` 皆 `200`;CSS 大括號平衡 153/153;token(`background-base` / `#5E6AD2` / `ambient-float` / reduced-motion)皆存在;`theme-color` = `#050506`。
- 註:完整 FastAPI 啟動在本機因缺系統 `libmagic` 無法 boot(既有環境相依,與本次視覺改動無關);pytest 未觸及該路徑,故不受影響。

## 未動(明確邊界確認)

- `routes/`、`main.py`、`utils/`、`static/js/*`(upload.js / admin.js / admin_security.js)零改動 → Authlib OIDC / session / CSRF / upload 邏輯與被測試鎖定的渲染完全保留。
- admin 登入為 OIDC redirect,無 HTML 可套版;錯誤頁為 `PlainTextResponse`,未觸碰。
</content>
