import secrets
import uuid
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["api-keys"])

KEY_PREFIX = "hsm_"


def _generate_api_key() -> tuple[str, str]:
    raw = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw, sha256(raw.encode()).hexdigest()


async def _require_owner(session: AsyncSession, user: User, tenant_id: uuid.UUID) -> Tenant:
    result = await session.execute(
        select(TenantMember, Tenant)
        .join(Tenant, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id, TenantMember.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    membership, tenant = row
    if membership.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")
    return tenant


class CreateApiKeyRequest(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_system: bool
    created_at: str
    last_used_at: str | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    tenant_id: uuid.UUID,
    req: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    raw_key, key_hash = _generate_api_key()
    api_key = ApiKey(tenant_id=tenant_id, key_hash=key_hash, key_prefix=raw_key[:16], name=req.name)
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    return ApiKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        is_system=False,
        created_at=api_key.created_at.isoformat(),
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)
    result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.is_system.desc(), ApiKey.created_at.desc())
    )
    return [
        ApiKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            is_system=k.is_system,
            created_at=k.created_at.isoformat(),
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        )
        for k in result.scalars().all()
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    await session.delete(api_key)
    await session.commit()
    return {"ok": True}
