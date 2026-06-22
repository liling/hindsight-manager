"""Business logic for tenant membership management.

User info (username, display_name, etc.) is no longer in manager schema.
Callers needing user details must fetch them via XinyiPlatformClient.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.tenant_member import MemberRole, TenantMember


async def list_members(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[TenantMember]:
    """Return TenantMember rows for all members of the tenant."""
    result = await session.execute(
        select(TenantMember).where(TenantMember.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


async def lookup_membership(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TenantMember | None:
    """Return existing membership row for (tenant_id, user_id) or None."""
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()


async def add_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: MemberRole,
) -> TenantMember:
    """Add a member. Caller must resolve user_id via platform_client first.

    Raises:
        HTTPException 409: user is already a member.
    """
    existing = await lookup_membership(session, tenant_id, user_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="User is already a member")

    member = TenantMember(user_id=user_id, tenant_id=tenant_id, role=role)
    session.add(member)
    await session.commit()
    return member


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
) -> TenantMember:
    """Returns updated member. 404 if member not found."""
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
    return member
