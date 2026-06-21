"""Business logic for tenant membership management."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User


async def list_members(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[tuple[TenantMember, User]]:
    """Return (member, user) tuples for all members of the tenant."""
    result = await session.execute(
        select(TenantMember, User)
        .join(User, TenantMember.user_id == User.id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    return list(result.all())


async def lookup_user(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    username: str,
) -> tuple[User, bool]:
    """Look up a user by username for membership addition.

    Returns:
        (user, is_already_member)
    Raises:
        HTTPException 404: user not found.
    """
    result = await session.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == target_user.id, TenantMember.tenant_id == tenant_id
        )
    )
    return target_user, existing.scalar_one_or_none() is not None


async def add_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    username: str,
    role: MemberRole,
) -> tuple[User, TenantMember]:
    """Add a member. Returns (user, new_membership).

    Raises:
        HTTPException 404: user not found.
        HTTPException 409: user already a member.
    """
    result = await session.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == target_user.id, TenantMember.tenant_id == tenant_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    member = TenantMember(user_id=target_user.id, tenant_id=tenant_id, role=role)
    session.add(member)
    await session.commit()
    return target_user, member


async def remove_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Delete a membership row. 404 if not found."""
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await session.delete(member)
    await session.commit()


async def update_member_role(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: MemberRole,
) -> tuple[User | None, TenantMember]:
    """Returns (user, member). 404 if member not found."""
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = role
    await session.commit()

    user = await session.get(User, user_id)
    return user, member