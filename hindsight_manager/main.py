from contextlib import asynccontextmanager
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from alembic import command
from alembic.config import Config as AlembicConfig
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hindsight_manager.api.admin import router as admin_router
from hindsight_manager.api.api_keys import router as api_keys_router
from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.api.members import router as members_router
from hindsight_manager.api.pages import router as pages_router
from hindsight_manager.api.proxy import router as proxy_router
from hindsight_manager.api.tenants import router as tenants_router
from hindsight_manager.api.task_monitor import router as task_monitor_router
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
    """Admin user is now seeded by xinyi-platform. This function is a no-op stub kept
    for backwards-compatibility with any deployment scripts that call it."""
    return


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
            session_gen = get_session()
            try:
                session = await session_gen.__anext__()
                try:
                    await audit_retry_once(session, client)
                finally:
                    await session_gen.aclose()
            except StopAsyncIteration:
                pass
        except Exception as e:
            logger.warning("audit_retry_job failed: %s", e)
        finally:
            await client.aclose()

    scheduler.add_job(_audit_retry_job, "interval", seconds=10,
                      id="audit-retry", replace_existing=True)

    # Auto-registration + service discovery
    from xinyi_platform.ui_common.service_discovery import (
        derive_client_secret,
        register_self,
        fetch_active_clients,
        build_product_list,
    )

    if settings.registration_token:
        # Derive client_secret from registration token
        settings.oauth_client_secret = derive_client_secret(
            settings.registration_token,
            settings.oauth_client_id,
        )

        # Register with platform
        await register_self(
            platform_url=settings.platform_url,
            registration_token=settings.registration_token,
            client_metadata={
                "client_id": settings.oauth_client_id,
                "name": "Hindsight",
                "base_url": f"{settings.base_url}/hindsight",
                "redirect_uris": ["/auth/callback"],
                "logout_url": "/auth/logout",
                "home_path": "/dashboard",
                "description": "RAG 记忆库",
            },
        )

    # Fetch active clients and populate product switcher
    if settings.registration_token:
        active = await fetch_active_clients(
            settings.platform_url,
            settings.oauth_client_id,
            settings.oauth_client_secret,
        )
        if app.state.ui:
            app.state.ui["products"] = build_product_list(
                active,
                platform_url=settings.platform_url,
                self_client_id=settings.oauth_client_id,
                self_name="Hindsight",
                self_home_path="/dashboard",
            )

        async def _refresh_products():
            active = await fetch_active_clients(
                settings.platform_url,
                settings.oauth_client_id,
                settings.oauth_client_secret,
            )
            if app.state.ui:
                app.state.ui["products"] = build_product_list(
                    active,
                    platform_url=settings.platform_url,
                    self_client_id=settings.oauth_client_id,
                    self_name="Hindsight",
                    self_home_path="/dashboard",
                )

        scheduler.add_job(_refresh_products, "interval", minutes=5, id="refresh-products", replace_existing=True)

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

async def _page_auth_redirect(request: Request, exc: HTTPException):
    if exc.status_code == 401 and request.url.path.startswith("/hindsight/") and not request.url.path.startswith(
        ("/hindsight/api/", "/hindsight/auth/", "/hindsight/health")
    ):
        return RedirectResponse(
            url=f"/hindsight/auth/login-redirect?return_to={quote(request.url.path)}",
            status_code=302,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.add_exception_handler(HTTPException, _page_auth_redirect)


# Wire shared UI (templates loader, static mount, jinja globals).
from xinyi_platform.ui_common import install_ui  # noqa: E402



HM_NAV_MENU = [
    {
        "label": "记忆库",
        "items": [
            {"id": "dashboard", "label": "记忆库", "href": "/hindsight/dashboard"},
        ],
    },
    {
        "label": "管理",
        "require_admin": True,
        "items": [
            {"id": "tenants",      "label": "租户管理",    "href": "/hindsight/admin/tenants"},
            {"id": "api_keys",     "label": "API Key 管理", "href": "/hindsight/admin/api-keys"},
            {"id": "task_monitor", "label": "任务监控",    "href": "/hindsight/admin/task-monitor"},
        ],
    },
]

install_ui(
    app,
    current_service="hindsight-manager",
    nav_menu=HM_NAV_MENU,
    brand=settings.brand_name,
    platform_url=settings.platform_url,
    service_prefix="/hindsight",
)

app.include_router(admin_router, prefix="/hindsight")
app.include_router(pages_router, prefix="/hindsight")
app.include_router(auth_router, prefix="/hindsight")
app.include_router(tenants_router, prefix="/hindsight")
app.include_router(members_router, prefix="/hindsight")
app.include_router(api_keys_router, prefix="/hindsight")
app.include_router(proxy_router, prefix="/hindsight")
app.include_router(task_monitor_router, prefix="/hindsight")
app.mount("/hindsight/static", StaticFiles(directory="hindsight_manager/static"), name="static")


@app.get("/hindsight/health")
async def health():
    return {"status": "ok"}
