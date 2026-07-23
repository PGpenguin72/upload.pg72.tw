# PGID Admin OIDC Cutover Runbook（Upload）

本 runbook 說明如何把 `upload.pg72.tw` 的 admin 登入切換到 production PGID
（Issuer `https://sso.pg72.tw`）。流程比照 Copy / Link 的切換節奏：先在 PGID
建立 client，再在 VPS 設定 secret 與部署，最後做 origin lockdown、煙霧測試與
rollback 驗證。

適用範圍只有 **admin OIDC 登入**。公開上傳流程（16 字上傳碼 → `X-Session-Token`
→ 分塊上傳）是獨立安全域，不在本次變更範圍，切換過程中不得更動。

> 標記為 **[Owner 親手]** 的步驟必須由專案 owner 在有 PGID 管理權限與 VPS
> shell 的環境親自執行；coding agent 不得代為輸入或產生真實 secret。

---

## 0. 前置條件

- [Owner 親手] 具備 PGID 管理後台權限，可建立 confidential OIDC client。
- [Owner 親手] 具備 `upload.pg72.tw` VPS 的 SSH 權限與 service manager 權限。
- 已確認 production DNS：`upload.pg72.tw` 由 Cloudflare 前置，回源到 VPS 的 Nginx。
- 已閱讀 [`README.md`](../README.md) 的「PGID client 設定」「正式部署」章節與
  [`AGENTS.md`](../AGENTS.md) 的 security invariants。
- 本機驗證已通過（見第 6 節煙霧測試與 `python -m unittest discover -s tests`）。

---

## 1. 在 PGID 建立 client [Owner 親手]

在 PGID 建立一個 confidential web client，欄位精確如下（大小寫、結尾斜線都要一致）：

| 欄位 | 值 |
| --- | --- |
| Client ID | `pg72-upload` |
| Client type | confidential web client（`public = false`） |
| Redirect URI | `https://upload.pg72.tw/admin/auth/callback` |
| Post-logout redirect URI | 不使用；Upload 僅執行本機 logout |
| Grant types | `authorization_code` |
| Response types | `code` |
| Scopes | `openid profile email` |
| Token endpoint auth method | `client_secret_post` |
| Require PKCE (S256) | `true` |
| Enable end session（RP-Initiated Logout） | `false` |
| Skip consent | `false` |

注意事項：

- **Redirect URI 必須精確比對**，不使用 wildcard、不加尾斜線、只允許 `https`。
- **Token endpoint auth method 必須是 `client_secret_post`**。原因見附錄 A：
  Authlib 的 `client_secret_basic` 使用原始（未 percent-encode）拼接，而 PGID
  的 token endpoint 與 oauth4webapi 式 percent-encoded Basic 不相容；改用
  `client_secret_post` 讓憑證以標準 form 參數傳遞，對任何 secret 字元集都明確無歧義。
- Scopes 只要 `openid profile email`。admin 判斷所需的 `role` 由 PGID 以
  namespaced claim `https://pg72.tw/role` 附在 ID Token 與 UserInfo，不需額外 scope。
- `role` claim 名稱固定為 `https://pg72.tw/role`（見 `utils/oidc_client.py` 的
  `ROLE_CLAIM`）。若 PGID 端 role claim 名稱不同，先對齊再切換，不要改應用端常數。

建立後由 PGID 產生 **client secret**。secret 只在下一步寫入 VPS，不進 Git、前端、
log、issue 或聊天訊息。

### 1a. 確認第一位 admin 的 `sub` [Owner 親手]

Upload 以 PGID **不可變 `sub`（UUID，非 email）** 做授權鍵。

- [Owner 親手] 用預定的 admin 帳號登入 PGID，從 profile / token 取得該帳號的 `sub`。
- 記下這個 `sub`，下一步寫入 `OIDC_BOOTSTRAP_ADMIN_SUB`。
- 確認該帳號在 PGID 具有 `admin` role（`https://pg72.tw/role == "admin"`），否則
  callback 會回 403「此 PGID 未獲 Upload 管理權限」。

---

## 2. 在 VPS 設定環境變數與 secret [Owner 親手]

在 VPS 的部署目錄以 `.env.example` 為範本建立 `.env`（`.env` 不進 Git）：

```bash
cp .env.example .env
```

填入下列值（`OIDC_*` 為本 repo 的實際變數名；下方註明對應語意）：

| 變數 | 值 | 說明 |
| --- | --- | --- |
| `OIDC_ISSUER` | `https://sso.pg72.tw` | PGID 精確 HTTPS issuer origin |
| `OIDC_CLIENT_ID` | `pg72-upload` | 第 1 步建立的 client ID |
| `OIDC_CLIENT_SECRET` | *(PGID 產生的真實 secret)* | 只在 VPS `.env`，不進 Git/log |
| `OIDC_BOOTSTRAP_ADMIN_SUB` | *(第 1a 步的 admin `sub`)* | 不可變 UUID，非 email |
| `OIDC_ADMIN_REQUIRED_ROLE` | `admin` | 需與 PGID role claim 相符 |
| `BASE_URL` | `https://upload.pg72.tw` | callback / Origin / QR 用的精確 origin |
| `ADMIN_TOKEN_ENCRYPTION_KEY` | *(見下方產生指令)* | 靜態加密 OIDC token 的 Fernet key |
| `RESEND_API_KEY` | *(真實 Resend key)* | 上傳完成通知，與 SSO 登入無關 |
| `ADMIN_EMAIL` | *(通知收件人)* | 只是通知信收件人，**不授權 admin** |
| `FROM_EMAIL` | `upload@pg72.tw` | 需通過 Resend 驗證的寄件人 |

其餘 TTL / cookie 名稱維持預設即可。

產生 Fernet key（[Owner 親手]，只放進 `.env`）：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Secret 管理原則：

- `OIDC_CLIENT_SECRET`、`ADMIN_TOKEN_ENCRYPTION_KEY`、`RESEND_API_KEY` 都是敏感值，
  只存在於 VPS `.env`，檔案權限限制為 service 帳號可讀（`chmod 600`）。
- 不得把真實 secret 貼進 Git、PR、log、截圖或聊天。`.env.example` 只放假值。

---

## 3. 部署到 VPS / reverse proxy [Owner 親手]

1. 備份現有執行資料（切換前）：

   ```bash
   cp upload_service.db      upload_service.db.bak
   cp upload_service.db-wal  upload_service.db-wal.bak 2>/dev/null || true
   cp upload_service.db-shm  upload_service.db-shm.bak 2>/dev/null || true
   tar czf uploads-backup-$(date +%Y%m%d).tgz uploads/
   ```

2. 取得目標版本原始碼並建立 venv：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

   Linux VPS 需要系統 `libmagic`（`sudo apt-get install libmagic1`）。

3. 用 service manager（systemd 等）在 `127.0.0.1:3000` 執行 `main:app`，
   不要對外直接開 port。啟動後確認 `schema_migrations` 有 `0001_admin_oidc.sql`：

   ```bash
   sqlite3 upload_service.db \
     "SELECT name FROM schema_migrations WHERE name='0001_admin_oidc.sql';"
   ```

   首次啟動會以 `OIDC_BOOTSTRAP_ADMIN_SUB` 對 `admin_identities` 做
   `INSERT OR IGNORE`（見 `README.md` 的 allowlist 章節）。

4. 設定 Nginx 反向代理，直接沿用 [`nginx.conf`](../nginx.conf)：保留
   `proxy_request_buffering off` 與長上傳 timeout；HTTPS 由 Cloudflare 前置。
   應用不讀取任何外部身分 header（Cloudflare Access identity header 一律不信任）。

---

## 4. Origin lockdown 驗證 [Owner 親手]

切換後必須確認 admin 安全邊界成立：

- **精確 Origin**：改變資料的 admin API（建立 / 撤銷上傳碼、logout）要求
  `Origin == https://upload.pg72.tw` 且帶 session-bound `X-CSRF-Token`。
  用錯誤 Origin 或缺 CSRF 應回 403。
  ```bash
  # 缺 CSRF → 403
  curl -si -X POST https://upload.pg72.tw/admin/api/codes \
       -H 'Origin: https://upload.pg72.tw' | head -1
  # 錯誤 Origin → 403
  curl -si -X POST https://upload.pg72.tw/admin/api/codes \
       -H 'Origin: https://attacker.example' -H 'X-CSRF-Token: x' | head -1
  ```
- **Cookie 屬性**：admin session cookie 為 `Secure`、`HttpOnly`、
  `SameSite=Lax`、`Path=/admin`，值為 opaque 隨機字串（DB 只存 SHA-256 hash）。
- **無 dev bypass**：確認沒有跳過 OIDC 的登入路徑（本 repo 已移除 `DEV_MODE`
  與 Cloudflare Access）。未登入存取 `GET /admin` 應 303 轉 `/admin/login`；
  `GET /admin/api/me` 未登入應回 401。
- **不信任身分 header**：即使外部注入身分 header，也不得取得 admin session。
- **callback iss / redirect**：redirect URI 精確、callback 要求 PGID 的
  `iss` 參數等於 `https://sso.pg72.tw`。

---

## 5. 端到端煙霧測試（production）[Owner 親手]

用真實 PGID 帳號跑完整 flow：

1. 瀏覽器開 `https://upload.pg72.tw/admin` → 應轉到 `/admin/login` → 轉到 PGID。
2. 在 PGID 完成登入（Google 或 Passkey）與授權頁（`skipConsent=false`）。
3. 回到 `/admin/auth/callback` 後應成功建立 admin session 並看到 dashboard。
   - 授權帳號（allowlist 內、`admin` role、verified email）→ 成功。
   - 非授權帳號 → 403「此 PGID 未獲 Upload 管理權限」，且 access token 被撤銷。
4. 建立一組上傳碼、顯示 QR、再撤銷該碼，確認 CSRF 正常。
5. 用該上傳碼在無痕視窗跑一次小檔（例如幾 KB）的 init/chunk/complete，確認公開
   上傳流程未受影響、Resend 通知寄達 `ADMIN_EMAIL`。
6. 按 logout：確認本機 session 被刪、access token best-effort 撤銷，瀏覽器只經
   本機 `/admin/logged-out` 導向 `/`，而且既有 PGID session 保持登入。

觀察 log：不得出現 token、secret、authorization code、完整 email/IP 等敏感值。

---

## 6. 本機驗證（切換前先在開發機做過）

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python -m compileall main.py config.py database.py routes utils tests
python -m unittest discover -s tests -v
```

全部測試需通過（含 `test_client_authentication_uses_client_secret_post`）。
另可跑 app import + ASGI lifespan 煙霧測試，確認在假 env 下能啟動與關閉，不需
對外長跑開 port。libmagic 不存在時測試會自動 stub `magic`。

---

## 7. Rollback

若 production 切換後出現無法即時修復的問題：

1. **停用新 client 不改碼的快速回退**：此版本 admin 登入完全依賴 PGID；沒有可用的
   舊登入路徑（Cloudflare Access / `DEV_MODE` 已移除）。因此 rollback = 回到上一個
   可運作的部署版本或維護頁，不是「關掉 OIDC 繼續用」。
2. **回到前一版部署**：用 service manager 切回上一個 release（或上一個 git tag），
   並還原第 3 步備份的 `upload_service.db*`。`0001_admin_oidc.sql` 只新增
   `admin_identities` / `admin_oauth_transactions` / `admin_sessions`，不改原有
   `codes` / `sessions` / `pending_uploads` / `uploads`，公開上傳資料不受影響。
3. **停用個別 admin**：不需 rollback 全站時，把 `admin_identities.is_active` 設為
   `0`，下一個 admin request 會移除該本機 session。
4. **PGID 端**：必要時在 PGID 停用或刪除 `pg72-upload` client；這會讓所有 admin
   登入失敗但不影響公開上傳。
5. **secret 外洩處理**：若 `OIDC_CLIENT_SECRET` 疑似外洩，在 PGID 輪替 secret，
   更新 VPS `.env` 後重啟服務；同時輪替 `ADMIN_TOKEN_ENCRYPTION_KEY` 會使既有
   加密 token 失效（等同強制所有 admin 重新登入）。

---

## 附錄 A：client 認證方式相容性結論（Basic vs post）

**結論：使用 `client_secret_post`。**

實測（本機 Authlib 1.7.2）：

- Authlib 的 `client_secret_basic` 以 `f"{client_id}:{client_secret}"` **原始拼接**
  後 base64（latin1），**不做 percent-encoding**。對 `-`、`_` 這類 RFC 3986
  unreserved 字元，Authlib 與 oauth4webapi 產生的 Basic header **完全相同**；
  也就是說 `pg72-upload` 與典型 `pg72_cs_...` secret 在 Basic 下不會被過度編碼。
- 兩者只在 secret 含 **reserved 字元**（`+`、`/`、`=`、空白等）時才分歧：
  oauth4webapi 依 RFC 6749 §2.3.1 把憑證 form-urlencode 後再 base64
  （例如 `+`→`%2B`、`/`→`%2F`、`=`→`%3D`），Authlib 則原樣送出。
  由於 PGID 的 token endpoint 對 oauth4webapi 式 percent-encoded Basic 不相容
  （代表它做的是原始拆解），Authlib 的原始 Basic 其實與 PGID 相容。
- 儘管如此，本專案選 `client_secret_post`：憑證以標準 form body 參數傳遞，由傳輸層
  form 編碼、伺服器 form 解碼，對任何 secret 字元集都明確、無歧義，直接消除整類
  Basic 編解碼互通風險，也對齊 PGID 建議。

對應程式與測試：

- `utils/oidc_client.py`：`TOKEN_ENDPOINT_AUTH_METHOD = "client_secret_post"`，
  token 與 revocation endpoint 都用 post；revocation 以 body 帶 `client_id` /
  `client_secret`（不再用 HTTP Basic）。
- `load_validated_metadata()` 要求 discovery 的
  `token_endpoint_auth_methods_supported` 含 `client_secret_post`。
- `tests/test_admin_oidc.py`：`test_client_authentication_uses_client_secret_post`
  與 `test_client_secret_post_encoder_does_not_over_encode_credentials` 鎖定此決策。

> 切換時仍須以 production PGID 的實際 discovery 文件確認
> `client_secret_post` 有被 advertise；若 PGID 只宣告 Basic，需在 PGID 端開啟
> post 後再切，不可改回會被過度編碼的 oauth4webapi 式 Basic。
