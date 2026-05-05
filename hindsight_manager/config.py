from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "manager"
    auth_provider: str = "local"
    cas_server_url: str | None = None
    cas_service_url: str | None = None
    jwt_secret: str
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {"env_prefix": "HINDSIGHT_MANAGER_"}
