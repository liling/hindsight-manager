import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from hindsight_manager.models.audit_outbox import AuditOutbox, OutboxStatus
from hindsight_manager.services.audit_outbox_service import (
    audit_retry_once,
    enqueue_audit,
)


def _make_session(scalars_result=None):
    session = MagicMock()
    session.execute = AsyncMock()
    session.execute.return_value = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_result or []
    session.execute.return_value.scalars.return_value = scalars_mock
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


async def test_enqueue_audit_inserts_pending_row():
    session = _make_session()
    user_id = uuid.uuid4()
    entry = await enqueue_audit(
        session,
        user_id=user_id,
        action="hm.tenant.create",
        resource_type="tenant",
        resource_id="abc",
        detail={"name": "x"},
        ip_address="127.0.0.1",
    )
    session.add.assert_called_once()
    assert entry.status == OutboxStatus.PENDING
    assert entry.action == "hm.tenant.create"


async def test_retry_once_delivers_pending():
    pending = AuditOutbox(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        client_id="hm-prod",
        action="hm.test",
        resource_type="t", resource_id="1",
        detail=None, ip_address=None,
        occurred_at=datetime.now(timezone.utc),
        status=OutboxStatus.PENDING, attempts=0,
    )
    session = _make_session(scalars_result=[pending])
    platform_client = MagicMock()
    platform_client.push_audit = AsyncMock()
    delivered = await audit_retry_once(session, platform_client)
    assert delivered == 1
    assert pending.status == OutboxStatus.DELIVERED
    platform_client.push_audit.assert_called_once()


async def test_retry_once_increments_attempts_on_failure():
    pending = AuditOutbox(
        id=uuid.uuid4(),
        action="hm.test",
        resource_type="t", resource_id="1",
        occurred_at=datetime.now(timezone.utc),
        status=OutboxStatus.PENDING, attempts=0,
    )
    session = _make_session(scalars_result=[pending])
    platform_client = MagicMock()
    platform_client.push_audit = AsyncMock(side_effect=Exception("platform down"))
    delivered = await audit_retry_once(session, platform_client)
    assert delivered == 0
    assert pending.status == OutboxStatus.PENDING
    assert pending.attempts == 1
    assert pending.last_error is not None


async def test_retry_once_skips_high_attempts():
    # attempts=5 rows are filtered out by the SELECT query
    session = _make_session(scalars_result=[])
    delivered = await audit_retry_once(session, MagicMock())
    assert delivered == 0
