import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.services import tenant_service
from hindsight_manager.services.membership import require_membership

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    name: str


class TenantConfigUpdateRequest(BaseModel):
    name: str | None = None
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


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenants = await tenant_service.list_tenants_for_user(session, uuid.UUID(current_user["id"]))
    return [_tenant_response(t) for t in tenants]


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    req: TenantCreateRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant = await tenant_service.create_tenant(session, current_user, req.name)
    return _tenant_response(tenant)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # require_membership 已 join 出 tenant，直接复用——避免二次查询
    _, tenant = await require_membership(session, current_user, tenant_id)
    return _tenant_response(tenant)


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_config(
    tenant_id: uuid.UUID,
    req: TenantConfigUpdateRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await require_membership(session, current_user, tenant_id, require_owner=True)

    update_data = req.model_dump(exclude_none=True)
    name = update_data.pop("name", None)
    tenant = await tenant_service.update_tenant_config(session, tenant, name, update_data)
    return _tenant_response(tenant)


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await require_membership(session, current_user, tenant_id, require_owner=True)
    await tenant_service.mark_tenant_deleting(session, tenant)
