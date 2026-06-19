"""Tests for POST /admin/api/tenants/{id}/purge endpoint."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.main import app
from hindsight_manager.models.tenant import TenantStatus
from hindsight_manager.models.user import UserRole


TENANT_ID = "00000000-0000-0000-0000-000000000001"
ADMIN_ID = "00000000-0000-0000-0000-0000000000a0"


def _make_user(user_id: str, role: UserRole):
    u = MagicMock()
    u.id = uuid.UUID(user_id)
    u.role = role
    return u


def _make_tenant(status: TenantStatus, schema_name: str = "tenant_abc12345"):
    t = MagicMock()
    t.id = uuid.UUID(TENANT_ID)
    t.name = "Test Tenant"
    t.schema_name = schema_name
    t.status = status
    return t


def _make_result(*, scalar=None, fetchone=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.fetchone.return_value = fetchone
    return r


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _override_session_and_user(session_mock, user_role=UserRole.ADMIN):
    async def _session_override():
        yield session_mock
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = lambda: _make_user(ADMIN_ID, user_role)


# ---------- 403 非管理员 ----------

@pytest.mark.asyncio
async def test_purge_requires_admin(client):
    mock_session = AsyncMock()
    _override_session_and_user(mock_session, user_role=UserRole.USER)
    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")
    assert resp.status_code == 403


# ---------- 404 租户不存在 ----------

@pytest.mark.asyncio
async def test_purge_unknown_tenant_404(client):
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[_make_result(scalar=None)]
    )
    _override_session_and_user(mock_session)
    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")
    assert resp.status_code == 404


# ---------- 409 ACTIVE ----------

@pytest.mark.asyncio
async def test_purge_active_tenant_409(client):
    tenant = _make_tenant(TenantStatus.ACTIVE)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[_make_result(scalar=tenant)])
    _override_session_and_user(mock_session)
    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")
    assert resp.status_code == 409
    assert "active" in resp.json()["detail"].lower()


# ---------- 409 DELETED（幂等保护） ----------

@pytest.mark.asyncio
async def test_purge_deleted_tenant_409(client):
    tenant = _make_tenant(TenantStatus.DELETED)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[_make_result(scalar=tenant)])
    _override_session_and_user(mock_session)
    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")
    assert resp.status_code == 409


# ---------- 成功路径（schema 存在） ----------

@pytest.mark.asyncio
async def test_purge_deleting_tenant_success(client):
    tenant = _make_tenant(TenantStatus.DELETING)
    mock_session = AsyncMock()
    # 执行顺序: SELECT tenant → SELECT schema_exists → DROP SCHEMA
    mock_session.execute = AsyncMock(side_effect=[
        _make_result(scalar=tenant),                           # tenant lookup
        _make_result(fetchone=(1,)),                           # schema_exists check
        MagicMock(),                                           # DROP SCHEMA
    ])
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    _override_session_and_user(mock_session)

    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "schema_dropped": True}
    assert tenant.status == TenantStatus.DELETED  # 端点里设置过
    mock_session.commit.assert_awaited_once()

    # Verify the DROP SCHEMA SQL is correct (not just that execute was called)
    drop_sql = str(mock_session.execute.call_args_list[2].args[0])
    assert "DROP SCHEMA" in drop_sql.upper()
    assert "tenant_abc12345" in drop_sql
    assert "CASCADE" in drop_sql.upper()


# ---------- 成功路径（schema 不存在） ----------

@pytest.mark.asyncio
async def test_purge_when_schema_missing(client):
    tenant = _make_tenant(TenantStatus.DELETING)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[
        _make_result(scalar=tenant),
        _make_result(fetchone=None),                           # schema 不存在
    ])
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    _override_session_and_user(mock_session)

    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "schema_dropped": False}
    # DROP SCHEMA 不应该被调用（仅 2 次 execute）
    assert mock_session.execute.await_count == 2


# ---------- 500 schema_name 异常 ----------

@pytest.mark.asyncio
async def test_purge_invalid_schema_name_500(client):
    tenant = _make_tenant(TenantStatus.DELETING, schema_name="public")
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[_make_result(scalar=tenant)])
    _override_session_and_user(mock_session)

    resp = await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")

    assert resp.status_code == 500
    # DROP SCHEMA 不应该被调用
    assert mock_session.execute.await_count == 1


# ---------- 审计日志 ----------

@pytest.mark.asyncio
async def test_purge_writes_audit_log(client):
    tenant = _make_tenant(TenantStatus.DELETING)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[
        _make_result(scalar=tenant),
        _make_result(fetchone=None),                           # schema 不存在
    ])
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    _override_session_and_user(mock_session)

    await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")

    # 验证 audit_log 通过 session.add 写入
    added = [c.args[0] for c in mock_session.add.call_args_list]
    audit_entries = [a for a in added if getattr(a, "action", None) == "tenant.purge"]
    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry.resource_type == "tenant"
    assert entry.resource_id == TENANT_ID
    assert entry.detail["schema_name"] == "tenant_abc12345"
    assert entry.detail["schema_dropped"] is False


# ---------- SELECT FOR UPDATE 并发保护 ----------

@pytest.mark.asyncio
async def test_purge_uses_select_for_update(client):
    """Purge must lock the tenant row with SELECT FOR UPDATE to serialize concurrent calls."""
    tenant = _make_tenant(TenantStatus.DELETING)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[
        _make_result(scalar=tenant),
        _make_result(fetchone=None),  # schema not exists → no DROP
    ])
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    _override_session_and_user(mock_session)

    await client.post(f"/admin/api/tenants/{TENANT_ID}/purge")

    first_call = mock_session.execute.call_args_list[0]
    # SQLAlchemy renders with_for_update as "FOR UPDATE" in the SQL
    select_sql = str(first_call.args[0])
    assert "FOR UPDATE" in select_sql.upper(), \
        "purge must use SELECT ... FOR UPDATE to serialize concurrent calls"


# ---------- 列表过滤 DELETED ----------

@pytest.mark.asyncio
async def test_admin_tenant_list_excludes_deleted(client):
    """list_tenants_admin should filter out DELETED tenants."""
    # 验证 SQL 语句包含 status != 'deleted' 过滤
    # 我们 mock 返回空列表，重点验证 query 拼接
    captured_queries = []

    async def capture_execute(query, *args, **kwargs):
        captured_queries.append(str(query))
        r = MagicMock()
        # 不同调用返回不同结构
        if "count" in str(query).lower():
            r.scalar.return_value = 0
        else:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            r.scalars.return_value = mock_scalars
        return r

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=capture_execute)
    _override_session_and_user(mock_session)

    resp = await client.get("/admin/api/tenants")
    assert resp.status_code == 200

    # count_query 和主 query 都不应该返回 deleted 行
    list_sqls = [q for q in captured_queries if "FROM manager.tenants" in q]
    # 检查查询中是否有 status != 条件（参数化查询）
    # 验证 WHERE 子句包含 status 过滤（参数化形式渲染为 "status != :status_1"），
    # 同时检查 "deleted" 是否出现在 SQL 字符串中。
    status_filter_present = any("status != " in q or "status <> " in q for q in list_sqls)
    assert status_filter_present, \
        "tenant list query must filter out DELETED status via WHERE status != <deleted>"


# ---------- API key 列表过滤 DELETED 租户 ----------

@pytest.mark.asyncio
async def test_admin_api_key_list_excludes_deleted_tenant(client):
    """list_api_keys_admin should hide API keys belonging to DELETED tenants."""
    captured_queries = []

    async def capture_execute(query, *args, **kwargs):
        captured_queries.append(str(query))
        r = MagicMock()
        if "count" in str(query).lower():
            r.scalar.return_value = 0
        else:
            mock_all = MagicMock()
            mock_all.all.return_value = []
            r.all.return_value = mock_all
        return r

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=capture_execute)
    _override_session_and_user(mock_session)

    resp = await client.get("/admin/api/api-keys")
    assert resp.status_code == 200

    # api_keys JOIN tenants 的查询应该只显示 ACTIVE 租户的 key
    # SQLAlchemy 渲染为 "status = :status_1"（注意 "status = " 不是 "status != " 的子串）
    join_sqls = [q for q in captured_queries if "api_keys" in q and "tenants" in q]
    assert join_sqls, "expected joined api_keys/tenants queries"
    status_filter_present = any("status = " in q for q in join_sqls)
    assert status_filter_present, \
        "api key list query must filter to ACTIVE tenants only via WHERE status = <active>"
