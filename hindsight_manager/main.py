from contextlib import asynccontextmanager
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hindsight_manager.api.admin import router as admin_router
from hindsight_manager.api.api_keys import router as api_keys_router
from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.api.captcha import router as captcha_router
from hindsight_manager.api.members import router as members_router
from hindsight_manager.api.pages import router as pages_router
from hindsight_manager.api.password import router as password_router
from hindsight_manager.api.proxy import router as proxy_router
from hindsight_manager.api.tenants import router as tenants_router
from hindsight_manager.api.task_monitor import router as task_monitor_router
from hindsight_manager.auth.password import hash_password
from hindsight_manager.config import Settings
from hindsight_manager.db import init_db

settings = Settings()

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=1)


def _run_migrations() -> None:
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", "hindsight_manager/migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    alembic_cfg.set_main_option("version_table_schema", settings.manager_schema)
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
        hashed = hash_password(settings.admin_password)
        await conn.execute(
            text(
                "INSERT INTO manager.users (id, username, password_hash, display_name, auth_provider, role) "
                "VALUES ('a0000000-0000-0000-0000-000000000001', 'admin', :ph, 'Admin', 'LOCAL', 'ADMIN')"
            ),
            {"ph": hashed},
        )
        await conn.commit()
        logger.info("Default admin user created (username=admin)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_pool, _run_migrations)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    await _ensure_admin_user(engine)
    await engine.dispose()
    init_db(settings)

    # Audit outbox retry scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from hindsight_manager.db import get_session
    from hindsight_manager.platform.client import XinyiPlatformClient
    from hindsight_manager.platform.config import PlatformSettings
    from hindsight_manager.services.audit_outbox_service import audit_retry_once

    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _audit_retry_job():
        ps = PlatformSettings.from_app_settings(settings)
        client = XinyiPlatformClient(ps)
        try:
            async with get_session() as session:
                await audit_retry_once(session, client)
        except Exception as e:
            logger.warning("audit_retry_job failed: %s", e)
        finally:
            await client.aclose()

    scheduler.add_job(_audit_retry_job, "interval", seconds=10,
                      id="audit-retry", replace_existing=True)
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)


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

app.include_router(admin_router)
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(password_router)
app.include_router(tenants_router)
app.include_router(members_router)
app.include_router(api_keys_router)
app.include_router(proxy_router)
app.include_router(task_monitor_router)
app.include_router(captcha_router)
app.mount("/static", StaticFiles(directory="hindsight_manager/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
