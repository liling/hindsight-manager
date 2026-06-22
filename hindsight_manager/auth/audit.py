import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.services.audit_outbox_service import enqueue_audit


async def record_audit(
    request: Request,
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Enqueue audit event to local outbox. Non-blocking w.r.t. platform availability."""
    ip = request.client.host if request.client else None
    await enqueue_audit(
        session,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        ip_address=ip,
    )


# Backward-compat alias (some callers may use the old name)
log_audit = record_audit
