import base64
import io

import httpx
import jwt
from cachetools import TTLCache
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

import database
from config import settings
from utils.code_gen import generate_code

import qrcode

router = APIRouter()
_cert_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


# ── Cloudflare Access JWT validation ─────────────────────────────────────────

async def _get_cf_public_keys() -> list[dict]:
    if "keys" in _cert_cache:
        return _cert_cache["keys"]
    url = f"https://{settings.cf_team_name}.cloudflareaccess.com/cdn-cgi/access/certs"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    keys = resp.json()["keys"]
    _cert_cache["keys"] = keys
    return keys


async def require_cf_auth(
    cf_access_jwt_assertion: str | None = Header(default=None),
) -> dict:
    if not cf_access_jwt_assertion:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        keys = await _get_cf_public_keys()
        header = jwt.get_unverified_header(cf_access_jwt_assertion)
        kid = header.get("kid")
        matching = next((k for k in keys if k.get("kid") == kid), None)
        if not matching:
            raise ValueError("No matching public key")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching)
        payload = jwt.decode(
            cf_access_jwt_assertion,
            public_key,
            algorithms=["RS256"],
            audience=settings.cf_aud,
        )
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def admin_page(_: dict = Depends(require_cf_auth)):
    return FileResponse("static/admin.html")


@router.get("/api/me")
async def me(payload: dict = Depends(require_cf_auth)):
    return {"email": payload.get("email", "")}


@router.get("/api/stats")
async def stats(_: dict = Depends(require_cf_auth)):
    return database.get_stats()


@router.get("/api/codes")
async def list_codes(_: dict = Depends(require_cf_auth)):
    return database.list_codes()


@router.post("/api/codes")
async def create_code(_: dict = Depends(require_cf_auth)):
    code = generate_code()
    record = database.create_code(code, ttl=settings.session_ttl_seconds)

    url = f"{settings.base_url}/?code={code}"
    qr_b64 = _make_qr_b64(url)

    return {**record, "url": url, "qr": qr_b64}


@router.get("/api/codes/{code_id}/qr")
async def get_qr(code_id: str, _: dict = Depends(require_cf_auth)):
    record = database.get_code_by_id(code_id)
    if not record:
        raise HTTPException(status_code=404, detail="Code not found")
    url = f"{settings.base_url}/?code={record['code']}"
    return {"url": url, "qr": _make_qr_b64(url), "code": record["code"]}


@router.delete("/api/codes/{code_id}")
async def revoke_code(code_id: str, _: dict = Depends(require_cf_auth)):
    record = database.get_code_by_id(code_id)
    if not record:
        raise HTTPException(status_code=404, detail="Code not found")
    database.revoke_code(code_id)
    return {"ok": True}


@router.get("/api/uploads")
async def list_uploads(_: dict = Depends(require_cf_auth)):
    return database.list_uploads()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_qr_b64(url: str) -> str:
    qr = qrcode.QRCode(version=None, box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#111827", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
