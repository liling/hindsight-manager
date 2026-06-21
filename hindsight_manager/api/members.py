import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant_member import MemberRole
from hindsight_manager.models.user import User
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
    username: str
    role: str


class MemberLookupResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    email: str | None
    is_already_member: bool


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_membership(session, current_user, tenant_id)
    pairs = await member_service.list_members(session, tenant_id)
    return [MemberResponse(user_id=str(u.id), username=u.username, role=m.role.value) for m, u in pairs]


@router.get("/members/lookup", response_model=MemberLookupResponse)
async def lookup_member(
    tenant_id: uuid.UUID,
    username: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)

    user, is_already_member = await member_service.lookup_user(session, tenant_id, username)
    return MemberLookupResponse(
        user_id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_already_member=is_already_member,
    )


@router.post("/members", response_model=MemberResponse, status_code=201)
async def add_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)

    user, _ = await member_service.add_member(session, tenant_id, req.username, req.role)
    return MemberResponse(user_id=str(user.id), username=user.username, role=req.role.value)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    await member_service.remove_member(session, tenant_id, user_id)


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateRoleRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    user, _ = await member_service.update_member_role(session, tenant_id, user_id, req.role)
    return MemberResponse(
        user_id=str(user_id),
        username=user.username if user else "unknown",
        role=req.role.value,
    )
