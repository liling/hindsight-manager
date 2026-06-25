from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "manager"
    auth_provider: str = "local"
    cas_server_url: str | None = None
    cas_service_url: str | None = None
    jwt_secret: str
    encryption_key: str = ""
    admin_password: str = ""
    dataplane_url: str = "http://localhost:8888"
    host: str = "0.0.0.0"
    port: int = 8001
    base_url: str = "http://localhost:8001"
    brand_name: str = "Hindsight"
    session_secure: bool = True
    cp_base_domain: str = "cp.local.mem99.cn"
    cp_port: str = "9996"
    cp_scheme: str = "http"
    docs_url: str = "https://hindsight.vectorize.io/best-practices"

    # Email service configuration
    email_service: str = "smtp"  # smtp or sendgrid
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    sendgrid_api_key: str | None = None
    sendgrid_from_email: str | None = None

    # xinyi-platform integration (Plan B)
    platform_url: str = "http://localhost:8000/xinyi"
    oauth_client_id: str = "hm-prod"
    oauth_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8001/hindsight/auth/callback"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 7
    registration_token: str = ""

    model_config = {"env_prefix": "HINDSIGHT_MANAGER_", "env_file": ".env"}

    @model_validator(mode="after")
    def _validate_encryption_key(self) -> "Settings":
        if not self.encryption_key:
            raise ValueError(
                "HINDSIGHT_MANAGER_ENCRYPTION_KEY must be set. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(16))"'
            )
        if len(bytes.fromhex(self.encryption_key)) != 16:
            raise ValueError("HINDSIGHT_MANAGER_ENCRYPTION_KEY must be 16 bytes (32 hex chars)")
        return self

    def cp_url_for_tenant(self, slug: str) -> str:
        return f"{self.cp_scheme}://{slug}.{self.cp_base_domain}:{self.cp_port}"
