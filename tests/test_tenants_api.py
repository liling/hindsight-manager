"""Tests for PATCH /tenants/{id} name update."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.main import app
from hindsight_manager.models.tenant_member import MemberRole


TENANT_ID = "00000000-0000-0000-0000-000000000001"
OWNER_ID = "00000000-0000-0000-0000-000000000010"
MEMBER_ID = "00000000-0000-0000-0000-000000000020"


def _make_user(user_id: str, username: str):
    u = MagicMock()
    u.id = uuid.UUID(user_id)
    u.username = username
    return u


def _make_membership(user_id, tenant_id, role):
    m = MagicMock()
    m.user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    m.tenant_id = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
    m.role = role
    return m


def _make_tenant(tenant_id: str, name: str = "Test Tenant", config=None):
    t = MagicMock()
    t.id = uuid.UUID(tenant_id)
    t.name = name
    t.schema_name = "tenant_test"
    t.config = config
    t.status = MagicMock()
    t.status.value = "active"
    t.created_at = "2026-01-01T00:00:00"
    return t


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _override_session_side_effect(side_effect):
    mock_session = AsyncMock()
    mock_session.execute.side_effect = side_effect
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.get = AsyncMock(return_value=None)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override
    return mock_session


def _login_as(user_id: str, username: str):
    app.dependency_overrides[get_current_user] = lambda: _make_user(user_id, username)


@pytest.mark.asyncio
async def test_owner_can_rename_tenant(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID, name="旧名")
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(f"/tenants/{TENANT_ID}", json={"name": "新名"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名"
    assert tenant.name == "新名"


@pytest.mark.asyncio
async def test_member_cannot_rename_tenant(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    tenant = _make_tenant(TENANT_ID, name="旧名")
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(f"/tenants/{TENANT_ID}", json={"name": "新名"})
    assert resp.status_code == 403
    assert tenant.name == "旧名"


@pytest.mark.asyncio
async def test_rename_empty_name_rejected(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID, name="旧名")
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(f"/tenants/{TENANT_ID}", json={"name": "   "})
    assert resp.status_code == 422
    assert tenant.name == "旧名"


@pytest.mark.asyncio
async def test_rename_too_long_name_rejected(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID, name="旧名")
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(f"/tenants/{TENANT_ID}", json={"name": "x" * 256})
    assert resp.status_code == 422
    assert tenant.name == "旧名"


@pytest.mark.asyncio
async def test_update_config_preserves_name(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID, name="保持不变", config={})
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}",
        json={"llm_provider": "openai"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "保持不变"
    assert resp.json()["config"]["llm_provider"] == "openai"


@pytest.mark.asyncio
async def test_rename_and_update_config_together(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID, name="旧名", config={})
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}",
        json={"name": "新名", "llm_model": "gpt-4"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "新名"
    assert body["config"]["llm_model"] == "gpt-4"
    # name 不应被错塞进 config
    assert "name" not in body["config"]
