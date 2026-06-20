import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User

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


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    membership = await session.execute(
        select(TenantMember).where(TenantMember.user_id == current_user.id, TenantMember.tenant_id == tenant_id)
    )
    if not membership.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Not found")

    result = await session.execute(
        select(TenantMember, User)
        .join(User, TenantMember.user_id == User.id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    return [MemberResponse(user_id=str(u.id), username=u.username, role=m.role.value) for m, u in result.all()]


@router.get("/members/lookup", response_model=MemberLookupResponse)
async def lookup_member(
    tenant_id: uuid.UUID,
    username: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == target_user.id, TenantMember.tenant_id == tenant_id
        )
    )
    return MemberLookupResponse(
        user_id=str(target_user.id),
        username=target_user.username,
        display_name=target_user.display_name,
        email=target_user.email,
        is_already_member=existing.scalar_one_or_none() is not None,
    )


@router.post("/members", response_model=MemberResponse, status_code=201)
async def add_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(select(User).where(User.username == req.username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(TenantMember.user_id == target_user.id, TenantMember.tenant_id == tenant_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    member = TenantMember(user_id=target_user.id, tenant_id=tenant_id, role=req.role)
    session.add(member)
    await session.commit()
    return MemberResponse(user_id=str(target_user.id), username=target_user.username, role=req.role.value)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(
        select(TenantMember).where(TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await session.delete(member)
    await session.commit()


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateRoleRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(
        select(TenantMember).where(TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = req.role
    await session.commit()

    target_user = await session.get(User, user_id)
    return MemberResponse(
        user_id=str(user_id),
        username=target_user.username if target_user else "unknown",
        role=req.role.value,
    )
