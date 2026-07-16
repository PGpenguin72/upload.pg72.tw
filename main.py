import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import database
from config import settings
from routes.admin import router as admin_router
from routes.upload import router as upload_router
from utils.file_handler import cleanup_temp_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()


async def _periodic_cleanup():
    while True:
        await asyncio.sleep(3600)
        database.cleanup_expired()
        cleanup_temp_dirs()


limiter = Limiter(key_func=get_remote_address)

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; object-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; media-src 'self' blob:; "
    "manifest-src 'self'; worker-src 'none'"
)
GLOBAL_SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Permissions-Policy": (
        "camera=(self), geolocation=(), microphone=(), payment=(), usb=()"
    ),
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in GLOBAL_SECURITY_HEADERS.items():
                    headers[name] = value
                if path.startswith(("/admin", "/api")):
                    headers["Cache-Control"] = "no-store"
                    headers["Pragma"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


fastapi_app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
fastapi_app.state.limiter = limiter
fastapi_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
fastapi_app.add_middleware(SlowAPIMiddleware)
fastapi_app.include_router(upload_router, prefix="/api")
fastapi_app.include_router(admin_router, prefix="/admin")

# Static assets — index.html served last so /admin route takes priority
fastapi_app.mount("/", StaticFiles(directory="static", html=True), name="static")

# This wrapper is deliberately outside FastAPI's ServerErrorMiddleware so the
# final unhandled 500 response receives the same policy as ordinary responses.
app = SecurityHeadersMiddleware(fastapi_app)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
