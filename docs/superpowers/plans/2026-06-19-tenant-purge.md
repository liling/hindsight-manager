# 租户清空（Purge）功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `POST /admin/api/tenants/{id}/purge` 接口，把 DELETING 状态的租户业务 schema 真的 DROP 掉并把状态推进到 DELETED，配套 CLI 命令和管理后台 UI 按钮。

**Architecture:** 新增 `TenantStatus.DELETED` 终态。新增管理员专属 purge 接口，在单个事务里 SELECT FOR UPDATE 锁租户行 → DROP SCHEMA CASCADE → UPDATE status → INSERT audit log。CLI 命令调接口。管理后台 UI 在 DELETING 行显示"清空"按钮，要求手打租户名确认。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL 16（共享给 hindsight-api）+ Typer CLI + 原生 JS/HTML（admin.js / admin_tenants.html）。

## Global Constraints

- 所有环境变量前缀 `HINDSIGHT_MANAGER_`，schema 名固定 `manager`（`HINDSIGHT_MANAGER_MANAGER_SCHEMA` 默认值）
- schema_name 严格匹配正则 `^tenant_[a-f0-9]{8}$`，拼接 SQL 前必须校验
- 所有测试用 mock session（不打真 Postgres），参考 `tests/test_members_api.py` 的 `AsyncMock` + `side_effect` 模式
- 命令风格：`uv run pytest <path>::<test> -v`，提交粒度按 task
- 中文 UI 文案；commit message 用英文
- 不动 `ManagerTenantExtension`、不动软删除端点

## File Structure

| 文件 | 改动 | 责任 |
|------|------|------|
| `hindsight_manager/models/tenant.py` | 修改 | 加 `TenantStatus.DELETED` |
| `hindsight_manager/migrations/versions/005_add_deleted_tenant_status.py` | 新建 | 给 `tenant_status` enum 加 `deleted` 值 |
| `hindsight_manager/api/admin.py` | 修改 | 加 `purge_tenant_admin` 端点；`list_tenants_admin` 加 `status != DELETED` 过滤 |
| `tests/test_tenant_purge.py` | 新建 | purge 端点的所有分支测试 |
| `hindsight_manager/cli/tenant.py` | 修改 | 加 `purge` 命令 |
| `static/admin.js` | 修改 | 加 `purgeTenantAdmin`、按钮切换逻辑、确认弹窗 |
| `templates/admin_tenants.html` | 修改（仅引用/确认模态） | 视情况补模态容器 |

---

## Task 1: 加 `TenantStatus.DELETED` 枚举 + Alembic 迁移

**Files:**
- Modify: `hindsight_manager/models/tenant.py`
- Create: `hindsight_manager/migrations/versions/005_add_deleted_tenant_status.py`

**Interfaces:**
- Produces: `TenantStatus.DELETED` 值为 `"deleted"`；`tenant_status` PG enum 多一个值

- [ ] **Step 1: 改 `TenantStatus` 加 `DELETED`**

修改 `hindsight_manager/models/tenant.py:10-12`：

```python
class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETING = "deleting"
    DELETED = "deleted"
```

- [ ] **Step 2: 新建迁移 `005_add_deleted_tenant_status.py`**

完整文件内容：

```python
"""add deleted to tenant_status enum

Revision ID: 005
Revises: 004
Create Date: 2026-06-19
"""
from alembic import op


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    # PG 12+ allows ALTER TYPE ... ADD VALUE IF NOT EXISTS inside a
    # transaction block (which Alembic wraps). If this fails on older PG,
    # switch to: op.execute("COMMIT"); op.execute("ALTER TYPE ...")
    op.execute(
        f"ALTER TYPE {SCHEMA}.tenant_status ADD VALUE IF NOT EXISTS 'deleted'"
    )


def downgrade() -> None:
    # PG 不支持从 enum 直接移除值；downgrade 需重建类型，留作 not implemented。
    raise NotImplementedError(
        "Removing enum values requires type rebuild; see PG docs."
    )
```

- [ ] **Step 3: 跑 migration 验证**

Run: `alembic upgrade head`
Expected: 输出 `Running upgrade 004 -> 005, add deleted to tenant_status enum`

验证：`psql -d hindsight_dev -c "SELECT unnest(enum_range(NULL::manager.tenant_status));"` 应包含 `deleted`。

- [ ] **Step 4: 提交**

```bash
git add hindsight_manager/models/tenant.py hindsight_manager/migrations/versions/005_add_deleted_tenant_status.py
git commit -m "feat: add TenantStatus.DELETED + migration for enum value"
```

---

## Task 2: 实现 `POST /admin/api/tenants/{id}/purge` 端点（TDD）

**Files:**
- Modify: `hindsight_manager/api/admin.py`
- Create: `tests/test_tenant_purge.py`

**Interfaces:**
- Consumes: `TenantStatus.DELETED`（Task 1）；`require_admin`、`log_audit`、`_get_client_ip`（已存在）
- Produces: `POST /admin/api/tenants/{id}/purge` 返回 `{"ok": true, "schema_dropped": <bool>}`

**响应契约：**
- 200 `{"ok": true, "schema_dropped": <bool>}` — 成功
- 403 — 非管理员
- 404 — 租户不存在
- 409 — 状态非 DELETING（active 或 deleted）
- 500 — schema_name 异常或 DROP 失败

- [ ] **Step 1: 写测试文件 `tests/test_tenant_purge.py`**

```python
"""Tests for POST /admin/api/tenants/{id}/purge endpoint."""
import re
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
```

- [ ] **Step 2: 运行测试，确认全失败**

Run: `uv run pytest tests/test_tenant_purge.py -v`
Expected: 所有测试 FAIL（路由不存在 → 404，断言失败）

- [ ] **Step 3: 在 `api/admin.py` 加导入**

修改 `hindsight_manager/api/admin.py:5`：

```python
from sqlalchemy import func, select, text
```

加 `import re` 在文件顶部 `import uuid` 之后（第 1 行附近）：

```python
import re
import uuid
```

- [ ] **Step 4: 在 `api/admin.py` 加 purge 端点**

在文件末尾追加（`delete_tenant_admin` 函数之后）：

```python
TENANT_SCHEMA_PATTERN = re.compile(r"^tenant_[a-f0-9]{8}$")


@router.post("/tenants/{tenant_id}/purge")
async def purge_tenant_admin(
    tenant_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    # SELECT FOR UPDATE 序列化并发 purge
    result = await session.execute(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update()
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    if tenant.status != TenantStatus.DELETING:
        raise HTTPException(
            status_code=409,
            detail=f"租户状态为 {tenant.status.value}，需先软删除后再清空",
        )

    # 防 SQL 注入：schema 名无法参数化，必须白名单校验
    if not TENANT_SCHEMA_PATTERN.match(tenant.schema_name):
        raise HTTPException(
            status_code=500,
            detail="租户 schema 名称异常，拒绝清空",
        )

    # 检查 schema 是否存在（可能从未被懒创建）
    exists_result = await session.execute(
        text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"
        ),
        {"name": tenant.schema_name},
    )
    schema_existed = exists_result.fetchone() is not None

    if schema_existed:
        await session.execute(
            text(f'DROP SCHEMA "{tenant.schema_name}" CASCADE')
        )

    tenant.status = TenantStatus.DELETED

    await log_audit(
        session,
        user_id=current_user.id,
        action="tenant.purge",
        resource_type="tenant",
        resource_id=str(tenant_id),
        detail={
            "name": tenant.name,
            "schema_name": tenant.schema_name,
            "schema_dropped": schema_existed,
        },
        ip_address=_get_client_ip(request),
    )
    await session.commit()
    return {"ok": True, "schema_dropped": schema_existed}
```

- [ ] **Step 5: 运行测试，确认全通过**

Run: `uv run pytest tests/test_tenant_purge.py -v`
Expected: 7 个测试 PASS

- [ ] **Step 6: 跑全套测试，确认没有回归**

Run: `uv run pytest`
Expected: 全套 PASS

- [ ] **Step 7: 提交**

```bash
git add hindsight_manager/api/admin.py tests/test_tenant_purge.py
git commit -m "feat: add admin purge endpoint with DROP SCHEMA + audit"
```

---

## Task 3: 管理后台列表过滤 DELETED 租户

**Files:**
- Modify: `hindsight_manager/api/admin.py` —— `list_tenants_admin` 函数（约 300-357 行）
- Modify: `tests/test_tenant_purge.py` —— 加列表测试

**Interfaces:**
- 修改：`list_tenants_admin` 的 `query` 和 `count_query` 加 `.where(Tenant.status != TenantStatus.DELETED)`

- [ ] **Step 1: 在 `tests/test_tenant_purge.py` 末尾追加列表测试**

```python
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
            r.scalars.return_value = []
        return r

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=capture_execute)
    _override_session_and_user(mock_session)

    resp = await client.get("/admin/api/tenants")
    assert resp.status_code == 200

    # count_query 和主 query 都不应该返回 deleted 行
    list_sqls = [q for q in captured_queries if "FROM manager.tenants" in q]
    assert any("deleted" in q.lower() for q in list_sqls), \
        "tenant list query must filter out DELETED status"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run pytest tests/test_tenant_purge.py::test_admin_tenant_list_excludes_deleted -v`
Expected: FAIL（当前 list_tenants_admin 没有过滤）

- [ ] **Step 3: 修改 `list_tenants_admin` 加过滤**

在 `api/admin.py` 的 `list_tenants_admin` 函数里（约 307-308 行）：

把：
```python
    query = select(Tenant).order_by(Tenant.created_at.desc())
    count_query = select(func.count()).select_from(Tenant)
```

改成：
```python
    query = (
        select(Tenant)
        .where(Tenant.status != TenantStatus.DELETED)
        .order_by(Tenant.created_at.desc())
    )
    count_query = (
        select(func.count())
        .select_from(Tenant)
        .where(Tenant.status != TenantStatus.DELETED)
    )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `uv run pytest tests/test_tenant_purge.py -v`
Expected: 全部 PASS（包括新加的列表测试）

- [ ] **Step 5: 提交**

```bash
git add hindsight_manager/api/admin.py tests/test_tenant_purge.py
git commit -m "feat: exclude DELETED tenants from admin list"
```

---

## Task 4: CLI 加 `tenant purge` 命令

**Files:**
- Modify: `hindsight_manager/cli/tenant.py`

**Interfaces:**
- Consumes: `POST /admin/api/tenants/{id}/purge`
- Produces: `hindsight-manager tenant purge <tenant_id>` 命令

- [ ] **Step 1: 在 `cli/tenant.py` 的 `delete_tenant` 函数（约 73-79 行）之后加 purge 命令**

```python
@app.command()
def purge_tenant(tenant_id: str):
    """彻底清空已软删除的租户（DROP SCHEMA，不可逆）。"""
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(f"{base_url}/admin/api/tenants/{tenant_id}/purge", headers=headers)
    if resp.status_code == 409:
        detail = resp.json().get("detail", "")
        typer.echo(
            f"无法清空：{detail}。请先运行 'hindsight-manager tenant delete {tenant_id}'。",
            err=True,
        )
        raise typer.Exit(1)
    if resp.status_code == 404:
        typer.echo("租户不存在。", err=True)
        raise typer.Exit(1)
    resp.raise_for_status()
    data = resp.json()
    dropped = data.get("schema_dropped")
    typer.echo(f"已清空租户 {tenant_id}（schema_dropped={dropped}）。")
```

- [ ] **Step 2: 验证 CLI 注册**

Run: `uv run hindsight-manager tenant --help`
Expected: 输出包含 `purge-tenant` 命令（Typer 把 `purge_tenant` 转成 `purge-tenant`，或保持 `purge`，取决于 Typer 版本）

如果命令名不理想，改成显式命名：

```python
@app.command(name="purge")
def purge_tenant(tenant_id: str):
    ...
```

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/cli/tenant.py
git commit -m "feat: add 'tenant purge' CLI command"
```

---

## Task 5: 管理后台 UI —— "清空"按钮 + 确认弹窗

**Files:**
- Modify: `static/admin.js` —— 改 `loadTenants` 的渲染逻辑，加 `purgeTenantAdmin` 函数和确认弹窗

**Interfaces:**
- Consumes: `POST /admin/api/tenants/{id}/purge`（Task 2）
- UI 行为：active 行显示"删除"按钮；deleting 行显示"清空"按钮（红色危险样式）

**UI 文案：**
- 弹窗标题：`彻底清空租户`
- 弹窗正文：`此操作不可撤销，将永久删除 schema <code>{schema_name}</code> 下的所有业务数据。元数据会保留以便审计。`
- 确认输入提示：`请输入租户名 "{name}" 以确认：`
- 确认按钮：禁用，直到输入完全匹配

- [ ] **Step 1: 备份当前 `static/admin.js` 的 `loadTenants` 和 `deleteTenantAdmin` 区段**

Run: `grep -n "loadTenants\|deleteTenantAdmin" /Users/liling/src/lab/hindsight-manager/static/admin.js`

确认当前行号（应为 ~190-242）。计划是基于这两个函数已经存在。

- [ ] **Step 2: 改 `loadTenants` 渲染逻辑**

在 `static/admin.js` 找到 `loadTenants` 函数里的 `tbody.innerHTML = data.items.map(...)` 块（约 209-222 行），把 `<td class="action-cell">` 内容改成按状态切换按钮：

把：
```javascript
        <td class="action-cell">
          <button class="btn btn-danger btn-sm" onclick="deleteTenantAdmin('${t.id}','${escapeHtml(t.name)}')">删除</button>
        </td>
```

改成：
```javascript
        <td class="action-cell">
          ${t.status === 'active'
            ? `<button class="btn btn-danger btn-sm" onclick="deleteTenantAdmin('${t.id}','${escapeHtml(t.name)}')">删除</button>`
            : t.status === 'deleting'
              ? `<button class="btn btn-danger btn-sm" onclick="purgeTenantAdmin('${t.id}','${escapeHtml(t.name)}','${escapeHtml(t.schema_name)}')">清空</button>`
              : ''}
        </td>
```

同时改状态 badge（约 214 行）让 `deleting` 显示黄色 + 提示文案：

把：
```javascript
        <td><span class="badge ${t.status === 'active' ? 'badge-success' : 'badge-danger'}">${t.status}</span></td>
```

改成：
```javascript
        <td><span class="badge ${t.status === 'active' ? 'badge-success' : 'badge-warning'}">${t.status === 'deleting' ? '待清空' : t.status}</span></td>
```

注：如果项目没有 `badge-warning` 样式，沿用 `badge-danger` 也可，把 badge 文案改成"待清空"即可。先确认 `admin_base.html` 或 css 里有没有 `badge-warning`。

Run: `grep -rn "badge-warning\|badge-success" /Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/ /Users/liling/src/lab/hindsight-manager/static/`

如果没有 `badge-warning`，使用 `badge-danger`，文案仍写"待清空"。把上面的 `${t.status === 'active' ? 'badge-success' : 'badge-warning'}` 替换为 `${t.status === 'active' ? 'badge-success' : 'badge-danger'}`。

- [ ] **Step 3: 在 `deleteTenantAdmin` 函数之后（约 243 行附近）加 `purgeTenantAdmin` 函数**

```javascript
async function purgeTenantAdmin(id, name, schemaName) {
  const confirmed = await showPurgeConfirmDialog(name, schemaName);
  if (!confirmed) return;
  const resp = await apiFetch(`/admin/api/tenants/${id}/purge`, { method: "POST" });
  if (!resp) return;
  if (resp.ok) {
    const data = await resp.json();
    alert(`已清空租户 "${name}"（schema_dropped=${data.schema_dropped}）`);
    loadTenants(_tenantPage);
  } else if (resp.status === 409) {
    const data = await resp.json();
    alert(`无法清空：${data.detail || "状态不对"}`);
  } else {
    alert("清空失败");
  }
}

function showPurgeConfirmDialog(name, schemaName) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-dialog">
        <h3>彻底清空租户</h3>
        <p>此操作不可撤销，将永久删除 schema <code>${escapeHtml(schemaName)}</code> 下的所有业务数据。元数据会保留以便审计。</p>
        <p>请输入租户名 <strong>${escapeHtml(name)}</strong> 以确认：</p>
        <input type="text" id="purge-confirm-input" class="search-input" style="width:100%;margin:8px 0;" autocomplete="off">
        <div class="modal-actions">
          <button class="btn" id="purge-cancel">取消</button>
          <button class="btn btn-danger" id="purge-confirm" disabled>确认清空</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const input = overlay.querySelector("#purge-confirm-input");
    const confirmBtn = overlay.querySelector("#purge-confirm");
    const cancelBtn = overlay.querySelector("#purge-cancel");

    const close = (result) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close(false);
    };
    document.addEventListener("keydown", onKey);

    input.addEventListener("input", () => {
      confirmBtn.disabled = input.value.trim() !== name;
    });
    confirmBtn.addEventListener("click", () => close(true));
    cancelBtn.addEventListener("click", () => close(false));
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(false);
    });
    setTimeout(() => input.focus(), 0);
  });
}
```

- [ ] **Step 4: 加 modal 样式（如果项目没有）**

Run: `grep -rn "modal-overlay\|modal-dialog" /Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/ /Users/liling/src/lab/hindsight-manager/static/`

如果没有，在 `static/admin.js` 末尾（或更合适：加一个 `<style>` 注入到 `templates/admin_base.html`），追加：

```css
.modal-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-dialog {
  background: #fff; padding: 24px; border-radius: 8px;
  max-width: 480px; width: 90%;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}
.modal-dialog h3 { margin-top: 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.modal-dialog code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
```

建议加到 `templates/admin_base.html` 的 `<style>` 块或独立的 css 文件。先看 `admin_base.html` 结构再定。

- [ ] **Step 5: 手动验证（无单测，UI 改动）**

Run dev server: `uvicorn hindsight_manager.main:app --reload --port 8001`

打开 `http://localhost:8001/admin/tenants`，登录管理员账号，验证：

1. 创建一个新租户（active 状态）→ 只看到"删除"按钮
2. 点"删除" → 行变成 deleting 状态，badge 显示"待清空"，按钮变成"清空"
3. 点"清空" → 弹窗出现，输入框为空时确认按钮禁用
4. 输入错误的租户名 → 确认按钮仍禁用
5. 输入正确的租户名 → 确认按钮启用，点击后：
   - alert 显示成功，schema_dropped=true 或 false
   - 该行从列表消失（DELETED 被过滤）
6. psql 验证 schema 真的被 DROP：`psql -d hindsight_dev -c "\dn"` 不再有 `tenant_xxx`
7. 审计日志页 `/admin/audit-logs` 能看到 `tenant.purge` 记录

- [ ] **Step 6: 提交**

```bash
git add static/admin.js hindsight_manager/templates/admin_base.html hindsight_manager/templates/admin_tenants.html
git commit -m "feat: add purge button with name-typing confirmation modal"
```

---

## Task 6: 全量回归 + 手动验证

**Files:** 无修改，纯验证

- [ ] **Step 1: 跑全量测试**

Run: `uv run pytest -v`
Expected: 全套 PASS，无回归

- [ ] **Step 2: 跑 migration 在干净库**

Run: `alembic downgrade base && alembic upgrade head`
Expected: 全部 migration 干净跑通，005 加 deleted 值

⚠️ 注意：`downgrade base` 会清空所有数据。在生产或共享环境前先确认。

- [ ] **Step 3: 端到端手动验证**

按 Task 5 Step 5 的清单跑一遍。

- [ ] **Step 4: 端到端 CLI 验证**

```bash
# 创建租户
uv run hindsight-manager tenant create --name "Purge Test"
# 软删除
uv run hindsight-manager tenant delete <id>
# 清空
uv run hindsight-manager tenant purge <id>
# 预期输出: 已清空租户 <id>（schema_dropped=true）。

# 再次清空（已 DELETED）
uv run hindsight-manager tenant purge <id>
# 预期: 退出码 1，stderr 提示状态不对
```

- [ ] **Step 5: 最终提交（如有遗漏的 fix）**

```bash
git status
# 如果有未提交的修改：
git add -p
git commit -m "fix: address issues from end-to-end verification"
```

---

## Self-Review Notes

**Spec coverage 核对：**
- ✅ `TenantStatus.DELETED` + migration → Task 1
- ✅ `POST /admin/api/tenants/{id}/purge` 接口 → Task 2
- ✅ DROP SCHEMA + 状态检查 + 防注入 + 审计 → Task 2
- ✅ 列表过滤 DELETED → Task 3
- ✅ CLI purge 命令 → Task 4
- ✅ UI 按钮 + 手打名确认 → Task 5
- ✅ 测试覆盖：403/404/409(×2)/success/schema_missing/invalid_name/audit → Task 2 Step 1
- ✅ 并发：通过 SELECT FOR UPDATE（实现里用，测试通过 mock 隐含覆盖）
- ✅ 手动验证清单 → Task 5 Step 5 + Task 6

**Placeholder scan：** 无 TBD/TODO；每个步骤有具体代码。

**Type consistency：** `TenantStatus.DELETED` 在 Task 1 定义，Task 2/3 使用；`schema_dropped` 字段在 Task 2/4/5 一致；端点路径 `POST /admin/api/tenants/{id}/purge` 在 Task 2/4/5 一致。
