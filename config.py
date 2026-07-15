from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upload_dir: str = "./uploads"
    temp_dir: str = "./temp"
    max_file_size_bytes: int = 5 * 1024 * 1024 * 1024
    max_chunk_size_bytes: int = 10 * 1024 * 1024

    session_ttl_seconds: int = 3600

    resend_api_key: str
    admin_email: str
    from_email: str = "upload@pg72.tw"

    base_url: str = "https://upload.pg72.tw"
    oidc_issuer: str = "https://sso.pg72.tw"
    oidc_client_id: str
    oidc_client_secret: SecretStr
    oidc_bootstrap_admin_sub: str
    oidc_admin_required_role: str = "admin"
    admin_token_encryption_key: SecretStr
    admin_session_ttl_seconds: int = 900
    admin_oauth_transaction_ttl_seconds: int = 600
    admin_cookie_name: str = "pg72_upload_admin"
    port: int = 3000

    @field_validator("base_url", "oidc_issuer")
    @classmethod
    def validate_exact_origin(cls, value: str) -> str:
        value = value.rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("must be an exact HTTPS origin")
        return value

    @field_validator("oidc_bootstrap_admin_sub", "oidc_admin_required_role")
    @classmethod
    def validate_identity_value(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 255:
            raise ValueError("must contain between 1 and 255 characters")
        return value

    @field_validator("admin_session_ttl_seconds")
    @classmethod
    def validate_admin_session_ttl(cls, value: int) -> int:
        if not 60 <= value <= 86400:
            raise ValueError("must be between 60 and 86400 seconds")
        return value

    @field_validator("admin_oauth_transaction_ttl_seconds")
    @classmethod
    def validate_oauth_transaction_ttl(cls, value: int) -> int:
        if not 60 <= value <= 900:
            raise ValueError("must be between 60 and 900 seconds")
        return value

    class Config:
        env_file = ".env"


settings = Settings()
