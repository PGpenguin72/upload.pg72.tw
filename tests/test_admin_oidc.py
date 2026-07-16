import asyncio
import base64
import hashlib
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlencode, urlsplit


os.environ.update(
    {
        "UPLOAD_DIR": "/tmp/pg72-upload-tests-placeholder",
        "TEMP_DIR": "/tmp/pg72-upload-tests-placeholder-temp",
        "RESEND_API_KEY": "re_test_only",
        "ADMIN_EMAIL": "upload-test@pg72.tw",
        "BASE_URL": "https://upload.test",
        "OIDC_ISSUER": "https://sso.test",
        "OIDC_CLIENT_ID": "pg72-upload-test",
        "OIDC_CLIENT_SECRET": "pg72_cs_test_only",
        "OIDC_BOOTSTRAP_ADMIN_SUB": "00000000-0000-4000-8000-000000000072",
        "OIDC_ADMIN_REQUIRED_ROLE": "admin",
        "ADMIN_TOKEN_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"u" * 32).decode(),
    }
)

try:
    import magic  # noqa: F401
except ImportError:
    magic_stub = types.ModuleType("magic")
    magic_stub.from_file = lambda *_args, **_kwargs: "application/octet-stream"
    sys.modules["magic"] = magic_stub

import database
from config import settings
from main import GLOBAL_SECURITY_HEADERS, app, fastapi_app, limiter
from routes import admin, upload
from utils import oidc_client as oidc

from fastapi.testclient import TestClient


ADMIN_SUBJECT = os.environ["OIDC_BOOTSTRAP_ADMIN_SUB"]
ROLE_CLAIM = "https://pg72.tw/role"


class AdminOidcTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_upload_dir = settings.upload_dir
        self.original_temp_dir = settings.temp_dir
        database.DB_PATH = os.path.join(self.temp_dir.name, "upload-test.db")
        settings.upload_dir = os.path.join(self.temp_dir.name, "uploads")
        settings.temp_dir = os.path.join(self.temp_dir.name, "temp")
        database.init_db()
        self.client = TestClient(app, base_url=settings.base_url)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        database.DB_PATH = self.original_db_path
        settings.upload_dir = self.original_upload_dir
        settings.temp_dir = self.original_temp_dir
        self.temp_dir.cleanup()

    def _assert_security_headers(self, response):
        self.assertEqual(
            response.headers["strict-transport-security"],
            "max-age=31536000",
        )
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["x-xss-protection"], "0")
        self.assertEqual(
            response.headers["permissions-policy"],
            "camera=(self), geolocation=(), microphone=(), payment=(), usb=()",
        )
        csp = response.headers["content-security-policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("img-src 'self' data: blob:", csp)
        self.assertIn("media-src 'self' blob:", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        for name in GLOBAL_SECURITY_HEADERS:
            self.assertEqual(
                len(response.headers.get_list(name)),
                1,
                f"duplicate {name} header",
            )

    def test_security_headers_cover_public_admin_api_and_assets(self):
        public_page = self.client.get("/")
        self.assertEqual(public_page.status_code, 200)
        self._assert_security_headers(public_page)

        jsqr = self.client.get("/vendor/jsqr/jsQR-1.4.0.js")
        self.assertEqual(jsqr.status_code, 200)
        self._assert_security_headers(jsqr)

        not_found = self.client.get("/missing")
        self.assertEqual(not_found.status_code, 404)
        self._assert_security_headers(not_found)

        public_api = self.client.post("/api/validate", json={"code": "short"})
        self.assertEqual(public_api.status_code, 400)
        self._assert_security_headers(public_api)
        self.assertEqual(public_api.headers["cache-control"], "no-store")
        self.assertEqual(public_api.headers["pragma"], "no-cache")

        invalid_api = self.client.post("/api/validate", json={})
        self.assertEqual(invalid_api.status_code, 422)
        self._assert_security_headers(invalid_api)
        self.assertEqual(invalid_api.headers["cache-control"], "no-store")
        self.assertEqual(invalid_api.headers["pragma"], "no-cache")

        admin_redirect = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(admin_redirect.status_code, 303)
        self._assert_security_headers(admin_redirect)
        self.assertEqual(admin_redirect.headers["cache-control"], "no-store")
        self.assertEqual(admin_redirect.headers["pragma"], "no-cache")

    def test_security_headers_cover_rate_limit_response(self):
        limiter.reset()
        upload.limiter.reset()
        try:
            responses = [
                self.client.post("/api/validate", json={"code": "short"})
                for _ in range(21)
            ]
        finally:
            limiter.reset()
            upload.limiter.reset()

        limited = responses[-1]
        self.assertEqual(limited.status_code, 429)
        self._assert_security_headers(limited)
        self.assertEqual(limited.headers["cache-control"], "no-store")
        self.assertEqual(limited.headers["pragma"], "no-cache")

    def test_security_headers_cover_unhandled_500s(self):
        limiter.reset()
        upload.limiter.reset()
        client = TestClient(
            app,
            base_url=settings.base_url,
            raise_server_exceptions=False,
        )
        static_app = next(
            route.app
            for route in fastapi_app.routes
            if getattr(route, "name", None) == "static"
        )

        with patch.object(
            static_app,
            "get_response",
            AsyncMock(side_effect=RuntimeError("injected root failure")),
        ):
            root_error = client.get("/")

        with patch.object(
            database,
            "get_code",
            side_effect=RuntimeError("injected api failure"),
        ):
            api_error = client.post(
                "/api/validate",
                json={"code": "ABCDEFGHJKLMNPQR"},
            )

        with patch.object(
            admin,
            "_read_admin_session",
            side_effect=RuntimeError("injected admin failure"),
        ):
            admin_error = client.get("/admin", follow_redirects=False)
        client.close()

        self.assertEqual(root_error.status_code, 500)
        self._assert_security_headers(root_error)
        for response in (api_error, admin_error):
            self.assertEqual(response.status_code, 500)
            self._assert_security_headers(response)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["pragma"], "no-cache")

    def _begin_login(self, next_path=None):
        captured = {}

        async def fake_authorization_url(**kwargs):
            captured.update(kwargs)
            return f"{settings.oidc_issuer}/oauth2/authorize?{urlencode({'state': kwargs['state']})}"

        path = "/admin/login"
        if next_path is not None:
            path += f"?{urlencode({'next': next_path})}"
        with patch.object(admin, "create_authorization_url", fake_authorization_url):
            response = self.client.get(path, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.headers["location"]).netloc, "sso.test")
        cookie_headers = response.headers.get_list("set-cookie")
        self.assertTrue(any("HttpOnly" in header for header in cookie_headers))
        self.assertTrue(any("Secure" in header for header in cookie_headers))
        self.assertTrue(any("SameSite=lax" in header for header in cookie_headers))
        self.assertTrue(any("Path=/admin/auth" in header for header in cookie_headers))
        return captured

    def _complete_login(self, captured, *, claims=None):
        token = {
            "access_token": "pg72_at_test",
            "id_token": "header.payload.signature",
            "expires_at": int(time.time()) + 600,
        }
        if claims is None:
            claims = {
                "sub": ADMIN_SUBJECT,
                "email": "admin@pg72.tw",
                "email_verified": True,
                ROLE_CLAIM: "admin",
            }

        exchange = AsyncMock(return_value=(token, claims))
        callback_query = urlencode(
            {
                "code": "authorization-code",
                "state": captured["state"],
                "iss": settings.oidc_issuer,
            }
        )
        with patch.object(admin, "exchange_authorization_code", exchange):
            response = self.client.get(
                f"/admin/auth/callback?{callback_query}", follow_redirects=False
            )
        return response, exchange

    def _login(self):
        captured = self._begin_login()
        response, exchange = self._complete_login(captured)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")
        exchange.assert_awaited_once_with(
            code="authorization-code",
            code_verifier=captured["code_verifier"],
            nonce=captured["nonce"],
        )
        session_headers = response.headers.get_list("set-cookie")
        self.assertTrue(
            any(settings.admin_cookie_name in header for header in session_headers)
        )
        self.assertTrue(any("Path=/admin" in header for header in session_headers))

    def test_admin_login_csrf_and_logout(self):
        self._login()

        admin_page = self.client.get("/admin")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(
            "frame-ancestors 'none'",
            admin_page.headers["content-security-policy"],
        )

        me = self.client.get("/admin/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "admin@pg72.tw")
        csrf_token = me.json()["csrf_token"]

        no_csrf = self.client.post(
            "/admin/api/codes", headers={"Origin": settings.base_url}
        )
        self.assertEqual(no_csrf.status_code, 403)
        wrong_origin = self.client.post(
            "/admin/api/codes",
            headers={"Origin": "https://attacker.test", "X-CSRF-Token": csrf_token},
        )
        self.assertEqual(wrong_origin.status_code, 403)
        create_code = self.client.post(
            "/admin/api/codes",
            headers={"Origin": settings.base_url, "X-CSRF-Token": csrf_token},
        )
        self.assertEqual(create_code.status_code, 200)
        self.assertEqual(len(create_code.json()["code"]), 16)

        revoke = AsyncMock()

        async def fake_logout_url(id_token, state):
            self.assertEqual(id_token, "header.payload.signature")
            return f"{settings.oidc_issuer}/oauth2/end-session?{urlencode({'state': state})}"

        with (
            patch.object(admin, "revoke_access_token", revoke),
            patch.object(admin, "create_logout_url", fake_logout_url),
        ):
            logout = self.client.post(
                "/admin/logout",
                headers={"Origin": settings.base_url, "X-CSRF-Token": csrf_token},
            )
        self.assertEqual(logout.status_code, 200)
        revoke.assert_awaited_once_with("pg72_at_test")
        self.assertEqual(self.client.get("/admin/api/me").status_code, 401)

        state = parse_qs(urlsplit(logout.json()["logout_url"]).query)["state"][0]
        logged_out = self.client.get(
            f"/admin/logged-out?{urlencode({'state': state})}",
            follow_redirects=False,
        )
        self.assertEqual(logged_out.status_code, 303)
        self.assertEqual(logged_out.headers["location"], "/")
        replay = self.client.get(
            f"/admin/logged-out?{urlencode({'state': state})}",
            follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 400)

    def test_callback_rejects_missing_issuer_and_consumes_state_once(self):
        captured = self._begin_login()
        missing_issuer = self.client.get(
            "/admin/auth/callback?"
            + urlencode({"code": "authorization-code", "state": captured["state"]}),
            follow_redirects=False,
        )
        self.assertEqual(missing_issuer.status_code, 400)

        response, exchange = self._complete_login(captured)
        self.assertEqual(response.status_code, 400)
        exchange.assert_not_awaited()

    def test_callback_rejects_unapproved_subject_and_revokes_token(self):
        captured = self._begin_login()
        claims = {
            "sub": "00000000-0000-4000-8000-000000000999",
            "email": "other@pg72.tw",
            "email_verified": True,
            ROLE_CLAIM: "admin",
        }
        revoke = AsyncMock()
        with patch.object(admin, "revoke_access_token", revoke):
            response, _ = self._complete_login(captured, claims=claims)
        self.assertEqual(response.status_code, 403)
        revoke.assert_awaited_once_with("pg72_at_test")
        self.assertEqual(self.client.get("/admin/api/me").status_code, 401)

    def test_callback_rejects_wrong_role_for_approved_subject(self):
        captured = self._begin_login()
        claims = {
            "sub": ADMIN_SUBJECT,
            "email": "admin@pg72.tw",
            "email_verified": True,
            ROLE_CLAIM: "user",
        }
        revoke = AsyncMock()
        with patch.object(admin, "revoke_access_token", revoke):
            response, _ = self._complete_login(captured, claims=claims)
        self.assertEqual(response.status_code, 403)
        revoke.assert_awaited_once_with("pg72_at_test")
        self.assertEqual(self.client.get("/admin/api/me").status_code, 401)

    def test_external_return_url_is_not_used(self):
        captured = self._begin_login("https://attacker.test/steal")
        response, _ = self._complete_login(captured)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")

    def test_logout_deletes_local_session_when_revocation_fails(self):
        self._login()
        csrf_token = self.client.get("/admin/api/me").json()["csrf_token"]
        revoke = AsyncMock(side_effect=RuntimeError("provider unavailable"))

        async def fake_logout_url(_id_token, state):
            return f"{settings.oidc_issuer}/oauth2/end-session?{urlencode({'state': state})}"

        with (
            patch.object(admin, "revoke_access_token", revoke),
            patch.object(admin, "create_logout_url", fake_logout_url),
        ):
            response = self.client.post(
                "/admin/logout",
                headers={"Origin": settings.base_url, "X-CSRF-Token": csrf_token},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/admin/api/me").status_code, 401)
        self.assertEqual(
            urlsplit(response.json()["logout_url"]).path,
            "/oauth2/end-session",
        )

    def test_public_upload_session_remains_separate_from_admin_session(self):
        code = "ABCDEFGHJKLMNPQR"
        record = database.create_code(code, ttl=600)
        validate = self.client.post("/api/validate", json={"code": code})
        self.assertEqual(validate.status_code, 200)
        upload_token = validate.json()["session_token"]

        initialize = self.client.post(
            "/api/upload/init",
            json={"filename": "public.txt", "filesize": 4, "total_chunks": 1},
            headers={"X-Session-Token": upload_token},
        )
        self.assertEqual(initialize.status_code, 200)
        pending = database.get_pending_upload(initialize.json()["upload_id"])
        self.assertEqual(pending["code_id"], record["id"])
        self.assertEqual(self.client.get("/admin/api/me").status_code, 401)

        database.init_db()
        self.assertEqual(database.get_code(code)["id"], record["id"])
        with database.get_conn() as conn:
            migration_count = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE name = '0001_admin_oidc.sql'"
            ).fetchone()[0]
        self.assertEqual(migration_count, 1)


class OidcClientTests(unittest.TestCase):
    def test_client_authentication_uses_client_secret_post(self):
        # PGID rejects oauth4webapi-style percent-encoded client_secret_basic.
        # The client must authenticate with client_secret_post so credentials
        # travel as ordinary form parameters regardless of secret characters.
        self.assertEqual(oidc.TOKEN_ENDPOINT_AUTH_METHOD, "client_secret_post")
        self.assertEqual(
            oidc.oidc_client.client_kwargs["token_endpoint_auth_method"],
            "client_secret_post",
        )
        self.assertEqual(
            oidc.oidc_client.client_kwargs["revocation_endpoint_auth_method"],
            "client_secret_post",
        )

    def test_client_secret_post_encoder_does_not_over_encode_credentials(self):
        # Regression guard for the Basic vs post compatibility finding: Authlib
        # carries the raw client_id in the body and the transport form-encoder
        # is the only thing that touches reserved characters, which every OAuth
        # server form-decodes. '-' and '_' are unreserved and pass untouched.
        from authlib.oauth2.auth import encode_client_secret_post

        class _Client:
            client_id = "pg72-upload"
            client_secret = "pg72_cs_A-b_C.d"

        _, _, body = encode_client_secret_post(_Client, None, "u", {}, {})
        self.assertIn("client_id=pg72-upload", body)
        self.assertIn("client_secret=pg72_cs_A-b_C.d", body)

    def test_authorization_url_contains_pkce_state_and_nonce(self):
        previous_metadata = dict(oidc.oidc_client.server_metadata)
        verifier = "test-verifier-with-enough-entropy-0123456789-ABCDEFGHIJKLMN"
        state = "state-value"
        nonce = "nonce-value"
        metadata = {
            "_loaded_at": time.time(),
            "issuer": settings.oidc_issuer,
            "authorization_endpoint": f"{settings.oidc_issuer}/oauth2/authorize",
            "token_endpoint": f"{settings.oidc_issuer}/oauth2/token",
            "jwks_uri": f"{settings.oidc_issuer}/.well-known/jwks.json",
            "userinfo_endpoint": f"{settings.oidc_issuer}/oauth2/userinfo",
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
        }
        oidc.oidc_client.server_metadata.clear()
        oidc.oidc_client.server_metadata.update(metadata)
        try:
            url = asyncio.run(
                oidc.create_authorization_url(
                    state=state, nonce=nonce, code_verifier=verifier
                )
            )
        finally:
            oidc.oidc_client.server_metadata.clear()
            oidc.oidc_client.server_metadata.update(previous_metadata)

        query = parse_qs(urlsplit(url).query)
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        self.assertEqual(query["state"], [state])
        self.assertEqual(query["nonce"], [nonce])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["code_challenge"], [expected_challenge])
        self.assertEqual(
            query["redirect_uri"],
            [f"{settings.base_url}/admin/auth/callback"],
        )

    def test_token_exchange_rejects_userinfo_subject_mismatch(self):
        token = {
            "access_token": "pg72_at_test",
            "id_token": "header.payload.signature",
        }
        metadata = AsyncMock(return_value={})
        fetch = AsyncMock(return_value=token)
        parse = AsyncMock(return_value={"sub": ADMIN_SUBJECT, ROLE_CLAIM: "admin"})
        userinfo = AsyncMock(
            return_value={
                "sub": "00000000-0000-4000-8000-000000000999",
                ROLE_CLAIM: "admin",
            }
        )
        with (
            patch.object(oidc, "load_validated_metadata", metadata),
            patch.object(oidc.oidc_client, "fetch_access_token", fetch),
            patch.object(oidc.oidc_client, "parse_id_token", parse),
            patch.object(oidc.oidc_client, "userinfo", userinfo),
        ):
            with self.assertRaisesRegex(RuntimeError, "subject mismatch"):
                asyncio.run(
                    oidc.exchange_authorization_code(
                        code="authorization-code",
                        code_verifier="code-verifier",
                        nonce="nonce",
                    )
                )


if __name__ == "__main__":
    unittest.main()
