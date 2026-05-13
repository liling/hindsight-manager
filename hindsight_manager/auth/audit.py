import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.audit_log import AuditLog


async def log_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        ip_address=ip_address,
    )
    session.add(entry)
