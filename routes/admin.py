import base64
import hashlib
import io
import logging
import secrets
import time
from urllib.parse import urlsplit

import qrcode
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

import database
from config import settings
from utils.code_gen import generate_code
from utils.oidc_client import (
    ROLE_CLAIM,
    create_authorization_url,
    create_logout_url,
    decrypt_token,
    encrypt_token,
    exchange_authorization_code,
    revoke_access_token,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

OAUTH_COOKIE_NAME = f"{settings.admin_cookie_name}_oauth"
LOGOUT_COOKIE_NAME = f"{settings.admin_cookie_name}_logout"


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_return_to(value: str | None) -> str:
    if not value:
        return "/admin"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return "/admin"
    if parsed.path != "/admin" or parsed.query:
        return "/admin"
    return "/admin"


def _set_cookie(
    response: RedirectResponse | JSONResponse,
    *,
    name: str,
    value: str,
    max_age: int,
    path: str,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _read_admin_session(request: Request) -> dict | None:
    raw_token = request.cookies.get(settings.admin_cookie_name)
    if not raw_token:
        return None
    session = database.get_admin_session(_hash_token(raw_token))
    if not session:
        return None
    if not session["is_active"] or session["role"] != session["required_role"]:
        database.pop_admin_session(session["token_hash"])
        return None
    return session


async def require_admin_session(request: Request) -> dict:
    session = _read_admin_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Admin session required")
    return session


async def require_admin_action(
    request: Request,
    session: dict = Depends(require_admin_session),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict:
    if request.headers.get("origin") != settings.base_url:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    if not x_csrf_token or not secrets.compare_digest(
        x_csrf_token, session["csrf_token"]
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return session


@router.get("")
async def admin_page(request: Request):
    if not _read_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    return FileResponse("static/admin.html")


@router.get("/login")
@limiter.limit("10/minute")
async def login(request: Request, next_path: str | None = Query(default=None, alias="next")):
    if _read_admin_session(request):
        return RedirectResponse(_safe_return_to(next_path), status_code=303)

    handle = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    return_to = _safe_return_to(next_path)
    expires_at = int(time.time()) + settings.admin_oauth_transaction_ttl_seconds
    database.create_admin_oauth_transaction(
        _hash_token(handle),
        _hash_token(state),
        nonce,
        code_verifier,
        return_to,
        expires_at,
    )

    try:
        authorization_url = await create_authorization_url(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )
    except Exception as exc:
        logger.error("OIDC authorization start failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Identity provider unavailable") from exc

    response = RedirectResponse(authorization_url, status_code=302)
    _set_cookie(
        response,
        name=OAUTH_COOKIE_NAME,
        value=handle,
        max_age=settings.admin_oauth_transaction_ttl_seconds,
        path="/admin/auth",
    )
    return response


@router.get("/auth/callback")
@limiter.limit("20/minute")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    iss: str | None = None,
    error: str | None = None,
):
    transaction_handle = request.cookies.get(OAUTH_COOKIE_NAME)
    if not transaction_handle or not state:
        response = PlainTextResponse("登入交易不存在或已過期。", status_code=400)
        response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
        return response
    transaction = database.consume_admin_oauth_transaction(
        _hash_token(transaction_handle), _hash_token(state)
    )
    if not transaction:
        response = PlainTextResponse("登入 state 驗證失敗。", status_code=400)
        response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
        return response
    if error or not code or iss != settings.oidc_issuer:
        response = PlainTextResponse("PG72 ID 登入未完成。", status_code=400)
        response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
        return response

    try:
        token, claims = await exchange_authorization_code(
            code=code,
            code_verifier=transaction["code_verifier"],
            nonce=transaction["nonce"],
        )
    except Exception as exc:
        logger.warning("OIDC callback validation failed: %s", type(exc).__name__)
        response = PlainTextResponse("PG72 ID token 驗證失敗。", status_code=400)
        response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
        return response

    subject = claims.get("sub")
    role = claims.get(ROLE_CLAIM)
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    identity = database.get_admin_identity(subject) if isinstance(subject, str) else None
    if (
        not identity
        or not identity["is_active"]
        or not isinstance(role, str)
        or role != identity["required_role"]
        or not isinstance(email, str)
        or email_verified is not True
    ):
        try:
            await revoke_access_token(token["access_token"])
        except Exception:
            logger.warning("Rejected OIDC token revocation failed")
        response = PlainTextResponse("此 PG72 ID 未獲 Upload 管理權限。", status_code=403)
        response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
        return response

    now = int(time.time())
    oauth_expires_at = int(
        token.get("expires_at") or now + int(token.get("expires_in", 0))
    )
    expires_at = min(now + settings.admin_session_ttl_seconds, oauth_expires_at)
    if expires_at <= now + 30:
        try:
            await revoke_access_token(token["access_token"])
        except Exception:
            logger.warning("Short-lived OIDC token revocation failed")
        response = PlainTextResponse("PG72 ID token 有效期不足。", status_code=400)
        response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
        return response

    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    database.create_admin_session(
        _hash_token(session_token),
        subject,
        email,
        role,
        csrf_token,
        encrypt_token(token["access_token"]),
        encrypt_token(token["id_token"]),
        oauth_expires_at,
        expires_at,
    )

    response = RedirectResponse(transaction["return_to"], status_code=303)
    response.delete_cookie(OAUTH_COOKIE_NAME, path="/admin/auth")
    _set_cookie(
        response,
        name=settings.admin_cookie_name,
        value=session_token,
        max_age=expires_at - now,
        path="/admin",
    )
    return response


@router.get("/logged-out")
async def logged_out(request: Request, state: str | None = None):
    expected_state = request.cookies.get(LOGOUT_COOKIE_NAME)
    if (
        not expected_state
        or not state
        or not secrets.compare_digest(expected_state, state)
    ):
        response = PlainTextResponse("登出 state 驗證失敗。", status_code=400)
        response.delete_cookie(LOGOUT_COOKIE_NAME, path="/admin/logged-out")
        return response
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(LOGOUT_COOKIE_NAME, path="/admin/logged-out")
    return response


@router.post("/logout")
async def logout(session: dict = Depends(require_admin_action)):
    stored_session = database.pop_admin_session(session["token_hash"])
    logout_url = "/"
    logout_state = None
    if stored_session:
        try:
            access_token = decrypt_token(stored_session["access_token_ciphertext"])
            id_token = decrypt_token(stored_session["id_token_ciphertext"])
        except Exception as exc:
            logger.warning("OIDC logout token decryption failed: %s", type(exc).__name__)
        else:
            try:
                await revoke_access_token(access_token)
            except Exception as exc:
                logger.warning("OIDC access token revocation failed: %s", type(exc).__name__)
            try:
                logout_state = secrets.token_urlsafe(32)
                logout_url = await create_logout_url(id_token, logout_state)
            except Exception as exc:
                logout_state = None
                logger.warning("OIDC end-session URL failed: %s", type(exc).__name__)

    response = JSONResponse({"logout_url": logout_url})
    response.delete_cookie(settings.admin_cookie_name, path="/admin")
    if logout_state:
        _set_cookie(
            response,
            name=LOGOUT_COOKIE_NAME,
            value=logout_state,
            max_age=settings.admin_oauth_transaction_ttl_seconds,
            path="/admin/logged-out",
        )
    return response


@router.get("/api/me")
async def me(session: dict = Depends(require_admin_session)):
    return {
        "email": session["email"],
        "role": session["role"],
        "csrf_token": session["csrf_token"],
    }


@router.get("/api/stats")
async def stats(_: dict = Depends(require_admin_session)):
    return database.get_stats()


@router.get("/api/codes")
async def list_codes(_: dict = Depends(require_admin_session)):
    return database.list_codes()


@router.post("/api/codes")
async def create_code(_: dict = Depends(require_admin_action)):
    code = generate_code()
    record = database.create_code(code, ttl=settings.session_ttl_seconds)
    url = f"{settings.base_url}/?code={code}"
    return {**record, "url": url, "qr": _make_qr_b64(url)}


@router.get("/api/codes/{code_id}/qr")
async def get_qr(code_id: str, _: dict = Depends(require_admin_session)):
    record = database.get_code_by_id(code_id)
    if not record:
        raise HTTPException(status_code=404, detail="Code not found")
    url = f"{settings.base_url}/?code={record['code']}"
    return {"url": url, "qr": _make_qr_b64(url), "code": record["code"]}


@router.delete("/api/codes/{code_id}")
async def revoke_code(code_id: str, _: dict = Depends(require_admin_action)):
    record = database.get_code_by_id(code_id)
    if not record:
        raise HTTPException(status_code=404, detail="Code not found")
    database.revoke_code(code_id)
    return {"ok": True}


@router.get("/api/uploads")
async def list_uploads(_: dict = Depends(require_admin_session)):
    return database.list_uploads()


def _make_qr_b64(url: str) -> str:
    qr = qrcode.QRCode(version=None, box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#111827", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
