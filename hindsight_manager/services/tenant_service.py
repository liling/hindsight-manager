"""Business logic for tenant lifecycle and config."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.config import Settings
from hindsight_manager.crypto import encrypt_sm4
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User
from hindsight_manager.services.api_key_service import generate_raw_key

SYSTEM_KEY_NAME = "system-proxy-key"


def _encryption_key_bytes() -> bytes:
    """Read the SM4 key from settings. Raises ValueError on bad hex."""
    return bytes.fromhex(Settings().encryption_key)


async def list_tenants_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[Tenant]:
    """Tenants the user has any role on."""
    result = await session.execute(
        select(Tenant, TenantMember.role)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .where(TenantMember.user_id == user_id)
    )
    return [t for t, _ in result.all()]


async def create_tenant(
    session: AsyncSession,
    owner: User,
    name: str,
) -> Tenant:
    """Atomically create tenant + owner membership + encrypted system API key."""
    schema_name = f"tenant_{uuid.uuid4().hex[:8]}"
    tenant = Tenant(name=name, schema_name=schema_name, status=TenantStatus.ACTIVE)
    session.add(tenant)
    await session.flush()

    membership = TenantMember(user_id=owner.id, tenant_id=tenant.id, role=MemberRole.OWNER)
    session.add(membership)

    raw_key, key_hash = generate_raw_key()
    encrypted_key = encrypt_sm4(raw_key, _encryption_key_bytes())
    system_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=key_hash,
        key_prefix=raw_key[:16],
        name=SYSTEM_KEY_NAME,
        is_system=True,
        encrypted_key=encrypted_key,
    )
    session.add(system_key)

    await session.commit()
    await session.refresh(tenant)
    return tenant


async def update_tenant_config(
    session: AsyncSession,
    tenant: Tenant,
    name: str | None,
    config_patch: dict,
) -> Tenant:
    """Apply optional name change + merge config patch. Commits + refreshes."""
    if name is not None:
        trimmed = name.strip()
        if not (1 <= len(trimmed) <= 255):
            raise HTTPException(status_code=422, detail="名称长度需在 1-255 之间")
        tenant.name = trimmed

    config = tenant.config or {}
    config.update(config_patch)
    tenant.config = config
    await session.commit()
    await session.refresh(tenant)
    return tenant


async def mark_tenant_deleting(session: AsyncSession, tenant: Tenant) -> None:
    """Soft delete: status -> DELETING. Real deletion handled by task_monitor."""
    tenant.status = TenantStatus.DELETING
    await session.commit()