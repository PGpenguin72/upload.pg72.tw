from urllib.parse import parse_qs, urlsplit

import httpx
from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet

from config import settings

ROLE_CLAIM = "https://pg72.tw/role"
OIDC_SCOPE = "openid profile email"

# PGID (Better Auth OAuth provider) is only compatible with raw, non
# percent-encoded client credentials. oauth4webapi-style client_secret_basic
# percent-encodes the credentials per RFC 6749 §2.3.1, which PGID rejects.
# client_secret_post carries the credentials as ordinary form body parameters
# and is unambiguous for every secret character set, so it is the client
# authentication method used against PGID here. See docs/pgid-cutover-runbook.md.
TOKEN_ENDPOINT_AUTH_METHOD = "client_secret_post"

_oauth = OAuth()
oidc_client = _oauth.register(
    "pg72_id",
    client_id=settings.oidc_client_id,
    client_secret=settings.oidc_client_secret.get_secret_value(),
    server_metadata_url=(
        f"{settings.oidc_issuer}/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": OIDC_SCOPE,
        "code_challenge_method": "S256",
        "token_endpoint_auth_method": TOKEN_ENDPOINT_AUTH_METHOD,
        "revocation_endpoint_auth_method": TOKEN_ENDPOINT_AUTH_METHOD,
    },
)
_token_cipher = Fernet(
    settings.admin_token_encryption_key.get_secret_value().encode("ascii")
)


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}"


async def load_validated_metadata() -> dict:
    metadata = await oidc_client.load_server_metadata()
    if metadata.get("issuer") != settings.oidc_issuer:
        raise RuntimeError("OIDC discovery issuer mismatch")
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise RuntimeError("OIDC provider does not advertise PKCE S256")
    if metadata.get("authorization_response_iss_parameter_supported") is not True:
        raise RuntimeError("OIDC provider does not advertise authorization response iss")
    if TOKEN_ENDPOINT_AUTH_METHOD not in metadata.get(
        "token_endpoint_auth_methods_supported", []
    ):
        raise RuntimeError(
            f"OIDC provider does not support {TOKEN_ENDPOINT_AUTH_METHOD}"
        )

    for key in (
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "userinfo_endpoint",
    ):
        endpoint = metadata.get(key)
        if not isinstance(endpoint, str) or _origin(endpoint) != settings.oidc_issuer:
            raise RuntimeError(f"OIDC discovery returned an invalid {key}")
    return metadata


async def _fetch_userinfo(endpoint: str, access_token: str) -> dict:
    # Authlib 1.7.2 adds Content-Length: 0 to its signed GET. Use a plain GET so
    # PGID receives an unambiguously bodyless UserInfo request.
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        userinfo = response.json()
    if not isinstance(userinfo, dict):
        raise RuntimeError("OIDC UserInfo response is invalid")
    return userinfo


async def create_authorization_url(
    *, state: str, nonce: str, code_verifier: str
) -> str:
    await load_validated_metadata()
    result = await oidc_client.create_authorization_url(
        f"{settings.base_url}/admin/auth/callback",
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        scope=OIDC_SCOPE,
    )
    if result.get("state") != state:
        raise RuntimeError("OIDC client returned an unexpected state")
    return result["url"]


async def exchange_authorization_code(
    *, code: str, code_verifier: str, nonce: str
) -> tuple[dict, dict]:
    metadata = await load_validated_metadata()
    token = await oidc_client.fetch_access_token(
        redirect_uri=f"{settings.base_url}/admin/auth/callback",
        code=code,
        code_verifier=code_verifier,
    )
    if not token.get("access_token") or not token.get("id_token"):
        raise RuntimeError("OIDC token response is incomplete")
    id_token_claims = await oidc_client.parse_id_token(token, nonce=nonce, leeway=60)
    if id_token_claims is None:
        raise RuntimeError("OIDC ID token is missing")
    userinfo = await _fetch_userinfo(
        metadata["userinfo_endpoint"], token["access_token"]
    )
    if userinfo.get("sub") != id_token_claims.get("sub"):
        raise RuntimeError("OIDC UserInfo subject mismatch")
    if userinfo.get(ROLE_CLAIM) != id_token_claims.get(ROLE_CLAIM):
        raise RuntimeError("OIDC role claim mismatch")
    return dict(token), dict(userinfo)


async def revoke_access_token(access_token: str) -> None:
    metadata = await load_validated_metadata()
    endpoint = metadata.get("revocation_endpoint")
    if not isinstance(endpoint, str) or _origin(endpoint) != settings.oidc_issuer:
        raise RuntimeError("OIDC discovery returned an invalid revocation endpoint")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            endpoint,
            data={
                "token": access_token,
                "token_type_hint": "access_token",
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret.get_secret_value(),
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()


async def create_logout_url(id_token: str, state: str) -> str:
    metadata = await load_validated_metadata()
    endpoint = metadata.get("end_session_endpoint")
    if not isinstance(endpoint, str) or _origin(endpoint) != settings.oidc_issuer:
        raise RuntimeError("OIDC discovery returned an invalid end session endpoint")
    result = await oidc_client.create_logout_url(
        post_logout_redirect_uri=f"{settings.base_url}/admin/logged-out",
        id_token_hint=id_token,
        state=state,
        client_id=settings.oidc_client_id,
    )
    if _origin(result["url"]) != settings.oidc_issuer:
        raise RuntimeError("OIDC client returned an invalid logout URL")
    returned_state = parse_qs(urlsplit(result["url"]).query).get("state", [])
    if returned_state != [state]:
        raise RuntimeError("OIDC client returned an unexpected logout state")
    return result["url"]


def encrypt_token(value: str) -> str:
    return _token_cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_token(value: str) -> str:
    return _token_cipher.decrypt(value.encode("ascii")).decode("utf-8")
