# Router → Service 层抽离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `api/tenants.py`、`api/api_keys.py`、`api/members.py` 三个 router 的业务逻辑下沉到 `services/` 层，消除 `_require_owner`/`_require_membership` 三份副本，把 SM4 加密、KEY 生成、Pydantic 响应构造各归一处。

**Architecture:** 新增 4 个文件（`services/membership.py` + 3 个 service），router 层仅做 HTTP 边界。Service 采用函数式风格，参数 `(session, ...)`，返回 ORM 实例（`Tenant` / `ApiKey` / `TenantMember`）。三个 router 逐个改造，每个改造前后跑全量测试做对照。

**Tech Stack:** FastAPI + SQLAlchemy 2.x async + pytest-asyncio。测试模式：`app.dependency_overrides[get_session]` 注入 mock，`session.execute.side_effect=[result1, ...]` 按顺序模拟多次查询。

## Global Constraints

- 不动 `api/admin.py`、`api/auth.py`、`api/password.py`、`api/task_monitor.py`、`api/pages.py`、`api/proxy.py`、`api/captcha.py`
- 不抽 `repositories/` 层，不引入 `schemas/` 目录，不重写测试框架
- HTTP 状态码（404/403/409/422）由 service 层直接 raise `HTTPException`，沿用项目既有约定
- 每个任务结束跑 `uv run pytest tests/ -v`，失败立刻 `git stash`/回滚
- 保持 Pydantic schemas 在 router 文件（不搬走）
- Service 函数签名风格：`async def fn(session: AsyncSession, ..., ) -> ModelClass`

## File Structure

新建：
- `hindsight_manager/services/membership.py` — `require_membership` / `require_owner`
- `hindsight_manager/services/tenant_service.py` — 5 个 endpoint 的业务逻辑
- `hindsight_manager/services/api_key_service.py` — 4 个 endpoint 的业务逻辑 + 统一 `KEY_PREFIX` / `_generate_raw_key`
- `hindsight_manager/services/member_service.py` — 5 个 endpoint 的业务逻辑
- `tests/test_api_keys_api.py` — 补齐 POST/GET/DELETE 缺失测试（T3）

改造（删除重复定义、改成调用 service）：
- `hindsight_manager/api/tenants.py` — 删除 `_require_membership`、`KEY_PREFIX`、`SYSTEM_KEY_NAME`、SM4 调用
- `hindsight_manager/api/api_keys.py` — 删除 `_require_owner`、`_generate_api_key`、`KEY_PREFIX`、两份 `_fmt` 合并为 `_fmt_dt`
- `hindsight_manager/api/members.py` — 删除 `_require_owner`

---

## Task 1: 补齐 `api_keys` endpoint 的缺失测试（基线锁定）

**为什么先做**：spec D6 决议——重构必动 POST/GET/DELETE 三个路径，重构前必须先有测试做对照。否则重构后无法证明这些路径行为不变。

**Files:**
- Create: `tests/test_api_keys_api.py`

**Interfaces:**
- Consumes: FastAPI `app`（来自 `hindsight_manager.main`），`get_session` / `get_current_user` 依赖覆盖（参考 `tests/test_tenants_api.py`）
- Produces: 6 个测试覆盖 `POST /tenants/{tenant_id}/api-keys`、`GET /tenants/{tenant_id}/api-keys`、`DELETE /tenants/{tenant_id}/api-keys/{key_id}`

**参考实现**：直接复用 `tests/test_tenants_api.py` 顶部的 helper（`_make_user`、`_make_membership`、`_make_tenant`、`_make_api_key`、`_override_session_side_effect`、`_login_as`），不要重新发明。

- [ ] **Step 1: 写文件骨架，复用 helper**

新建 `tests/test_api_keys_api.py`：

```python
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
```

- [ ] **Step 2: 写 POST /api-keys 的三个测试**

追加到同一文件：

```python
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
```

- [ ] **Step 3: 写 GET /api-keys 的两个测试**

追加：

```python
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
```

- [ ] **Step 4: 写 DELETE /api-keys/{key_id} 的两个测试**

追加：

```python
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
```

- [ ] **Step 5: 跑测试，确认全部通过（这是改造前的基线）**

Run: `uv run pytest tests/test_api_keys_api.py -v`

Expected: 7 passed

注意：如果不通过，是测试本身写错了或者 mock 顺序错了——**不要改 router 代码让它过**，测试错了就修测试。

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `uv run pytest tests/ -v`

Expected: 所有测试通过（含新加 7 个）。

- [ ] **Step 7: Commit**

```bash
git add tests/test_api_keys_api.py
git commit -m "test: establish baseline for POST/GET/DELETE /api-keys before refactor"
```

---

## Task 2: 抽 `services/membership.py`

**Files:**
- Create: `hindsight_manager/services/membership.py`

**Interfaces:**
- Produces: `require_membership(session, user, tenant_id, require_owner=False) -> tuple[TenantMember, Tenant]` 和 `require_owner(session, user, tenant_id) -> Tenant`

- [ ] **Step 1: 写 service 文件**

新建 `hindsight_manager/services/membership.py`：

```python
"""Shared membership / ownership checks for tenant-scoped endpoints."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User


async def require_membership(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
    require_owner: bool = False,
) -> tuple[TenantMember, Tenant]:
    """Return (membership, tenant) for the user on this tenant.

    Raises:
        HTTPException 404: user is not a member of the tenant.
        HTTPException 403: require_owner=True and user is not OWNER.
    """
    result = await session.execute(
        select(TenantMember, Tenant)
        .join(Tenant, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id, TenantMember.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found or you are not a member")
    membership, tenant = row
    if require_owner and membership.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")
    return membership, tenant


async def require_owner(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
) -> Tenant:
    """Convenience wrapper returning only the tenant (callers usually
    don't need the membership row)."""
    _, tenant = await require_membership(session, user, tenant_id, require_owner=True)
    return tenant
```

注意：实现差异点——三个 router 副本里 404 详情字符串不统一（`"Not found"` vs `"Tenant not found or you are not a member"`）。以 `tenants.py` 那份（更长、更准确）为准。但**不**让 router 文件级测试因为这个改变而失败——`test_list_members_as_non_member` 只断言 404 不关心 detail。检查现有测试断言只对比状态码，无影响。

- [ ] **Step 2: 确认 import 通畅，不修改任何 router**

Run: `uv run python -c "from hindsight_manager.services.membership import require_membership, require_owner; print('ok')"`

Expected: 输出 `ok`，无 ImportError。

- [ ] **Step 3: 跑全量测试确认没引入任何回归（此时 router 还没改）**

Run: `uv run pytest tests/ -v`

Expected: 与 Task 1 结束时的数量一致，全绿。

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/services/membership.py
git commit -m "refactor: add shared services/membership.py (preview, not yet wired)"
```

---

## Task 3: 改造 `api/members.py`，调用 `require_*`

**为什么先改 members 而不是 tenants**：members router 最简单（无 SM4、无 config），先验证 `require_membership`/`require_owner` 调用模式生效。

**Files:**
- Modify: `hindsight_manager/api/members.py`（删除本地 `_require_owner`，改调用 service）

**Interfaces:**
- Consumes: `require_membership`、`require_owner` from Task 2

**关键约束**（D1）：`list_members` 调 `require_membership`（**不**传 `require_owner=True`），其它 4 个 endpoint 调 `require_owner`。

**注意点**：现有 `list_members` 实现是用 `scalar_one_or_none()` 自己 inline 校验的。改成 `require_membership` 后，校验方式变了一处——原来是查 TenantMember 是否存在（不带 Tenant join），新实现查的是 join。但效果都是"非成员返回 404"，mock 测试 `test_list_members_as_non_member` 不再触发 `scalar_one_or_none()` 路径，而是走 `one_or_none()`，所以测试的 mock 返回值需要对齐。**本 step 同步改测试**。

- [ ] **Step 1: 改 list_members 的测试 mock，预期它当前会 fail**

`tests/test_members_api.py` 当前 `test_list_members_as_owner` 用 `membership_result.scalar_one_or_none.return_value = owner_membership`。新的 service 走 `one_or_none()`。先改成匹配新路径：

打开 `tests/test_members_api.py:81-127`，把 list_members 的三个测试 mock 改成：

`test_list_members_as_owner`（line 81）：
```python
membership_result = MagicMock()
membership_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))
```
（删掉 `scalar_one_or_none.return_value`，改 `one_or_none.return_value` 返回元组）

`test_list_members_as_member`（line 105）：
```python
membership_result = MagicMock()
membership_result.one_or_none.return_value = (
    _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER),
    _make_tenant(TENANT_ID),
)
```

`test_list_members_as_non_member`（line 119）：
```python
membership_result = MagicMock()
membership_result.one_or_none.return_value = None
```

跑一次测试确认 fail：`uv run pytest tests/test_members_api.py::test_list_members_as_owner tests/test_members_api.py::test_list_members_as_member tests/test_members_api.py::test_list_members_as_non_member -v`

Expected: 3 个测试 fail（member 实际还可能 pass，因为新 mock 和旧代码读到 `one_or_none` 后会进一步 deref 元组——但不重要，旧代码用 `scalar_one_or_none` 会返回 None 导致 404，所以 `as_member` 会 fail，`as_non_member` 可能 pass）。

- [ ] **Step 2: 改 `api/members.py` 替换 `_require_owner`**

修改 `hindsight_manager/api/members.py`：

1. 顶部 import 区加：
```python
from hindsight_manager.services.membership import require_membership, require_owner
```

2. 删除文件内 `_require_owner` 函数（line 40-52，整段）。

3. 把 4 处 endpoint 里的 `await _require_owner(session, current_user, tenant_id)` 改成 `await require_owner(session, current_user, tenant_id)`。

4. `list_members`（line 56-72）改写整段：

```python
@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # 任意成员可看；require_membership 不要求 OWNER
    await require_membership(session, current_user, tenant_id)

    result = await session.execute(
        select(TenantMember, User)
        .join(User, TenantMember.user_id == User.id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    return [MemberResponse(user_id=str(u.id), username=u.username, role=m.role.value) for m, u in result.all()]
```

5. 删除文件里不再使用的 `Tenant` import（如果原 import 行 `from hindsight_manager.models.tenant import Tenant` 现在没有引用——逐一确认）；`User`、`TenantMember`、`MemberRole` 仍由 list/lookup/add 使用，保留。

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/test_members_api.py -v`

Expected: 全部通过（含三个已改 mock 的 list_members 测试）。

如有失败，对照错误是 `AttributeError` 还是 status_code 不符——前者说明 mock 没改成 `one_or_none` 模式，后者说明 router 逻辑改错。

- [ ] **Step 4: 跑全量测试确认无回归**

Run: `uv run pytest tests/ -v`

Expected: 全绿。

- [ ] **Step 5: 检查 `Tenant` import 是否仍被使用**

Run: `grep -E "^from hindsight_manager.models.tenant import|^from hindsight_manager.models.user import" hindsight_manager/api/members.py`

确认 import 行只剩实际使用的名字。若 `Tenant` 不再使用，从 import 中删除；若仍用（例如 closure 内注释/类型注解），保留。

- [ ] **Step 6: Commit**

```bash
git add hindsight_manager/api/members.py tests/test_members_api.py
git commit -m "refactor: api/members.py delegates ownership to services/membership"
```

---

## Task 4: 抽 `services/api_key_service.py` + 改造 `api/api_keys.py`

**Files:**
- Create: `hindsight_manager/services/api_key_service.py`
- Modify: `hindsight_manager/api/api_keys.py`
- Modify: `tests/test_api_keys_api.py`（list 测试可能有 mock 顺序变化——见 Step 3）

**Interfaces:**
- Consumes: `require_owner` from Task 2
- Produces: `create_api_key`、`list_api_keys`、`revoke_api_key`、`update_api_key_name` 四个函数 + `KEY_PREFIX` 常量 + 公开 `generate_raw_key` helper

- [ ] **Step 1: 写 service 文件**

新建 `hindsight_manager/services/api_key_service.py`：

```python
"""Business logic for tenant-scoped API keys."""

import secrets
import uuid
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.api_key import ApiKey

KEY_PREFIX = "hsm_"


def generate_raw_key() -> tuple[str, str]:
    """Return (raw_key, sha256_hex_hash). raw_key caller-visible only once."""
    raw = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw, sha256(raw.encode()).hexdigest()


async def create_api_key(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
) -> tuple[ApiKey, str]:
    """Persist a new (non-system) API key. Returns (record, raw_key_once)."""
    raw_key, key_hash = generate_raw_key()
    api_key = ApiKey(
        tenant_id=tenant_id,
        key_hash=key_hash,
        key_prefix=raw_key[:16],
        name=name,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return api_key, raw_key


async def list_api_keys(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[ApiKey]:
    """System keys first, then by created_at desc."""
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.tenant_id == tenant_id)
        .order_by(ApiKey.is_system.desc(), ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
) -> None:
    """Delete one key. 404 if not found or belongs to another tenant."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    await session.delete(api_key)
    await session.commit()


async def update_api_key_name(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    name: str,
) -> ApiKey:
    """Rename a non-system key.

    Raises:
        HTTPException 404: key not found in this tenant.
        HTTPException 403: key is_system.
        HTTPException 422: name length not in 1..255 after trim.
    """
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if api_key.is_system:
        raise HTTPException(status_code=403, detail="System API key cannot be renamed")

    trimmed = name.strip()
    if not (1 <= len(trimmed) <= 255):
        raise HTTPException(status_code=422, detail="名称长度需在 1-255 之间")
    api_key.name = trimmed
    await session.commit()
    await session.refresh(api_key)
    return api_key
```

- [ ] **Step 2: 改造 `api/api_keys.py`**

整体替换 `hindsight_manager/api/api_keys.py` 内容为：

```python
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.user import User
from hindsight_manager.services import api_key_service
from hindsight_manager.services.membership import require_owner

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str


class UpdateApiKeyRequest(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_system: bool
    created_at: str
    last_used_at: str | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str


def _fmt_dt(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _api_key_response(k: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(k.id),
        name=k.name,
        key_prefix=k.key_prefix,
        is_system=k.is_system,
        created_at=_fmt_dt(k.created_at),
        last_used_at=_fmt_dt(k.last_used_at),
    )


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    tenant_id: uuid.UUID,
    req: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    api_key, raw_key = await api_key_service.create_api_key(session, tenant_id, req.name)
    return ApiKeyCreatedResponse(
        **_api_key_response(k=api_key).model_dump(),
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    keys = await api_key_service.list_api_keys(session, tenant_id)
    return [_api_key_response(k) for k in keys]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    await api_key_service.revoke_api_key(session, tenant_id, key_id)
    return {"ok": True}


@router.patch("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    req: UpdateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    api_key = await api_key_service.update_api_key_name(session, tenant_id, key_id, req.name)
    return _api_key_response(api_key)
```

关键变化：
- 删除本地 `KEY_PREFIX`、`_generate_api_key`、`_require_owner`、`_fmt`（两份）
- `is_system` 字段从响应保留（`ApiKeyResponse` 不变），但在 service `create_api_key` 里**不**显式设 `is_system=False`——SQLAlchemy 模型 default 即 False，行为等价；保留默认行为以减少 diff
- 日期 helper 合并成单一 `_fmt_dt`，处理 `None`（采用更严格的版本）

- [ ] **Step 3: 校验现有 `test_api_keys_api.py` 的 mock 顺序**

回顾 Task 1 写的测试：每个测试的 `side_effect` 是 join_result 在前、业务查询在后。改造后调用顺序：
- POST: `require_owner`（1 次查询） → `create_api_key`（仅 commit/refresh/add，无 select）

  Task 1 写的 POST mock 是 `[join_result]`，正好 1 个查询 ✓

- GET: `require_owner`（1） → `list_api_keys`（1 次 select）

  Task 1 写的 GET mock 是 `[join_result, list_result]`，2 个 ✓

- DELETE: `require_owner`（1） → `revoke_api_key`（1 次 select）

  Task 1 写的 DELETE mock 是 `[join_result, key_result]`，2 个 ✓

如果某项 mock 顺序错了，运行测试会报 `StopIteration`（mock 用光）或 `AttributeError`。**不需要**事先改 Task 1 的测试。

- [ ] **Step 4: 运行专项测试**

Run: `uv run pytest tests/test_api_keys_api.py tests/test_tenants_api.py -v`

Expected: 全部通过。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `uv run pytest tests/ -v`

Expected: 全绿。

- [ ] **Step 6: 检查 ApiKey model 的 is_system default**

Run: `grep -n "is_system" hindsight_manager/models/api_key.py`

确认 `is_system` 有 `default=False` 或 SQLAlchemy 默认值。若无 default、新值会是 None，则 Step 2 的 service 需要显式 `is_system=False`。

如果是后者，回到 `services/api_key_service.py` 的 `create_api_key`，把 `ApiKey(...)` 调用加一个 `is_system=False`。

- [ ] **Step 7: Commit**

```bash
git add hindsight_manager/services/api_key_service.py hindsight_manager/api/api_keys.py
git commit -m "refactor: api/api_keys.py delegates to services/api_key_service"
```

---

## Task 5: 抽 `services/tenant_service.py` + 改造 `api/tenants.py`

**这个 task 最重**——会内聚 SM4 加密 + system key 生成到 service。`create_tenant` 的逻辑分散在 `tenants.py:97-131`。

**Files:**
- Create: `hindsight_manager/services/tenant_service.py`
- Modify: `hindsight_manager/api/tenants.py`

**Interfaces:**
- Consumes: `require_membership` from Task 2; `generate_raw_key`、`KEY_PREFIX` from Task 4 (public API of `api_key_service`)

  → Task 4 已把 `generate_raw_key` 暴露为公开函数（非 `_` 前缀）。`tenant_service` 在生成 system key 时 import 它。

- Produces: `list_tenants_for_user`、`create_tenant`、`update_tenant_config`、`mark_tenant_deleting`

- [ ] **Step 1: 写 `services/tenant_service.py`**

新建 `hindsight_manager/services/tenant_service.py`：

```python
"""Business logic for tenant lifecycle and config."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.config import Settings
from hindsight_manager.crypto import encrypt_sm4
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User
from hindsight_manager.services.api_key_service import generate_raw_key

SYSTEM_KEY_NAME = "system-proxy-key"


def _encryption_key_bytes() -> bytes:
    """Read the SM4 key from settings. Raises ValueError on bad hex."""
    return bytes.fromhex(Settings().encryption_key)


async def list_tenants_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[Tenant]:
    """Tenants the user has any role on."""
    result = await session.execute(
        select(Tenant, TenantMember.role)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .where(TenantMember.user_id == user_id)
    )
    return [t for t, _ in result.all()]


async def create_tenant(
    session: AsyncSession,
    owner: User,
    name: str,
) -> Tenant:
    """Atomically create tenant + owner membership + encrypted system API key."""
    schema_name = f"tenant_{uuid.uuid4().hex[:8]}"
    tenant = Tenant(name=name, schema_name=schema_name, status=TenantStatus.ACTIVE)
    session.add(tenant)
    await session.flush()

    membership = TenantMember(user_id=owner.id, tenant_id=tenant.id, role=MemberRole.OWNER)
    session.add(membership)

    raw_key, key_hash = generate_raw_key()
    encrypted_key = encrypt_sm4(raw_key, _encryption_key_bytes())
    system_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=key_hash,
        key_prefix=raw_key[:16],
        name=SYSTEM_KEY_NAME,
        is_system=True,
        encrypted_key=encrypted_key,
    )
    session.add(system_key)

    await session.commit()
    await session.refresh(tenant)
    return tenant


async def update_tenant_config(
    session: AsyncSession,
    tenant: Tenant,
    name: str | None,
    config_patch: dict,
) -> Tenant:
    """Apply optional name change + merge config patch. Commits + refreshes."""
    if name is not None:
        trimmed = name.strip()
        if not (1 <= len(trimmed) <= 255):
            raise HTTPException(status_code=422, detail="名称长度需在 1-255 之间")
        tenant.name = trimmed

    config = tenant.config or {}
    config.update(config_patch)
    tenant.config = config
    await session.commit()
    await session.refresh(tenant)
    return tenant


async def mark_tenant_deleting(session: AsyncSession, tenant: Tenant) -> None:
    """Soft delete: status -> DELETING. Real deletion handled by task_monitor."""
    tenant.status = TenantStatus.DELETING
    await session.commit()
```

注意：
- `config.update` 现在传 `config_patch`——router 把 `req.model_dump(exclude_none=True)` 后再 pop `"name"` 的逻辑保留在 router 层（业务无关、是 Pydantic 序列化关注点）。
- 移除了原来 `tenants.py:113` 的 `token_hex(32)`，统一用 `generate_raw_key()`（用 `token_urlsafe(32)`）。这是 spec Issue 2 的决议——生成方式变了，值空间不影响（key_hash 仍是 sha256，prefix 仍是前 16 字符）。无测试断言 raw key 的具体格式，所以无回归。

- [ ] **Step 2: 改造 `api/tenants.py`**

整体替换 `hindsight_manager/api/tenants.py` 内容为：

```python
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole
from hindsight_manager.models.user import User
from hindsight_manager.services import tenant_service
from hindsight_manager.services.membership import require_membership

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    name: str


class TenantConfigUpdateRequest(BaseModel):
    name: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embeddings_provider: str | None = None
    embeddings_model: str | None = None
    embeddings_api_key: str | None = None
    embeddings_base_url: str | None = None
    reranker_provider: str | None = None
    reranker_model: str | None = None
    reranker_api_key: str | None = None


class TenantResponse(BaseModel):
    id: str
    name: str
    schema_name: str
    config: dict | None
    status: str
    created_at: str


def _tenant_response(t: Tenant) -> TenantResponse:
    return TenantResponse(
        id=str(t.id),
        name=t.name,
        schema_name=t.schema_name,
        config=t.config,
        status=t.status.value,
        created_at=str(t.created_at),
    )


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenants = await tenant_service.list_tenants_for_user(session, current_user.id)
    return [_tenant_response(t) for t in tenants]


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    req: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant = await tenant_service.create_tenant(session, current_user, req.name)
    return _tenant_response(tenant)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # require_membership 已 join 出 tenant，直接复用——避免二次查询
    _, tenant = await require_membership(session, current_user, tenant_id)
    return _tenant_response(tenant)


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_config(
    tenant_id: uuid.UUID,
    req: TenantConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await require_membership(session, current_user, tenant_id, require_owner=True)

    update_data = req.model_dump(exclude_none=True)
    name = update_data.pop("name", None)
    tenant = await tenant_service.update_tenant_config(session, tenant, name, update_data)
    return _tenant_response(tenant)


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await require_membership(session, current_user, tenant_id, require_owner=True)
    await tenant_service.mark_tenant_deleting(session, tenant)
```

关键变化：
- 删除 `KEY_PREFIX`、`SYSTEM_KEY_NAME`、`_require_membership`、`encrypt_sm4`、`Settings`、`ApiKey` 等 import（不再直接用）
- `TenantConfigUpdateRequest` 完整保留——schema 是 API 边界
- `get_tenant` 路由直接复用 `require_membership` 返回的 tenant，避免二次查询（不允许 `require_membership` 之后 service 再 select 一次）

- [ ] **Step 3: 跑全量测试**

Run: `uv run pytest tests/ -v`

Expected: 全绿。

如果 `test_tenants_api.py` 有 test fail：
- 若 fail 显示 mock 顺序错（`StopIterator`）——按 service 的实际 execute 次数调整 mock 顺序。
- PATCH 系列 `test_update_config_preserves_name` 等检查 `req.model_dump(exclude_none=True).pop("name")` —— 新实现保留了 router 这段逻辑，行为等价。

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/services/tenant_service.py hindsight_manager/services/api_key_service.py hindsight_manager/api/tenants.py
git commit -m "refactor: api/tenants.py delegates to services/tenant_service"
```

---

## Task 6: 抽 `services/member_service.py` + 改造 `api/members.py`

**Files:**
- Create: `hindsight_manager/services/member_service.py`
- Modify: `hindsight_manager/api/members.py`

**Interfaces:**
- Consumes: `require_membership` / `require_owner` from Task 2

- [ ] **Step 1: 写 service 文件**

新建 `hindsight_manager/services/member_service.py`：

```python
"""Business logic for tenant membership management."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User


async def list_members(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[tuple[TenantMember, User]]:
    """Return (member, user) tuples for all members of the tenant."""
    result = await session.execute(
        select(TenantMember, User)
        .join(User, TenantMember.user_id == User.id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    return list(result.all())


async def lookup_user(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    username: str,
) -> tuple[User, bool]:
    """Look up a user by username for membership addition.

    Returns:
        (user, is_already_member)
    Raises:
        HTTPException 404: user not found.
    """
    result = await session.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == target_user.id, TenantMember.tenant_id == tenant_id
        )
    )
    return target_user, existing.scalar_one_or_none() is not None


async def add_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    username: str,
    role: MemberRole,
) -> tuple[User, TenantMember]:
    """Add a member. Returns (user, new_membership).

    Raises:
        HTTPException 404: user not found.
        HTTPException 409: user already a member.
    """
    result = await session.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == target_user.id, TenantMember.tenant_id == tenant_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    member = TenantMember(user_id=target_user.id, tenant_id=tenant_id, role=role)
    session.add(member)
    await session.commit()
    return target_user, member


async def remove_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Delete a membership row. 404 if not found."""
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await session.delete(member)
    await session.commit()


async def update_member_role(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: MemberRole,
) -> TenantMember:
    """Change a member's role. 404 if not found.
    Caller must look up username separately if needed (returns the TenantMember).
    """
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = role
    await session.commit()
    return member
```

注意 `update_member_role` 不再 fetch `User`——原 router 末尾用 `session.get(User, user_id)` 拉 username。为保持响应包含 username，service 仍需要返回 user 信息。

回到 service `update_member_role`，再 fetch user 并一起返回：

```python
async def update_member_role(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: MemberRole,
) -> tuple[User | None, TenantMember]:
    """Returns (user, member). 404 if member not found."""
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = role
    await session.commit()

    user = await session.get(User, user_id)
    return user, member
```

- [ ] **Step 2: 改造 `api/members.py`**

整体替换 `hindsight_manager/api/members.py` 内容为：

```python
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant_member import MemberRole
from hindsight_manager.models.user import User
from hindsight_manager.services import member_service
from hindsight_manager.services.membership import require_membership, require_owner

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["members"])


class AddMemberRequest(BaseModel):
    username: str
    role: MemberRole = MemberRole.MEMBER


class UpdateRoleRequest(BaseModel):
    role: MemberRole


class MemberResponse(BaseModel):
    user_id: str
    username: str
    role: str


class MemberLookupResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    email: str | None
    is_already_member: bool


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_membership(session, current_user, tenant_id)
    pairs = await member_service.list_members(session, tenant_id)
    return [MemberResponse(user_id=str(u.id), username=u.username, role=m.role.value) for m, u in pairs]


@router.get("/members/lookup", response_model=MemberLookupResponse)
async def lookup_member(
    tenant_id: uuid.UUID,
    username: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)

    user, is_already_member = await member_service.lookup_user(session, tenant_id, username)
    return MemberLookupResponse(
        user_id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_already_member=is_already_member,
    )


@router.post("/members", response_model=MemberResponse, status_code=201)
async def add_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)

    user, _ = await member_service.add_member(session, tenant_id, req.username, req.role)
    return MemberResponse(user_id=str(user.id), username=user.username, role=req.role.value)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    await member_service.remove_member(session, tenant_id, user_id)


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateRoleRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_owner(session, current_user, tenant_id)
    user, _ = await member_service.update_member_role(session, tenant_id, user_id, req.role)
    return MemberResponse(
        user_id=str(user_id),
        username=user.username if user else "unknown",
        role=req.role.value,
    )
```

- [ ] **Step 3: 跑全量测试**

Run: `uv run pytest tests/ -v`

Expected: 全绿。

`test_add_member_by_owner` 的 mock 顺序：`[owner_join_result, target_user_result, existing_result]`（原来 3 个查询）。改造后 `add_member` 仍走 `require_owner`（1）+ `add_member` 内部 3 个查询（user lookup、existing lookup、不需要 add 后的查询）= 4 个查询。

**这里会 fail**——mock 数量不够。检查 service `add_member`：
1. `select(User).where(User.username == ...)` → target_user_result
2. `select(TenantMember).where(...)` → existing_result
3. `commit`

加上 `require_owner` 1 次 = 3 次 execute 调用。Task 3 改的测试 `test_add_member_by_owner` 已经是 3 个 mock，正好匹配 ✓（无变化）。

逐个跑各 sub-test 看 fail 的原因，若是 `StopIteration` 说明 mock 不匹配，回到测试加 mock。

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/services/member_service.py hindsight_manager/api/members.py
git commit -m "refactor: api/members.py delegates to services/member_service"
```

---

## Task 7: 最终验证 + 文件清理

- [ ] **Step 1: 跑全量测试**

Run: `uv run pytest tests/ -v`

Expected: 全绿，与重构前对照数量只增加（Task 1 新增的 7 个 api_keys 测试）。

- [ ] **Step 2: 确认无未使用 import**

Run: `uv run python -c "import hindsight_manager.api.tenants, hindsight_manager.api.api_keys, hindsight_manager.api.members; print('ok')"`

Expected: `ok`，无 ImportError。

- [ ] **Step 3: 确认模块装载顺序正常（router 注册无副作用）**

Run: `uv run python -c "from hindsight_manager.main import app; print([r.path for r in app.routes][:5])"`

Expected: 列出路由路径，且无错误。

- [ ] **Step 4: 启动应用做一次冒烟**

Run: `uv run uvicorn hindsight_manager.main:app --port 8001 &` （后台） → `curl http://localhost:8001/docs -o /dev/null -w "%{http_code}"` → kill 进程

Expected: 200（OpenAPI docs 可访问）。

- [ ] **Step 5: 完成性检查 commit（若有 lint 修复）**

如果上面任何一步清理了空行、未使用 import 等，commit：

```bash
git add hindsight_manager/
git commit -m "chore: clean up after service-layer refactor"
```

否则跳过该 step。

---

## Self-Review 检查项

执行者在合并前自查：

- [ ] `_require_owner` / `_require_membership` 不再存在于任何 router 文件
- [ ] `KEY_PREFIX` 在整个代码库唯一（只在 `services/api_key_service.py`）
- [ ] `_fmt_dt` 在 `api_keys.py` 内只剩一份
- [ ] `services/` 目录含 4 个新文件（membership、tenant_service、api_key_service、member_service）
- [ ] `uv run pytest tests/ -v` 全绿
- [ ] `crypto.encrypt_sm4` 不再被 `api/tenants.py` import（已搬至 `services/tenant_service.py`）
- [ ] 三个改造的 router 文件（`api/tenants.py`、`api/api_keys.py`、`api/members.py`）每个不超过 150 行
- [ ] 未修改：`admin.py`、`auth.py`、`password.py`、`task_monitor.py`、`pages.py`、`proxy.py`、`captcha.py`
