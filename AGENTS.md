# AGENTS.md

This file applies to the entire repository. Read `README.md` before changing behavior.

## Project in one minute

PG72 Upload is a self-hosted FastAPI file intake service. Administrators authenticate with PGID through OIDC Authorization Code + PKCE. An authorized administrator creates a 16-character time-limited upload code; the public client exchanges that code for a separate upload session and uploads files in 5 MiB chunks. The server assembles chunks into `uploads/`, records metadata in SQLite, and sends an asynchronous Resend notification.

There is no public file download endpoint. The admin UI lists metadata only.

## Start here

1. Copy `.env.example` to `.env` and fill every required value.
2. Register the exact callback and post-logout URIs documented in `README.md` with PGID.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Run `python main.py`. The public page can be viewed over local HTTP; admin OIDC requires HTTPS because its cookies are always `Secure`.

There is intentionally no development authentication bypass.

## Architecture map

| Path | Responsibility |
| --- | --- |
| `main.py` | FastAPI construction, routers, global security headers/CSP, lifespan, hourly cleanup |
| `config.py` | Typed settings and exact HTTPS origin validation |
| `database.py` | Existing upload schema, migrations, admin allowlist, OAuth transactions and sessions |
| `migrations/` | Ordered, idempotently tracked SQLite migrations |
| `routes/upload.py` | Public code validation and authenticated chunk upload lifecycle |
| `routes/admin.py` | OIDC callback, opaque admin session, CSRF, logout and admin APIs |
| `utils/oidc_client.py` | Authlib discovery, PKCE, ID Token/UserInfo validation and token revocation |
| `utils/code_gen.py` | Cryptographically secure 16-character upload code generation |
| `utils/file_handler.py` | Extension sanitization, stored filenames, assembly, MIME lookup, temp cleanup |
| `utils/email_helper.py` | Escaped multipart Resend notification and dangerous MIME warning |
| `static/js/upload.js` | QR scanning, client state, 5 MiB chunking, upload progress |
| `static/js/admin.js` | Dashboard data, CSRF-bearing mutations and logout |
| `nginx.conf` | Production reverse proxy with upload buffering disabled |
| `tests/test_admin_oidc.py` | Disposable SQLite OIDC/admin/upload-isolation tests |

## Data flow and contracts

Public upload flow:

1. `POST /api/validate` checks a 16-character code and creates a UUID upload session token.
2. Every later upload request sends that token as `X-Session-Token`.
3. `POST /api/upload/init` creates a database row and `temp/{upload_id}/`.
4. `PUT /api/upload/{upload_id}/chunk/{index}` writes one numbered chunk.
5. `POST /api/upload/{upload_id}/complete` requires every chunk, assembles the final file, detects MIME, records the upload, deletes pending state, and schedules email.

Admin flow:

1. `/admin/login` stores hashed state plus nonce and PKCE verifier in a short-lived SQLite transaction. The browser receives only an opaque transaction cookie.
2. `/admin/auth/callback` consumes the transaction once and requires the PGID authorization response `iss` parameter.
3. Authlib validates discovery, endpoint origins, PKCE support, ID Token signature/issuer/audience/nonce/time claims, and the UserInfo subject.
4. Authorization requires immutable `sub` membership in `admin_identities`, an active row, verified email, and exact `https://pg72.tw/role` equality with `required_role`.
5. The browser receives an opaque admin cookie; only its SHA-256 hash is stored. Access and ID tokens are encrypted at rest with the configured Fernet key.
6. Unsafe admin requests require both exact same-origin `Origin` and the session-bound `X-CSRF-Token` returned by `/admin/api/me`.
7. `/admin/logout` removes the local session first, best-effort revokes the access token, then returns a local `/admin/logged-out` URL. It does not terminate the PGID session.

Preserve existing public response fields and endpoint paths unless the requested change explicitly includes a migration. Public upload sessions and admin sessions are separate security domains and must never become interchangeable.

## Database and filesystem

The original tables are `codes`, `sessions`, `pending_uploads`, and `uploads`. `migrations/0001_admin_oidc.sql` adds `admin_identities`, `admin_oauth_transactions`, and `admin_sessions`; `schema_migrations` tracks application. The default database is `./upload_service.db`, with WAL and foreign keys enabled per connection.

Runtime data is intentionally ignored by Git:

- `.env`
- `uploads/`
- `temp/`
- `upload_service.db`, `upload_service.db-wal`, and `upload_service.db-shm`

Never delete or rewrite user runtime data during development. Tests must redirect `database.DB_PATH`, `settings.upload_dir`, and `settings.temp_dir` to disposable temporary locations.

## Security invariants

- Never add an auth bypass or trust Cloudflare Access identity headers. The app is its own OIDC relying party.
- Keep `BASE_URL` and `OIDC_ISSUER` as exact HTTPS origins; callback, cookie, CSRF and discovery checks depend on them.
- Do not authorize by email. Use the immutable issuer-scoped PGID `sub` plus the required namespaced role claim.
- Keep state transactions single-use, PKCE S256, nonce verification, authorization-response `iss`, strict discovery endpoint origins, and verified UserInfo `sub`.
- Keep admin cookies `Secure`, `HttpOnly`, `SameSite=Lax`, scoped to `/admin`, random and opaque. Persist only hashes.
- Keep unsafe admin actions protected by exact `Origin` and session-bound CSRF tokens.
- Delete the local admin session even when remote token revocation is unavailable; never log stored tokens or secrets.
- Never trust a client-provided filename as a storage path. Keep generated UUID-based stored names and sanitized extensions.
- Every upload init/chunk/complete call must resolve a live upload session and verify that the pending upload belongs to the same `code_id`.
- Keep file size, chunk size, chunk index, chunk count, and missing-chunk validation on the server.
- Treat MIME detection as informational only. Current dangerous MIME handling warns by email; it is not malware scanning.
- Do not add public access to `uploads/`. A future download route needs explicit authorization, safe response headers, and path traversal protection.
- Keep production Nginx request buffering disabled for chunk uploads.
- Keep browser runtime scripts and fonts self-hosted. A vendored dependency update
  must pin the version, verify the published integrity and bundle hash, retain its
  license/attribution, and update the regression test.
- Treat filenames and MIME strings as untrusted in email. Subjects must be
  single-line, HTML fields escaped, and every notification must include a plain-text
  alternative.

## Coding conventions

- Support Python 3.10 or newer and follow the existing small-module, function-oriented structure.
- Keep route handlers async. Move blocking external calls off the event loop where practical.
- Put SQL in `database.py`, file operations in `utils/file_handler.py`, OIDC protocol operations in `utils/oidc_client.py`, and HTTP behavior in `routes/`.
- Use parameterized SQL for runtime values. Migration filenames are repository-controlled and escaped before recording.
- Use `os.path` consistently unless a scoped refactor deliberately converts the whole touched flow to `pathlib`.
- Keep frontend code dependency-light. Escape untrusted values before inserting them through `innerHTML`.
- Maintain mobile behavior and horizontally scrollable admin tables.
- Add comments only for non-obvious constraints or sequencing.

## Environment settings

Required settings are `RESEND_API_KEY`, `ADMIN_EMAIL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_BOOTSTRAP_ADMIN_SUB`, and `ADMIN_TOKEN_ENCRYPTION_KEY`. `ADMIN_EMAIL` is only the upload notification recipient; it does not grant admin access. See `.env.example` and `README.md` for all defaults and client registration metadata.

When adding a setting:

1. Add a typed field and safe default, if one exists, in `config.py`.
2. Add it to `.env.example` without a real secret.
3. Document it in `README.md`.
4. Update deployment examples and tests that depend on it.

## Verification

At minimum, run:

```bash
python -m compileall main.py config.py database.py routes utils tests
python -m unittest discover -s tests -v
```

The automated suite must use disposable storage and cover:

- Authorization URL state, nonce and S256 PKCE challenge.
- Callback transaction single-use behavior, strict issuer and allowlist rejection.
- Secure opaque session cookie and authenticated `/admin/api/me`.
- Origin plus CSRF enforcement for every mutation, including logout.
- Local logout even if revocation fails, remote token revocation and local cookie deletion.
- Migration idempotency and preservation of existing public code data.
- Public 16-character code and `X-Session-Token` flow without an admin session.

For backend changes, also perform a disposable small-file init/chunk/complete smoke test when system `libmagic` is available. For frontend changes, inspect narrow mobile and desktop widths and confirm long filenames, empty tables and modal content do not overflow.

## Definition of done

- Requested behavior works end to end without weakening security invariants or the public upload contract.
- Error paths return useful status codes and do not leave avoidable temp files or orphaned records.
- New settings and operational steps are reflected in `.env.example`, `README.md`, and this file.
- Syntax checks and relevant automated tests pass against disposable data.
- No secrets, runtime databases, uploaded content, caches, or virtual environments are included in the change.
