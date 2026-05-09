from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user, get_current_user_or_none
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import TenantMember
from hindsight_manager.models.user import User

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="hindsight_manager/templates")


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, user: User | None = Depends(get_current_user_or_none)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str = "",
    user: User | None = Depends(get_current_user_or_none),
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant, TenantMember.role)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .where(TenantMember.user_id == current_user.id, Tenant.status == "active")
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
        "dashboard.html",
        {"request": request, "user": current_user, "tenants": tenants},
    )
