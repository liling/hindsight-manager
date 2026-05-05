import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    name: str


class TenantConfigUpdateRequest(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embeddings_provider: str | None = None
    embeddings_model: str | None = None
    embeddings_api_key: str | None = None
    embeddings_base_url: str | None = None
    reranker_provider: str | None = None
    reranker_model: str | None = None
    reranker_api_key: str | None = None


class TenantResponse(BaseModel):
    id: str
    name: str
    schema_name: str
    config: dict | None
    status: str
    created_at: str


def _tenant_response(t: Tenant) -> TenantResponse:
    return TenantResponse(
        id=str(t.id),
        name=t.name,
        schema_name=t.schema_name,
        config=t.config,
        status=t.status.value,
        created_at=str(t.created_at),
    )


async def _require_membership(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
    require_owner: bool = False,
):
    result = await session.execute(
        select(TenantMember, Tenant)
        .join(Tenant, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id, TenantMember.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found or you are not a member")
    membership, tenant = row
    if require_owner and membership.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")
    return membership, tenant


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant, TenantMember.role)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .where(TenantMember.user_id == current_user.id)
    )
    return [_tenant_response(t) for t, role in result.all()]


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    req: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    schema_name = f"tenant_{uuid.uuid4().hex[:8]}"
    tenant = Tenant(name=req.name, schema_name=schema_name, status=TenantStatus.ACTIVE)
    session.add(tenant)
    await session.flush()

    membership = TenantMember(user_id=current_user.id, tenant_id=tenant.id, role=MemberRole.OWNER)
    session.add(membership)
    await session.commit()
    await session.refresh(tenant)
    return _tenant_response(tenant)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await _require_membership(session, current_user, tenant_id)
    return _tenant_response(tenant)


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_config(
    tenant_id: uuid.UUID,
    req: TenantConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await _require_membership(session, current_user, tenant_id, require_owner=True)
    config = tenant.config or {}
    update_data = req.model_dump(exclude_none=True)
    config.update(update_data)
    tenant.config = config
    await session.commit()
    await session.refresh(tenant)
    return _tenant_response(tenant)


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await _require_membership(session, current_user, tenant_id, require_owner=True)
    tenant.status = TenantStatus.DELETING
    await session.commit()
