"""Business logic for tenant-scoped API keys."""

import secrets
import uuid
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.api_key import ApiKey

KEY_PREFIX = "hsm_"


def generate_raw_key() -> tuple[str, str]:
    """Return (raw_key, sha256_hex_hash). raw_key caller-visible only once."""
    raw = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw, sha256(raw.encode()).hexdigest()


async def create_api_key(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
) -> tuple[ApiKey, str]:
    """Persist a new (non-system) API key. Returns (record, raw_key_once)."""
    raw_key, key_hash = generate_raw_key()
    api_key = ApiKey(
        tenant_id=tenant_id,
        key_hash=key_hash,
        key_prefix=raw_key[:16],
        name=name,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return api_key, raw_key


async def list_api_keys(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[ApiKey]:
    """System keys first, then by created_at desc."""
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.tenant_id == tenant_id)
        .order_by(ApiKey.is_system.desc(), ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
) -> None:
    """Delete one key. 404 if not found or belongs to another tenant."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    await session.delete(api_key)
    await session.commit()


async def update_api_key_name(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    name: str,
) -> ApiKey:
    """Rename a non-system key.

    Raises:
        HTTPException 404: key not found in this tenant.
        HTTPException 403: key is_system.
        HTTPException 422: name length not in 1..255 after trim.
    """
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if api_key.is_system:
        raise HTTPException(status_code=403, detail="System API key cannot be renamed")

    trimmed = name.strip()
    if not (1 <= len(trimmed) <= 255):
        raise HTTPException(status_code=422, detail="名称长度需在 1-255 之间")
    api_key.name = trimmed
    await session.commit()
    await session.refresh(api_key)
    return api_key
