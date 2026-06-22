import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.audit import record_audit
from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.config import Settings
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember

router = APIRouter(prefix="/admin/api", tags=["admin"])


# ─── Pydantic 模型 ───

class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


class AdminTenantResponse(BaseModel):
    id: str
    name: str
    schema_name: str
    status: str
    config: dict | None
    created_at: str
    member_count: int
    api_key_count: int
    owner_user_id: str | None


class AdminApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_system: bool
    created_at: str
    last_used_at: str | None
    tenant_id: str
    tenant_name: str


# ─── 辅助函数 ───

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_pattern(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _get_client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


# ─── Tenant 管理端点 ───

@router.get("/tenants")
async def list_tenants_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    current_user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(Tenant)
        .where(Tenant.status != TenantStatus.DELETED)
        .order_by(Tenant.created_at.desc())
    )
    count_query = (
        select(func.count())
        .select_from(Tenant)
        .where(Tenant.status != TenantStatus.DELETED)
    )

    if search:
        pattern = _like_pattern(search)
        query = query.where(Tenant.name.ilike(pattern))
        count_query = count_query.where(Tenant.name.ilike(pattern))

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    tenants = result.scalars().all()

    items = []
    for t in tenants:
        mc_result = await session.execute(
            select(func.count()).select_from(TenantMember).where(TenantMember.tenant_id == t.id)
        )
        member_count = mc_result.scalar() or 0

        kc_result = await session.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == t.id)
        )
        api_key_count = kc_result.scalar() or 0

        owner_result = await session.execute(
            select(TenantMember.user_id)
            .where(TenantMember.tenant_id == t.id, TenantMember.role == MemberRole.OWNER)
            .limit(1)
        )
        owner_row = owner_result.first()
        owner_user_id = str(owner_row[0]) if owner_row else None

        items.append(AdminTenantResponse(
            id=str(t.id), name=t.name, schema_name=t.schema_name,
            status=t.status.value, config=t.config, created_at=str(t.created_at),
            member_count=member_count, api_key_count=api_key_count,
            owner_user_id=owner_user_id,
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant_admin(
    tenant_id: uuid.UUID,
    request: Request,
    current_user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    tenant.status = TenantStatus.DELETING
    await record_audit(
        request, session,
        user_id=uuid.UUID(current_user["id"]), action="hm.tenant.delete",
        resource_type="tenant", resource_id=str(tenant_id),
        detail={"name": tenant.name},
    )
    await session.commit()
    return {"ok": True}


TENANT_SCHEMA_PATTERN = re.compile(r"^tenant_[a-f0-9]{8}$")


@router.post("/tenants/{tenant_id}/purge")
async def purge_tenant_admin(
    tenant_id: uuid.UUID,
    request: Request,
    current_user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update()
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    if tenant.status != TenantStatus.DELETING:
        raise HTTPException(
            status_code=409,
            detail=f"租户状态为 {tenant.status.value}，需先软删除后再清空",
        )

    if not TENANT_SCHEMA_PATTERN.match(tenant.schema_name):
        raise HTTPException(
            status_code=500,
            detail="租户 schema 名称异常，拒绝清空",
        )

    exists_result = await session.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"),
        {"name": tenant.schema_name},
    )
    schema_existed = exists_result.fetchone() is not None

    if schema_existed:
        await session.execute(text(f'DROP SCHEMA "{tenant.schema_name}" CASCADE'))

    tenant.status = TenantStatus.DELETED

    await record_audit(
        request, session,
        user_id=uuid.UUID(current_user["id"]),
        action="hm.tenant.purge",
        resource_type="tenant",
        resource_id=str(tenant_id),
        detail={
            "name": tenant.name,
            "schema_name": tenant.schema_name,
            "schema_dropped": schema_existed,
        },
    )
    await session.commit()
    return {"ok": True, "schema_dropped": schema_existed}


# ─── API Key 管理端点 ───

@router.get("/api-keys")
async def list_api_keys_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID | None = Query(None),
    current_user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(ApiKey, Tenant)
        .join(Tenant, ApiKey.tenant_id == Tenant.id)
        .where(Tenant.status == TenantStatus.ACTIVE)
        .order_by(ApiKey.created_at.desc())
    )
    count_query = (
        select(func.count())
        .select_from(ApiKey)
        .join(Tenant, ApiKey.tenant_id == Tenant.id)
        .where(Tenant.status == TenantStatus.ACTIVE)
    )

    if tenant_id:
        query = query.where(ApiKey.tenant_id == tenant_id)
        count_query = count_query.where(ApiKey.tenant_id == tenant_id)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    rows = result.all()

    items = []
    for key, tenant in rows:
        def _fmt(v):
            return v.isoformat() if hasattr(v, "isoformat") else str(v) if v else None
        items.append(AdminApiKeyResponse(
            id=str(key.id), name=key.name, key_prefix=key.key_prefix,
            is_system=key.is_system, created_at=_fmt(key.created_at),
            last_used_at=_fmt(key.last_used_at),
            tenant_id=str(tenant.id), tenant_name=tenant.name,
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("/api-keys/{key_id}")
async def revoke_api_key_admin(
    key_id: uuid.UUID,
    request: Request,
    current_user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    await record_audit(
        request, session,
        user_id=uuid.UUID(current_user["id"]),
        action="hm.api_key.revoke",
        resource_type="api_key", resource_id=str(key_id),
        detail={"name": api_key.name, "tenant_id": str(api_key.tenant_id)},
    )
    await session.delete(api_key)
    await session.commit()
    return {"ok": True}


# ─── Audit logs: redirect to xinyi-platform admin ───

@router.get("/audit-logs")
async def list_audit_logs_redirect(
    current_user: dict = Depends(require_admin),
):
    settings = Settings()
    return RedirectResponse(
        url=f"{settings.platform_url}/admin/audit-logs?client_id=hm-prod",
        status_code=302,
    )
