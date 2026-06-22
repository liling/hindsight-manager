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


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, user: dict | None = Depends(get_current_user_or_none)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str = "",
    user: dict | None = Depends(get_current_user_or_none),
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": error})


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
        {"user": current_user, "tenants": tenants, "dataplane_url": Settings().dataplane_url, "docs_url": Settings().docs_url, "mcp_url": Settings().dataplane_url.rstrip("/") + "/mcp"},
    )


@router.get("/password/change", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    error: str = "",
    message: str = "",
    current_user: dict = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request, "password/change.html",
        {"user": current_user, "error": error, "message": message},
    )


@router.get("/password/forgot", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request,
    error: str = "",
    message: str = "",
):
    return templates.TemplateResponse(
        request, "password/reset.html",
        {"error": error, "message": message, "show_reset_form": False},
    )


@router.get("/password/reset", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    email: str = "",
    error: str = "",
    message: str = "",
):
    show_reset_form = bool(email)
    return templates.TemplateResponse(
        request, "password/reset.html",
        {"error": error, "message": message, "show_reset_form": show_reset_form, "email": email},
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
        {"user": current_user, "api_keys": api_keys},
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request, "profile.html",
        {"user": current_user},
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_users.html", {"user": current_user, "nav_active": "users"})


@router.get("/admin/tenants", response_class=HTMLResponse)
async def admin_tenants_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_tenants.html", {"user": current_user, "nav_active": "tenants"})


@router.get("/admin/api-keys", response_class=HTMLResponse)
async def admin_api_keys_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_api_keys.html", {"user": current_user, "nav_active": "api_keys"})


@router.get("/admin/audit-logs", response_class=HTMLResponse)
async def admin_audit_logs_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_audit_logs.html", {"user": current_user, "nav_active": "audit_logs"})


@router.get("/admin/task-monitor", response_class=HTMLResponse)
async def admin_task_monitor_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_task_monitor.html", {"user": current_user, "nav_active": "task_monitor"})
