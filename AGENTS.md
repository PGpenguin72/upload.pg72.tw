# AGENTS.md

This file applies to the entire repository. Read `README.md` before changing behavior.

## Project in one minute

PG72 Upload is a self-hosted FastAPI file intake service. An administrator authenticates through Cloudflare Access, creates a 16-character time-limited upload code, and shares either the code, a URL, or a QR code. The public client validates the code, receives a session token, and uploads one or more files in 5 MiB chunks. The server assembles the chunks into `uploads/`, records metadata in SQLite, and sends an asynchronous Resend notification.

There is no public file download endpoint. The admin UI lists metadata only.

## Start here

1. Copy `.env.example` to `.env` and fill the required values.
2. For local-only development, set `DEV_MODE=true` so `/admin` does not require a real Cloudflare Access JWT.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Run `python main.py` and open `http://127.0.0.1:3000/` or `/admin`.

Never use `DEV_MODE=true` in a public or production environment.

## Architecture map

| Path | Responsibility |
| --- | --- |
| `main.py` | FastAPI construction, routers, static mount, lifespan, hourly cleanup |
| `config.py` | Pydantic settings loaded from environment and `.env` |
| `database.py` | SQLite schema and all current database queries |
| `routes/upload.py` | Public code validation and authenticated chunk upload lifecycle |
| `routes/admin.py` | Cloudflare Access JWT validation and admin APIs |
| `utils/code_gen.py` | Cryptographically secure 16-character upload code generation |
| `utils/file_handler.py` | Extension sanitization, stored filenames, assembly, MIME lookup, temp cleanup |
| `utils/email_helper.py` | Resend upload notification and dangerous MIME warning |
| `static/index.html` | Public upload UI and social metadata |
| `static/admin.html` | Admin dashboard markup |
| `static/js/upload.js` | QR scanning, client state, 5 MiB chunking, upload progress |
| `static/js/admin.js` | Dashboard data, code creation/revocation, QR modal |
| `static/css/style.css` | Shared visual system and mobile layout |
| `nginx.conf` | Production reverse-proxy example and Access header forwarding |

## Data flow and contracts

Public upload flow:

1. `POST /api/validate` checks a 16-character code and creates a UUID session token.
2. Every later upload request sends that token as `X-Session-Token`.
3. `POST /api/upload/init` creates a database row and `temp/{upload_id}/`.
4. `PUT /api/upload/{upload_id}/chunk/{index}` writes one numbered chunk.
5. `POST /api/upload/{upload_id}/complete` requires every chunk, assembles the final file, detects MIME, records the upload, deletes pending state, and schedules the email.

Admin flow:

1. Cloudflare sends `Cf-Access-Jwt-Assertion` through Nginx.
2. `require_cf_auth()` fetches and caches Cloudflare public keys, verifies RS256 and `CF_AUD`, and exposes the payload.
3. Admin APIs create/revoke codes, generate QR images, and read stats/upload metadata.

Preserve existing response fields and endpoint paths unless the requested change includes a migration. The frontend calls these APIs directly without a generated client.

## Database and filesystem

`database.init_db()` creates four tables: `codes`, `sessions`, `pending_uploads`, and `uploads`. The database path is currently fixed at `./upload_service.db`. SQLite uses WAL mode and foreign keys on each connection.

Runtime data is intentionally ignored by Git:

- `.env`
- `uploads/`
- `temp/`
- `upload_service.db`, `upload_service.db-wal`, and `upload_service.db-shm`

Do not delete or rewrite user runtime data during development. Use temporary directories or a disposable working copy for destructive tests.

## Security invariants

- Never weaken `require_cf_auth()` or enable the `DEV_MODE` bypass by default.
- Never trust a client-provided filename as a storage path. Keep generated UUID-based stored names and sanitized extensions.
- Every upload init/chunk/complete call must resolve a live session and verify that the pending upload belongs to the same `code_id`.
- Keep file size, chunk size, chunk index, chunk count, and missing-chunk validation on the server.
- Keep secrets out of source, HTML, logs, fixtures, screenshots, and commits.
- Treat MIME detection as informational only. Current dangerous MIME handling warns by email; it is not malware scanning.
- Do not add public access to `uploads/`. A future download route needs explicit authorization, safe response headers, and path traversal protection.
- Keep production Nginx request buffering disabled for chunk uploads and forward `Cf-Access-Jwt-Assertion` unchanged.

## Coding conventions

- Support Python 3.10 or newer and follow the existing small-module, function-oriented structure.
- Keep route handlers async. Move blocking external calls off the event loop, as the Resend call currently does with `asyncio.to_thread()`.
- Put SQL in `database.py`, file operations in `utils/file_handler.py`, and HTTP behavior in `routes/`.
- Use parameterized SQL only.
- Use `os.path` consistently unless a scoped refactor deliberately converts the whole touched flow to `pathlib`.
- Keep frontend code dependency-light. The current UI uses native HTML/CSS/JavaScript plus jsQR from a CDN.
- Escape untrusted text before inserting it through `innerHTML`; `original_filename` is user-controlled.
- Maintain mobile behavior for the public page and horizontally scrollable admin tables.
- Add comments only for non-obvious constraints or sequencing.

## Environment settings

Required by `config.py`: `RESEND_API_KEY` and `ADMIN_EMAIL`.

Production admin auth also requires `CF_TEAM_NAME` and `CF_AUD`. `FROM_EMAIL` must be a sender accepted by the configured Resend account. `BASE_URL` controls links encoded into generated QR images. See `.env.example` and the README table for defaults.

When adding a setting:

1. Add a typed field and safe default, if one exists, in `config.py`.
2. Add it to `.env.example` without a real secret.
3. Document it in `README.md`.
4. Update all deployment examples that depend on it.

## UI and OG assets

Keep the visual language consistent with `static/css/style.css`. Reuse the existing upload icon shape rather than introducing a second logo system.

`static/og-preview.svg` is the editable source for `static/og-preview.png`. Social metadata intentionally points to the absolute production PNG URL. After changing the source, regenerate and verify the raster:

```bash
magick -background none static/og-preview.svg static/og-preview.png
magick identify static/og-preview.png
```

The output must remain exactly 1200 x 630, with readable text inside the safe area. If the deployment hostname changes, update canonical, Open Graph, and Twitter image URLs in `static/index.html`, plus `BASE_URL`.

## Verification

There is no automated test suite yet. At minimum, run:

```bash
python -m compileall main.py config.py database.py routes utils
```

For backend or upload changes, also perform a disposable local smoke test with `DEV_MODE=true`:

- App starts and serves `/` and `/admin`.
- Admin can create a code and receive a QR payload.
- A code validates and returns a session token.
- A small file completes through init, chunk, and complete.
- A revoked or expired code cannot create or continue a session.
- A pending upload cannot be accessed with a session for another code.
- The completed file size and recorded metadata are correct.

For frontend changes, check at narrow mobile and desktop widths. Confirm long filenames, multiple files, progress states, QR camera denial, empty tables, and modal text do not overflow.

For social metadata changes, verify that all image URLs are absolute, the PNG exists, and its dimensions are 1200 x 630.

## Definition of done

- The requested behavior works end to end without weakening the security invariants.
- Error paths return useful HTTP status codes and do not leave avoidable temp files or orphaned records.
- New settings and operational steps are reflected in `.env.example`, `README.md`, and this file when relevant.
- Python syntax checks pass and relevant manual smoke tests are reported.
- No secrets, runtime databases, uploaded content, caches, or virtual environments are included in the change.
