"""Tests for POST/GET/DELETE /tenants/{tenant_id}/api-keys.

These endpoints are touched by the upcoming service-layer refactor;
this file establishes a behavior baseline before that refactor.
"""

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
API_KEY_ID = "00000000-0000-0000-0000-0000000000a1"


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


def _make_tenant(tenant_id: str, name: str = "Test Tenant"):
    t = MagicMock()
    t.id = uuid.UUID(tenant_id)
    t.name = name
    t.schema_name = "tenant_test"
    t.status = MagicMock()
    t.status.value = "active"
    return t


def _make_api_key(key_id: str, tenant_id: str, name: str = "test-key", is_system: bool = False):
    k = MagicMock()
    k.id = uuid.UUID(key_id)
    k.tenant_id = uuid.UUID(tenant_id)
    k.name = name
    k.key_prefix = "hsm_abcd1234efgh"
    k.is_system = is_system
    k.created_at = "2026-01-01T00:00:00"
    k.last_used_at = None
    return k


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
    mock_session.delete = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.get = AsyncMock(return_value=None)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override
    return mock_session


def _login_as(user_id: str, username: str):
    app.dependency_overrides[get_current_user] = lambda: _make_user(user_id, username)


# ---------- POST /tenants/{tenant_id}/api-keys ----------

@pytest.mark.asyncio
async def test_create_api_key_as_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    mock_session = _override_session_side_effect([join_result])

    resp = await client.post(
        f"/tenants/{TENANT_ID}/api-keys",
        json={"name": "my-key"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my-key"
    assert body["is_system"] is False
    assert body["key"].startswith("hsm_")
    assert body["key_prefix"] == body["key"][:16]
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_api_key_as_member_forbidden(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    member_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (member_membership, _make_tenant(TENANT_ID))

    _override_session_side_effect([join_result])

    resp = await client.post(
        f"/tenants/{TENANT_ID}/api-keys",
        json={"name": "my-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_api_key_as_outsider_not_found(client: AsyncClient):
    _login_as(MEMBER_ID, "outsider")
    join_result = MagicMock()
    join_result.one_or_none.return_value = None

    _override_session_side_effect([join_result])

    resp = await client.post(
        f"/tenants/{TENANT_ID}/api-keys",
        json={"name": "my-key"},
    )
    assert resp.status_code == 404


# ---------- GET /tenants/{tenant_id}/api-keys ----------

@pytest.mark.asyncio
async def test_list_api_keys_as_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    sys_key = _make_api_key(API_KEY_ID, TENANT_ID, name="system-proxy-key", is_system=True)
    user_key = _make_api_key("00000000-0000-0000-0000-0000000000b2", TENANT_ID, name="mine", is_system=False)
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [sys_key, user_key]

    _override_session_side_effect([join_result, list_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["is_system"] is True  # system key 排在前
    assert body[1]["is_system"] is False


@pytest.mark.asyncio
async def test_list_api_keys_as_member_forbidden(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    member_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (member_membership, _make_tenant(TENANT_ID))

    _override_session_side_effect([join_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/api-keys")
    assert resp.status_code == 403


# ---------- DELETE /tenants/{tenant_id}/api-keys/{key_id} ----------

@pytest.mark.asyncio
async def test_revoke_api_key_as_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    api_key = _make_api_key(API_KEY_ID, TENANT_ID, name="mine", is_system=False)
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = api_key

    mock_session = _override_session_side_effect([join_result, key_result])

    resp = await client.delete(f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_session.delete.assert_awaited_once_with(api_key)
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_api_key_not_found(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = None

    _override_session_side_effect([join_result, key_result])

    resp = await client.delete(f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}")
    assert resp.status_code == 404