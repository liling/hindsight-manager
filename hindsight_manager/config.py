from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "manager"
    auth_provider: str = "local"
    cas_server_url: str | None = None
    cas_service_url: str | None = None
    jwt_secret: str
    encryption_key: str = "0123456789abcdef0123456789abcdef"
    admin_password: str = ""
    dataplane_url: str = "http://localhost:8888"
    host: str = "0.0.0.0"
    port: int = 8001
    base_url: str = "http://localhost:8001"
    cp_base_domain: str = "cp.local.mem99.cn"
    cp_port: str = "9996"
    cp_scheme: str = "http"

    model_config = {"env_prefix": "HINDSIGHT_MANAGER_"}

    def cp_url_for_tenant(self, slug: str) -> str:
        return f"{self.cp_scheme}://{slug}.{self.cp_base_domain}:{self.cp_port}"
