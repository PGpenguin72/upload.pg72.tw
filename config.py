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

    cf_team_name: str = ""
    cf_aud: str = ""

    # 本機開發用：設 DEV_MODE=true 跳過 Cloudflare Access 驗證
    dev_mode: bool = False

    base_url: str = "https://upload.pg72.tw"
    port: int = 3000

    class Config:
        env_file = ".env"


settings = Settings()
