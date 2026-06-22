"""Smoke tests for /tenants/{id}/members endpoints.

The backend already implements these; this file establishes coverage
that the new dashboard UI depends on. Pattern follows tests/test_pages.py.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.main import app
from hindsight_manager.models.tenant_member import MemberRole


def _make_user(user_id: str, username: str):
    return {"id": user_id, "username": username, "role": "owner"}


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
    t.status = "active"
    return t


TENANT_ID = "00000000-0000-0000-0000-000000000001"
OWNER_ID = "00000000-0000-0000-0000-000000000010"
MEMBER_ID = "00000000-0000-0000-0000-000000000020"
OUTSIDER_ID = "00000000-0000-0000-0000-000000000030"
TARGET_USER_ID = "00000000-0000-0000-0000-000000000040"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _override_session_side_effect(side_effect):
    """Install a mock session whose .execute is `side_effect` (list of results)."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = side_effect
    mock_session.commit = AsyncMock()
    mock_session.delete = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.get = AsyncMock(return_value=None)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override
    return mock_session


def _patch_platform_client(*, batch_get_users=None, get_user_by_username=None):
    """Patch XinyiPlatformClient via module-level patch objects."""
    from unittest.mock import patch

    class FakePlatformClient:
        def __init__(self, *args, **kwargs):
            self._batch = batch_get_users or {}
            self._get_user = get_user_by_username

        async def aclose(self):
            pass

        async def batch_get_users(self, user_ids):
            out = {}
            for uid in user_ids:
                key = str(uid)
                v = self._batch.get(key) or self._batch.get(uid)
                out[uid] = v
            return out

        async def get_user_by_username(self, username):
            return self._get_user

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_ctx(*args, **kwargs):
        yield FakePlatformClient()

    return [
        patch("hindsight_manager.api.members.XinyiPlatformClient", FakePlatformClient),
        patch("hindsight_manager.api.members._platform_client", fake_ctx),
    ]


def _login_as(user_id: str, username: str):
    app.dependency_overrides[get_current_user] = lambda: _make_user(user_id, username)


def _platform_user_info(user_id, username="alice", role="user", **extras):
    """Build a fake user dict that XinyiPlatformClient would return."""
    base = {
        "id": user_id,
        "username": username,
        "display_name": username.title(),
        "email": None,
        "role": role,
        "is_active": True,
    }
    base.update(extras)
    return base


# ---------- GET /tenants/{id}/members ----------

@pytest.mark.asyncio
async def test_list_members_as_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    other_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    membership_result = MagicMock()
    membership_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    list_result = MagicMock()
    # member_service.list_members uses result.scalars().all()
    list_result.scalars.return_value.all.return_value = [owner_membership, other_membership]

    _override_session_side_effect([membership_result, list_result])

    patches = _patch_platform_client(batch_get_users={
        OWNER_ID: _platform_user_info(OWNER_ID, "owner"),
        MEMBER_ID: _platform_user_info(MEMBER_ID, "member"),
    })
    for p in patches:
        p.start()
    try:
        resp = await client.get(f"/tenants/{TENANT_ID}/members")
        assert resp.status_code == 200
        body = resp.json()
        usernames = [m["username"] for m in body]
        assert "owner" in usernames and "member" in usernames
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_members_as_member(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    membership_result = MagicMock()
    membership_result.one_or_none.return_value = (
        _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER),
        _make_tenant(TENANT_ID),
    )
    list_result = MagicMock()
    list_result.all.return_value = []
    _override_session_side_effect([membership_result, list_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/members")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_members_as_non_member(client: AsyncClient):
    _login_as(OUTSIDER_ID, "outsider")
    membership_result = MagicMock()
    membership_result.one_or_none.return_value = None
    _override_session_side_effect([membership_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/members")
    assert resp.status_code == 404


# ---------- POST /tenants/{id}/members ----------

@pytest.mark.asyncio
async def test_add_member_by_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    owner_join_result = MagicMock()
    owner_join_result.one_or_none.return_value = (
        owner_membership,
        _make_tenant(TENANT_ID),
    )

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None

    mock_session = _override_session_side_effect([owner_join_result, existing_result])

    patches = _patch_platform_client(
        get_user_by_username=_platform_user_info(TARGET_USER_ID, "newbie", role="user"),
    )
    for p in patches:
        p.start()
    try:
        resp = await client.post(
            f"/tenants/{TENANT_ID}/members",
            json={"username": "newbie", "role": "member"},
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "newbie"
        assert resp.json()["role"] == "member"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_add_member_by_member_forbidden(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    member_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (
        member_membership,
        _make_tenant(TENANT_ID),
    )
    _override_session_side_effect([join_result])

    resp = await client.post(
        f"/tenants/{TENANT_ID}/members",
        json={"username": "newbie", "role": "member"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_add_nonexistent_user(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    _override_session_side_effect([join_result])

    patches = _patch_platform_client(get_user_by_username=None)
    for p in patches:
        p.start()
    try:
        resp = await client.post(
            f"/tenants/{TENANT_ID}/members",
            json={"username": "ghost", "role": "member"},
        )
        assert resp.status_code == 404
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_add_duplicate_member(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    existing = _make_membership(TARGET_USER_ID, TENANT_ID, MemberRole.MEMBER)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing

    _override_session_side_effect([join_result, existing_result])

    patches = _patch_platform_client(
        get_user_by_username=_platform_user_info(TARGET_USER_ID, "newbie"),
    )
    for p in patches:
        p.start()
    try:
        resp = await client.post(
            f"/tenants/{TENANT_ID}/members",
            json={"username": "newbie", "role": "member"},
        )
        assert resp.status_code == 409
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()


# ---------- GET /tenants/{id}/members/lookup ----------

def _make_lookup_user(user_id: str, username: str, display_name: str, email):
    base = _make_user(user_id, username)
    base["display_name"] = display_name
    base["email"] = email
    return base


@pytest.mark.asyncio
async def test_lookup_member_success(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None

    _override_session_side_effect([join_result, existing_result])

    patches = _patch_platform_client(
        get_user_by_username=_platform_user_info(TARGET_USER_ID, "newbie", role="user",
                                                  display_name="Newbie", email="newbie@example.com"),
    )
    for p in patches:
        p.start()
    try:
        resp = await client.get(f"/tenants/{TENANT_ID}/members/lookup?username=newbie")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "newbie"
        assert body["display_name"] == "Newbie"
        assert body["email"] == "newbie@example.com"
        assert body["is_already_member"] is False
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_lookup_member_already_member(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    existing = _make_membership(TARGET_USER_ID, TENANT_ID, MemberRole.MEMBER)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing

    _override_session_side_effect([join_result, existing_result])

    patches = _patch_platform_client(
        get_user_by_username=_platform_user_info(TARGET_USER_ID, "newbie", role="user"),
    )
    for p in patches:
        p.start()
    try:
        resp = await client.get(f"/tenants/{TENANT_ID}/members/lookup?username=newbie")
        assert resp.status_code == 200
        assert resp.json()["is_already_member"] is True
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_lookup_member_not_found(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = None

    _override_session_side_effect([join_result, target_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/members/lookup?username=ghost")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_lookup_member_requires_owner(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    member_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (member_membership, _make_tenant(TENANT_ID))
    _override_session_side_effect([join_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/members/lookup?username=newbie")
    assert resp.status_code == 403


# ---------- DELETE /tenants/{id}/members/{user_id} ----------

@pytest.mark.asyncio
async def test_remove_member_by_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    target_membership = _make_membership(TARGET_USER_ID, TENANT_ID, MemberRole.MEMBER)
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target_membership

    mock_session = _override_session_side_effect([join_result, target_result])

    resp = await client.delete(f"/tenants/{TENANT_ID}/members/{TARGET_USER_ID}")
    assert resp.status_code == 204
    mock_session.delete.assert_awaited_once_with(target_membership)
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_member_by_member_forbidden(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    member_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (member_membership, _make_tenant(TENANT_ID))
    _override_session_side_effect([join_result])

    resp = await client.delete(f"/tenants/{TENANT_ID}/members/{TARGET_USER_ID}")
    assert resp.status_code == 403


# ---------- PATCH /tenants/{id}/members/{user_id} ----------

@pytest.mark.asyncio
async def test_change_role_by_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    target_membership = _make_membership(TARGET_USER_ID, TENANT_ID, MemberRole.MEMBER)
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target_membership

    mock_session = _override_session_side_effect([join_result, target_result])
    # session.get(User, user_id) for username lookup
    mock_session.get = AsyncMock(return_value=_make_user(TARGET_USER_ID, "newbie"))

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/members/{TARGET_USER_ID}",
        json={"role": "owner"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"
    assert target_membership.role == MemberRole.OWNER
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_role_by_member_forbidden(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    member_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (member_membership, _make_tenant(TENANT_ID))
    _override_session_side_effect([join_result])

    resp = await client.patch(
        f"/tenants/{TENANT_ID}/members/{TARGET_USER_ID}",
        json={"role": "owner"},
    )
    assert resp.status_code == 403