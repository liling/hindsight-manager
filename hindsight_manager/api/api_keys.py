import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.user import User
from hindsight_manager.services import api_key_service
from hindsight_manager.services.membership import require_owner

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str


class UpdateApiKeyRequest(BaseModel):
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


def _fmt_dt(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _api_key_response(k: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(k.id),
        name=k.name,
        key_prefix=k.key_prefix,
        is_system=k.is_system,
        created_at=_fmt_dt(k.created_at),
        last_used_at=_fmt_dt(k.last_used_at),
    )


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    tenant_id: uuid.UUID,
    req: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    api_key, raw_key = await api_key_service.create_api_key(session, tenant_id, req.name)
    return ApiKeyCreatedResponse(
        **_api_key_response(k=api_key).model_dump(),
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    keys = await api_key_service.list_api_keys(session, tenant_id)
    return [_api_key_response(k) for k in keys]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    await api_key_service.revoke_api_key(session, tenant_id, key_id)
    return {"ok": True}


@router.patch("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    req: UpdateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    api_key = await api_key_service.update_api_key_name(session, tenant_id, key_id, req.name)
    return _api_key_response(api_key)
