import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.audit_outbox import AuditOutbox, OutboxStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


async def enqueue_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict | None,
    ip_address: str | None,
    idempotency_key: str | None = None,
) -> AuditOutbox:
    """Insert a pending audit row. Caller is responsible for commit."""
    entry = AuditOutbox(
        user_id=user_id,
        client_id="hm-prod",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        detail=detail,
        ip_address=ip_address,
        idempotency_key=idempotency_key,
        status=OutboxStatus.PENDING,
    )
    session.add(entry)
    await session.flush()
    return entry


async def audit_retry_once(
    session: AsyncSession,
    platform_client,
) -> int:
    """Pull pending rows (attempts < MAX), post to platform, mark delivered/failed.
    Returns count of newly delivered rows.
    """
    result = await session.execute(
        select(AuditOutbox).where(
            AuditOutbox.status == OutboxStatus.PENDING,
            AuditOutbox.attempts < MAX_ATTEMPTS,
        ).limit(100)
    )
    pending = result.scalars().all()
    delivered = 0
    for row in pending:
        try:
            await platform_client.push_audit({
                "user_id": str(row.user_id) if row.user_id else None,
                "client_id": row.client_id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "detail": row.detail or {},
                "ip_address": row.ip_address,
                "occurred_at": row.occurred_at.isoformat(),
                "idempotency_key": row.idempotency_key or str(row.id),
            })
            row.status = OutboxStatus.DELIVERED
            delivered += 1
        except Exception as e:
            row.attempts += 1
            row.last_error = str(e)[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = OutboxStatus.FAILED
    await session.commit()
    return delivered
