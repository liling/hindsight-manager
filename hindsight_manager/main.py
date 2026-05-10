from contextlib import asynccontextmanager
import logging

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from passlib.hash import bcrypt as passlib_bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hindsight_manager.api.api_keys import router as api_keys_router
from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.api.members import router as members_router
from hindsight_manager.api.pages import router as pages_router
from hindsight_manager.api.proxy import router as proxy_router
from hindsight_manager.api.tenants import router as tenants_router
from hindsight_manager.config import Settings
from hindsight_manager.db import init_db

settings = Settings()

logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", "hindsight_manager/migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied")


async def _ensure_admin_user(engine: AsyncEngine) -> None:
    if not settings.admin_password:
        return
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM manager.users WHERE username = 'admin'")
        )
        if result.fetchone():
            return
        hashed = passlib_bcrypt.using(rounds=12).hash(settings.admin_password)
        await conn.execute(
            text(
                "INSERT INTO manager.users (id, username, password_hash, display_name, auth_provider) "
                "VALUES ('a0000000-0000-0000-0000-000000000001', 'admin', :ph, 'Admin', 'local')"
            ),
            {"ph": hashed},
        )
        await conn.commit()
        logger.info("Default admin user created (username=admin)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    await _ensure_admin_user(engine)
    await engine.dispose()
    init_db(settings)
    yield


app = FastAPI(title="Hindsight Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.base_url,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(members_router)
app.include_router(api_keys_router)
app.include_router(proxy_router)
app.mount("/static", StaticFiles(directory="hindsight_manager/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
