import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.config import Settings
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant_member import MemberRole
from hindsight_manager.platform.client import XinyiPlatformClient
from hindsight_manager.platform.config import PlatformSettings
from hindsight_manager.services import member_service
from hindsight_manager.services.membership import require_membership, require_owner

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["members"])


class AddMemberRequest(BaseModel):
    username: str
    role: MemberRole = MemberRole.MEMBER


class UpdateRoleRequest(BaseModel):
    role: MemberRole


class MemberResponse(BaseModel):
    user_id: str
    username: str | None
    role: str


class MemberLookupResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    email: str | None
    is_already_member: bool


@asynccontextmanager
async def _platform_client():
    ps = PlatformSettings.from_app_settings(Settings())
    client = XinyiPlatformClient(ps)
    try:
        yield client
    finally:
        await client.aclose()


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_membership(session, current_user, tenant_id)
    members = await member_service.list_members(session, tenant_id)
    if not members:
        return []

    user_ids = [m.user_id for m in members]
    async with _platform_client() as client:
        users = await client.batch_get_users(user_ids)

    return [
        MemberResponse(
            user_id=str(m.user_id),
            username=(users.get(m.user_id) or {}).get("username"),
            role=m.role.value,
        )
        for m in members
    ]


@router.get("/members/lookup", response_model=MemberLookupResponse)
async def lookup_member(
    tenant_id: uuid.UUID,
    username: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)

    async with _platform_client() as client:
        user_info = await client.get_user_by_username(username)

    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = uuid.UUID(user_info["id"])
    existing = await member_service.lookup_membership(session, tenant_id, user_id)
    return MemberLookupResponse(
        user_id=str(user_id),
        username=user_info["username"],
        display_name=user_info.get("display_name", ""),
        email=user_info.get("email"),
        is_already_member=existing is not None,
    )


@router.post("/members", response_model=MemberResponse, status_code=201)
async def add_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)

    async with _platform_client() as client:
        user_info = await client.get_user_by_username(req.username)

    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = uuid.UUID(user_info["id"])
    member = await member_service.add_member(session, tenant_id, user_id, req.role)
    return MemberResponse(user_id=str(user_id), username=user_info["username"], role=member.role.value)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    await member_service.remove_member(session, tenant_id, user_id)


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateRoleRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    member = await member_service.update_member_role(session, tenant_id, user_id, req.role)
    return MemberResponse(user_id=str(user_id), username=None, role=member.role.value)
