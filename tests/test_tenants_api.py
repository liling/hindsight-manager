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
    return {"id": user_id, "username": username, "role": "owner"}


def _make_membership(user_id, tenant_id, role):
    m = MagicMock()
    m.user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    m.tenant_id = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
    m.role = role
    return m


def _make_api_key(
    key_id: str,
    tenant_id: str,
    name: str = "old-name",
    is_system: bool = False,
):
    k = MagicMock()
    k.id = uuid.UUID(key_id)
    k.tenant_id = uuid.UUID(tenant_id)
    k.name = name
    k.key_prefix = "hsm_abcd1234efgh"
    k.is_system = is_system
    k.created_at = "2026-01-01T00:00:00"
    k.last_used_at = None
    return k


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


# ─── API Key 改名：PATCH /tenants/{tenant_id}/api-keys/{key_id} ───

API_KEY_ID = "00000000-0000-0000-0000-0000000000a1"
OTHER_TENANT_ID = "00000000-0000-0000-0000-000000000099"


@pytest.mark.asyncio
async def test_update_api_key_name_success(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    api_key = _make_api_key(API_KEY_ID, TENANT_ID, name="old-name")
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = api_key

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "new-name"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-name"
    assert api_key.name == "new-name"


@pytest.mark.asyncio
async def test_update_api_key_empty_name_rejected(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    api_key = _make_api_key(API_KEY_ID, TENANT_ID, name="old-name")
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = api_key

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "   "}
    )
    assert resp.status_code == 422
    assert api_key.name == "old-name"


@pytest.mark.asyncio
async def test_update_api_key_name_too_long_rejected(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    api_key = _make_api_key(API_KEY_ID, TENANT_ID, name="old-name")
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = api_key

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "x" * 256}
    )
    assert resp.status_code == 422
    assert api_key.name == "old-name"


@pytest.mark.asyncio
async def test_update_api_key_system_key_forbidden(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    api_key = _make_api_key(API_KEY_ID, TENANT_ID, name="old-name", is_system=True)
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = api_key

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "new-name"}
    )
    assert resp.status_code == 403
    assert "System API key cannot be renamed" in resp.json()["detail"]
    assert api_key.name == "old-name"


@pytest.mark.asyncio
async def test_update_api_key_not_owner(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)

    _override_session_side_effect([join_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "new-name"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_api_key_not_found(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = None

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "new-name"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_api_key_wrong_tenant_returns_404(client: AsyncClient):
    """key 不属于 path 中的 tenant —— 返回 404 而非 403，避免泄露 key 存在性。"""
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    # 查询同时过滤 tenant_id，跨租户 key 查不到
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = None

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "new-name"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_api_key_strips_whitespace(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    tenant = _make_tenant(TENANT_ID)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (membership, tenant)
    api_key = _make_api_key(API_KEY_ID, TENANT_ID, name="old-name")
    key_result = MagicMock()
    key_result.scalar_one_or_none.return_value = api_key

    _override_session_side_effect([join_result, key_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/api-keys/{API_KEY_ID}", json={"name": "  new-name  "}
    )
    assert resp.status_code == 200
    assert api_key.name == "new-name"
    assert resp.json()["name"] == "new-name"
