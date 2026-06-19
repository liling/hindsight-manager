import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.audit import log_audit
from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.auth.password import hash_password, validate_password_strength, PasswordStrengthError
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.audit_log import AuditLog
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import AuthProvider, User, UserRole

router = APIRouter(prefix="/admin/api", tags=["admin"])


# ─── Pydantic 模型 ───

class AdminUserResponse(BaseModel):
    id: str
    username: str
    email: str | None
    display_name: str
    role: str
    is_active: bool
    auth_provider: str
    created_at: str
    last_login_at: str | None


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    display_name: str
    role: UserRole = UserRole.USER


class AdminUpdateUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


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
    owner: str | None


class AdminApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_system: bool
    created_at: str
    last_used_at: str | None
    tenant_id: str
    tenant_name: str


class AdminAuditLogResponse(BaseModel):
    id: str
    user_id: str | None
    username: str | None
    action: str
    resource_type: str
    resource_id: str
    detail: dict | None
    ip_address: str | None
    created_at: str


# ─── 辅助函数 ───

def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_pattern(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _admin_user_response(u: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=str(u.id),
        username=u.username,
        email=u.email,
        display_name=u.display_name,
        role=u.role.value,
        is_active=u.is_active,
        auth_provider=u.auth_provider.value,
        created_at=str(u.created_at),
        last_login_at=u.last_login_at.isoformat() if hasattr(u.last_login_at, "isoformat") else (str(u.last_login_at) if u.last_login_at else None),
    )


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


# ─── 用户管理端点 ───

@router.get("/users")
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(User).order_by(User.created_at.desc())
    count_query = select(func.count()).select_from(User)

    if search:
        pattern = _like_pattern(search)
        query = query.where(
            (User.username.ilike(pattern)) | (User.email.ilike(pattern))
        )
        count_query = count_query.where(
            (User.username.ilike(pattern)) | (User.email.ilike(pattern))
        )

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await session.execute(query)
    users = result.scalars().all()

    return PaginatedResponse(
        items=[_admin_user_response(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def admin_create_user(
    req: AdminCreateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    try:
        validate_password_strength(req.password)
    except PasswordStrengthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        email=req.email,
        display_name=req.display_name,
        auth_provider=AuthProvider.LOCAL,
        role=req.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    await log_audit(
        session, user_id=current_user.id, action="user.create",
        resource_type="user", resource_id=str(user.id),
        detail={"username": user.username, "role": user.role.value},
        ip_address=_get_client_ip(request),
    )
    await session.commit()

    return _admin_user_response(user)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def admin_update_user(
    user_id: uuid.UUID,
    req: AdminUpdateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    changes = {}
    for field, value in req.model_dump(exclude_none=True).items():
        old_val = getattr(user, field)
        if value != old_val:
            setattr(user, field, value)
            changes[field] = {"old": str(old_val), "new": str(value)}

    await session.commit()
    await session.refresh(user)

    if changes:
        await log_audit(
            session, user_id=current_user.id, action="user.update",
            resource_type="user", resource_id=str(user_id),
            detail=changes, ip_address=_get_client_ip(request),
        )
        await session.commit()

    return _admin_user_response(user)


@router.delete("/users/{user_id}")
async def admin_disable_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="不能禁用自己")

    user.is_active = not user.is_active
    await session.commit()

    action = "user.enable" if user.is_active else "user.disable"
    await log_audit(
        session, user_id=current_user.id, action=action,
        resource_type="user", resource_id=str(user_id),
        ip_address=_get_client_ip(request),
    )
    await session.commit()

    return {"ok": True, "is_active": user.is_active}


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: uuid.UUID,
    req: AdminResetPasswordRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        validate_password_strength(req.new_password)
    except PasswordStrengthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user.password_hash = hash_password(req.new_password)
    await session.commit()

    await log_audit(
        session, user_id=current_user.id, action="user.reset_password",
        resource_type="user", resource_id=str(user_id),
        ip_address=_get_client_ip(request),
    )
    await session.commit()

    return {"ok": True}


# ─── 租户管理端点 ───

@router.get("/tenants")
async def list_tenants_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    current_user: User = Depends(require_admin),
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
        owner_subquery = (
            select(TenantMember.tenant_id)
            .join(User, User.id == TenantMember.user_id)
            .where(
                TenantMember.role == MemberRole.OWNER,
                (User.username.ilike(pattern)) | (User.display_name.ilike(pattern)) | (User.email.ilike(pattern)),
            )
        )
        query = query.where(Tenant.name.ilike(pattern) | Tenant.id.in_(owner_subquery))
        count_query = count_query.where(Tenant.name.ilike(pattern) | Tenant.id.in_(owner_subquery))

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
            select(User.username)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(TenantMember.tenant_id == t.id, TenantMember.role == MemberRole.OWNER)
            .limit(1)
        )
        owner = owner_result.scalar_one_or_none()

        items.append(AdminTenantResponse(
            id=str(t.id), name=t.name, schema_name=t.schema_name,
            status=t.status.value, config=t.config, created_at=str(t.created_at),
            member_count=member_count, api_key_count=api_key_count,
            owner=owner,
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant_admin(
    tenant_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    tenant.status = TenantStatus.DELETING
    await log_audit(
        session, user_id=current_user.id, action="tenant.delete",
        resource_type="tenant", resource_id=str(tenant_id),
        detail={"name": tenant.name}, ip_address=_get_client_ip(request),
    )
    await session.commit()
    return {"ok": True}


TENANT_SCHEMA_PATTERN = re.compile(r"^tenant_[a-f0-9]{8}$")


@router.post("/tenants/{tenant_id}/purge")
async def purge_tenant_admin(
    tenant_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    # SELECT FOR UPDATE 序列化并发 purge
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

    # 防 SQL 注入：schema 名无法参数化，必须白名单校验
    if not TENANT_SCHEMA_PATTERN.match(tenant.schema_name):
        raise HTTPException(
            status_code=500,
            detail="租户 schema 名称异常，拒绝清空",
        )

    # 检查 schema 是否存在（可能从未被懒创建）
    exists_result = await session.execute(
        text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"
        ),
        {"name": tenant.schema_name},
    )
    schema_existed = exists_result.fetchone() is not None

    if schema_existed:
        await session.execute(
            text(f'DROP SCHEMA "{tenant.schema_name}" CASCADE')
        )

    tenant.status = TenantStatus.DELETED

    await log_audit(
        session,
        user_id=current_user.id,
        action="tenant.purge",
        resource_type="tenant",
        resource_id=str(tenant_id),
        detail={
            "name": tenant.name,
            "schema_name": tenant.schema_name,
            "schema_dropped": schema_existed,
        },
        ip_address=_get_client_ip(request),
    )
    await session.commit()
    return {"ok": True, "schema_dropped": schema_existed}


# ─── API Key 管理端点 ───

@router.get("/api-keys")
async def list_api_keys_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID | None = Query(None),
    current_user: User = Depends(require_admin),
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
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    await log_audit(
        session, user_id=current_user.id, action="api_key.revoke",
        resource_type="api_key", resource_id=str(key_id),
        detail={"name": api_key.name, "tenant_id": str(api_key.tenant_id)},
        ip_address=_get_client_ip(request),
    )
    await session.delete(api_key)
    await session.commit()
    return {"ok": True}


# ─── 审计日志端点 ───

@router.get("/audit-logs")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(AuditLog, User).outerjoin(User, AuditLog.user_id == User.id).order_by(AuditLog.created_at.desc())
    count_query = select(func.count()).select_from(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
        count_query = count_query.where(AuditLog.resource_type == resource_type)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    rows = result.all()

    items = []
    for log, user in rows:
        def _fmt(v):
            return v.isoformat() if hasattr(v, "isoformat") else str(v) if v else None
        items.append(AdminAuditLogResponse(
            id=str(log.id), user_id=str(log.user_id) if log.user_id else None,
            username=user.username if user else None,
            action=log.action, resource_type=log.resource_type,
            resource_id=log.resource_id, detail=log.detail,
            ip_address=log.ip_address, created_at=_fmt(log.created_at),
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)
