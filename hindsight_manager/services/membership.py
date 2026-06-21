"""Shared membership / ownership checks for tenant-scoped endpoints."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User


async def require_membership(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
    require_owner: bool = False,
) -> tuple[TenantMember, Tenant]:
    """Return (membership, tenant) for the user on this tenant.

    Raises:
        HTTPException 404: user is not a member of the tenant.
        HTTPException 403: require_owner=True and user is not OWNER.
    """
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


async def require_owner(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
) -> Tenant:
    """Convenience wrapper returning only the tenant (callers usually
    don't need the membership row)."""
    _, tenant = await require_membership(session, user, tenant_id, require_owner=True)
    return tenant
