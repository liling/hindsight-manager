import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user, get_current_user_or_none, require_admin
from hindsight_manager.config import Settings
from hindsight_manager.db import get_session
from hindsight_manager.jinja_filters import make_templates
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import TenantMember

router = APIRouter(tags=["pages"])
templates = make_templates()


def _ui_ctx(request: Request) -> dict:
    """Pull ui_common state from app.state for template rendering."""
    ui = request.app.state.ui
    return {
        "current_service": ui["current_service"],
        "nav_menu": ui["nav_menu"],
        "brand": ui["brand"],
        "products": ui["products"],
        "platform_url": ui["platform_url"],
        "manager_url": ui["manager_url"],
        "service_prefix": ui.get("service_prefix", ""),
    }


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, user: dict | None = Depends(get_current_user_or_none)):
    if user:
        return RedirectResponse(url="/hindsight/dashboard", status_code=302)
    return RedirectResponse(url="/hindsight/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    return_to: str = "/hindsight/dashboard",
    error: str = "",
    user: dict | None = Depends(get_current_user_or_none),
):
    # Login is now handled by xinyi-platform. Redirect to the platform's
    # OAuth2 authorize endpoint (this endpoint should rarely be hit since
    # unauthenticated HM requests redirect to /auth/login-redirect).
    from fastapi.responses import RedirectResponse
    from hindsight_manager.config import Settings
    from urllib.parse import urlencode
    from hindsight_manager.auth.oauth_state import generate_oauth_state, sign_oauth_state

    settings = Settings()
    state = generate_oauth_state()
    sig = sign_oauth_state(state, settings.jwt_secret)
    params = {
        "response_type": "code",
        "client_id": settings.oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "state": sig,
        "return_to": return_to,
    }
    url = f"{settings.platform_url}/oauth/authorize?{urlencode(params)}"
    resp = RedirectResponse(url=url, status_code=303)
    resp.set_cookie("hm_oauth_state", sig, httponly=True, max_age=600, path="/auth", samesite="lax")
    return resp


@router.api_route("/dashboard", methods=["GET", "POST"], response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant, TenantMember.role)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .where(TenantMember.user_id == uuid.UUID(current_user["id"]), Tenant.status == "active")
    )
    tenants = [
        {
            "id": str(t.id),
            "name": t.name,
            "schema_name": t.schema_name,
            "role": role.value if hasattr(role, "value") else str(role),
        }
        for t, role in result.all()
    ]
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            **_ui_ctx(request),
            "current_user": current_user,
            "tenants": tenants,
            "dataplane_url": Settings().dataplane_url,
            "docs_url": Settings().docs_url,
            "mcp_url": Settings().dataplane_url.rstrip("/") + "/mcp",
        },
    )


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant, TenantMember.role, ApiKey)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .join(ApiKey, ApiKey.tenant_id == Tenant.id)
        .where(TenantMember.user_id == uuid.UUID(current_user["id"]))
    )
    api_keys = [
        {
            "id": str(key.id),
            "key_prefix": key.key_prefix,
            "name": key.name,
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "created_at": str(key.created_at),
            "last_used_at": str(key.last_used_at) if key.last_used_at else "Never",
            "is_system": key.is_system,
        }
        for tenant, role, key in result.all()
    ]
    return templates.TemplateResponse(
        request, "api_keys.html",
        {
            **_ui_ctx(request),
            "current_user": current_user,
            "api_keys": api_keys,
        },
    )


@router.get("/admin/tenants", response_class=HTMLResponse)
async def admin_tenants_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(
        request, "admin_tenants.html",
        {**_ui_ctx(request), "current_user": current_user},
    )


@router.get("/admin/api-keys", response_class=HTMLResponse)
async def admin_api_keys_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(
        request, "admin_api_keys.html",
        {**_ui_ctx(request), "current_user": current_user},
    )


@router.get("/admin/task-monitor", response_class=HTMLResponse)
async def admin_task_monitor_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(
        request, "admin_task_monitor.html",
        {**_ui_ctx(request), "current_user": current_user},
    )
