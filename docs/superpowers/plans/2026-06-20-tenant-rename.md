# 记忆库重命名功能 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 owner 在 dashboard 上直接修改记忆库（tenant）名称。

**Architecture:** 复用现有 `PATCH /tenants/{tenant_id}` 端点，在请求体上新增可选 `name` 字段；前端在 owner 卡片上加「重命名」按钮和轻量 modal，提交时 PATCH `{name}` 后整页 reload。

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy（后端）；Jinja2 模板 + 原生 fetch JS（前端）；pytest + httpx（测试）。

## Global Constraints

- 所有用户可见文案使用简体中文，术语保留英文。
- 后端校验：`name` trim 后长度 1–255；超出返回 422。
- 权限：仅 owner 可改（复用 `_require_membership(require_owner=True)`）。
- 不新增数据库迁移、不新增端点、不动 admin 页面。
- 项目运行命令：`uv run pytest tests/<file>::<test> -v`（后端）；`uvicorn hindsight_manager.main:app --reload --port 8001`（手动验证 UI）。

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `hindsight_manager/api/tenants.py` | 扩展 `TenantConfigUpdateRequest`、`update_tenant_config` | Modify |
| `tests/test_tenants_api.py` | 后端 PATCH name 的新测试文件 | Create |
| `hindsight_manager/templates/dashboard.html` | 加重命名按钮 + rename-modal HTML | Modify |
| `hindsight_manager/static/app.js` | 加 `showRenameModal` / `hideRenameModal` / `renameTenant` | Modify |
| `tests/test_pages.py` | 加 dashboard 重命名 UI 渲染断言 | Modify |

---

### Task 1: 后端 — PATCH /tenants/{id} 支持 name 更新

**Files:**
- Modify: `hindsight_manager/api/tenants.py`（`TenantConfigUpdateRequest` 与 `update_tenant_config`）
- Create: `tests/test_tenants_api.py`

**Interfaces:**
- Consumes: 现有 `_require_membership(session, user, tenant_id, require_owner=True)`、`_tenant_response(t)`、`get_current_user`、`get_session`
- Produces: `PATCH /tenants/{tenant_id}` 接受可选 body 字段 `name: str`；成功返回 `TenantResponse`（已存在，不变）

**测试 mock 套路（沿用 tests/test_members_api.py）：**
- `_make_user`、`_make_membership`、`_make_tenant`、`_login_as`、`_override_session_side_effect` 与 `test_members_api.py` 同名函数行为一致。
- `update_tenant_config` 路径只调用一次 `session.execute()`（在 `_require_membership` 内），返回 `(membership, tenant)` via `result.one_or_none()`。然后 `session.commit()` + `session.refresh(tenant)`。

- [ ] **Step 1: 创建测试文件 + happy path 失败测试**

Create `tests/test_tenants_api.py`:

```python
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
```

- [ ] **Step 2: 运行测试，确认失败（PATCH 还不接受 name）**

Run: `uv run pytest tests/test_tenants_api.py::test_owner_can_rename_tenant -v`
Expected: FAIL。失败原因可能是：`update_tenant_config` 把 `name` 当成 config 字段塞进 `tenant.config` dict，导致 `tenant.name` 没改、响应 `name` 仍是 "旧名"。具体表现为 `assert resp.json()["name"] == "新名"` 失败。

- [ ] **Step 3: 修改 `TenantConfigUpdateRequest` 增加 `name` 字段**

Modify `hindsight_manager/api/tenants.py`，在 `TenantConfigUpdateRequest` 类的最前面（其它字段之前）加：

```python
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
```

- [ ] **Step 4: 修改 `update_tenant_config` 处理 name**

Modify `hindsight_manager/api/tenants.py`，把 `update_tenant_config` 改为：

```python
@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_config(
    tenant_id: uuid.UUID,
    req: TenantConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = await _require_membership(session, current_user, tenant_id, require_owner=True)

    if req.name is not None:
        trimmed = req.name.strip()
        if not (1 <= len(trimmed) <= 255):
            raise HTTPException(status_code=422, detail="名称长度需在 1-255 之间")
        tenant.name = trimmed

    config = tenant.config or {}
    update_data = req.model_dump(exclude_none=True)
    update_data.pop("name", None)
    config.update(update_data)
    tenant.config = config
    await session.commit()
    await session.refresh(tenant)
    return _tenant_response(tenant)
```

注意：`update_data.pop("name", None)` 把 name 从 config 更新数据里剔除（避免它再被当成 config 字段写进 JSON）。

- [ ] **Step 5: 运行 happy path 测试，确认通过**

Run: `uv run pytest tests/test_tenants_api.py::test_owner_can_rename_tenant -v`
Expected: PASS

- [ ] **Step 6: 加 member forbidden 测试**

Append to `tests/test_tenants_api.py`:

```python
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
```

Run: `uv run pytest tests/test_tenants_api.py::test_member_cannot_rename_tenant -v`
Expected: PASS（现有 `_require_membership` 已处理 owner 检查）

- [ ] **Step 7: 加空名 / 空白名 422 测试**

Append to `tests/test_tenants_api.py`:

```python
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
```

Run: `uv run pytest tests/test_tenants_api.py::test_rename_empty_name_rejected -v`
Expected: PASS

- [ ] **Step 8: 加超长名 422 测试**

Append to `tests/test_tenants_api.py`:

```python
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
```

Run: `uv run pytest tests/test_tenants_api.py::test_rename_too_long_name_rejected -v`
Expected: PASS

- [ ] **Step 9: 加回归测试 — 只改 config 时 name 不变**

Append to `tests/test_tenants_api.py`:

```python
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
```

Run: `uv run pytest tests/test_tenants_api.py::test_update_config_preserves_name -v`
Expected: PASS

- [ ] **Step 10: 加同时改 name 和 config 测试**

Append to `tests/test_tenants_api.py`:

```python
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
```

Run: `uv run pytest tests/test_tenants_api.py::test_rename_and_update_config_together -v`
Expected: PASS

- [ ] **Step 11: 跑整个测试文件 + 现有 tenant 相关测试，确认无回归**

Run: `uv run pytest tests/test_tenants_api.py tests/test_members_api.py tests/test_tenant_purge.py tests/test_pages.py -v`
Expected: 全部 PASS

- [ ] **Step 12: Commit**

```bash
git add hindsight_manager/api/tenants.py tests/test_tenants_api.py
git commit -m "feat: allow renaming tenant via PATCH /tenants/{id}"
```

---

### Task 2: 前端 — dashboard 加重命名 UI

**Files:**
- Modify: `hindsight_manager/templates/dashboard.html`
- Modify: `hindsight_manager/static/app.js`
- Modify: `tests/test_pages.py`（加渲染断言）

**Interfaces:**
- Consumes: Task 1 的 `PATCH /tenants/{id}` 接受 `{name}`
- Produces: dashboard 上 owner 卡片显示「重命名」按钮；点击弹出 modal；提交后调 PATCH 并整页 reload

**UI 模式参照：** 现有 `create-modal` / `createTenant` / `showCreateModal` / `hideCreateModal`。

- [ ] **Step 1: 加 dashboard 渲染测试（TDD - 先失败）**

Modify `tests/test_pages.py`，在 `test_dashboard_page_renders` 函数末尾追加断言：

```python
    assert "重命名" in resp.text
    assert 'id="rename-modal"' in resp.text
    assert 'id="rename-name"' in resp.text
    assert 'id="rename-tenant-id"' in resp.text
```

Run: `uv run pytest tests/test_pages.py::test_dashboard_page_renders -v`
Expected: FAIL（"重命名" 不在页面里 / `id="rename-modal"` 不存在）

- [ ] **Step 2: dashboard.html 加重命名按钮**

Modify `hindsight_manager/templates/dashboard.html`。找到 owner 区块：

```html
{% if t.role == 'owner' %}
<button class="btn btn-secondary btn-sm" onclick="toggleApiKeys('{{ t.id }}')">API Keys</button>
<button class="btn btn-danger btn-sm" onclick="deleteTenant('{{ t.id }}', '{{ t.name }}')">删除</button>
{% endif %}
```

改为（在 API Keys 和 删除 之间插入重命名按钮）：

```html
{% if t.role == 'owner' %}
<button class="btn btn-secondary btn-sm" onclick="toggleApiKeys('{{ t.id }}')">API Keys</button>
<button class="btn btn-secondary btn-sm" onclick="showRenameModal('{{ t.id }}', '{{ t.name | e }}')">重命名</button>
<button class="btn btn-danger btn-sm" onclick="deleteTenant('{{ t.id }}', '{{ t.name }}')">删除</button>
{% endif %}
```

- [ ] **Step 3: dashboard.html 加 rename-modal**

Modify `hindsight_manager/templates/dashboard.html`。在 `create-modal` div 闭合 `</div>` 之后、`apikey-modal` div 开始之前，插入：

```html
<div id="rename-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideRenameModal()"></div>
    <div class="modal-content">
        <h3>重命名记忆库</h3>
        <form id="rename-form" onsubmit="renameTenant(event)">
            <div class="form-group">
                <label for="rename-name">名称</label>
                <input type="text" id="rename-name" name="name" required placeholder="输入新名称">
                <input type="hidden" id="rename-tenant-id">
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="hideRenameModal()">取消</button>
                <button type="submit" class="btn btn-primary">保存</button>
            </div>
        </form>
    </div>
</div>
```

- [ ] **Step 4: 运行 dashboard 渲染测试，确认通过**

Run: `uv run pytest tests/test_pages.py::test_dashboard_page_renders -v`
Expected: PASS

- [ ] **Step 5: app.js 加 rename 函数**

Modify `hindsight_manager/static/app.js`。在 `hideCreateModal` 函数之后（约第 67 行之后），插入：

```javascript
function showRenameModal(tenantId, currentName) {
  document.getElementById("rename-tenant-id").value = tenantId;
  const input = document.getElementById("rename-name");
  input.value = currentName;
  document.getElementById("rename-modal").classList.remove("hidden");
  input.focus();
  input.select();
}

function hideRenameModal() {
  document.getElementById("rename-modal").classList.add("hidden");
}

async function renameTenant(e) {
  e.preventDefault();
  const tenantId = document.getElementById("rename-tenant-id").value;
  const name = document.getElementById("rename-name").value;
  try {
    const resp = await fetch(`/tenants/${tenantId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name }),
    });
    if (resp.ok) {
      window.location.reload();
    } else {
      const err = await resp.json();
      alert(err.detail || "重命名失败");
    }
  } catch (e) {
    alert("网络错误");
  }
}
```

- [ ] **Step 6: 手动验证 UI（golden path）**

Run: `uvicorn hindsight_manager.main:app --reload --port 8001`

验证步骤：
1. 登录 → 进入 `/dashboard`
2. 在 owner 的记忆库卡片上看到「重命名」按钮
3. 点击 → modal 弹出，输入框预填当前名称并全选
4. 改名 → 点保存 → 页面 reload → 卡片标题已更新
5. 验证非 owner 成员（如有）卡片上没有「重命名」按钮
6. 验证 modal「取消」按钮和点击背景都能关闭
7. 在浏览器 Network 面板确认请求是 `PATCH /tenants/{id}` body `{"name": "..."}`

Expected: 上述全部通过。

- [ ] **Step 7: 手动验证边界 — 空名**

在重命名 modal 里清空输入框 → 点保存 → 浏览器原生 required 提示无法提交。
直接用 curl 或浏览器 devtools 发 `PATCH /tenants/{id}` body `{"name": "   "}` → 返回 422 + 中文错误。

Expected: 行为符合预期。

- [ ] **Step 8: 跑全套测试，确认无回归**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 9: Commit**

```bash
git add hindsight_manager/templates/dashboard.html hindsight_manager/static/app.js tests/test_pages.py
git commit -m "feat: add rename button and modal to dashboard tenant cards"
```

---

## Self-Review

**Spec 覆盖检查：**
- ✅ 后端扩展 PATCH 支持 name — Task 1
- ✅ 长度 1–255 校验 / 422 — Task 1 Step 4 + Step 7/8 测试
- ✅ trim 后非空 — Task 1 Step 4（`req.name.strip()` + 长度检查）
- ✅ 仅 owner 可改 — Task 1 Step 6 测试（现有 `_require_membership` 已实现）
- ✅ 同时改 name 和 config — Task 1 Step 10
- ✅ 不动 admin — 计划中无 admin 改动
- ✅ 整页 reload — Task 2 Step 5 `renameTenant` 中 `window.location.reload()`
- ✅ dashboard 加按钮 + modal — Task 2

**Placeholder 扫描：** 无 TBD/TODO，所有代码块完整。

**类型一致性：** `showRenameModal(tenantId, currentName)` 在 HTML onclick 和 JS 定义签名一致；`renameTenant`、`hideRenameModal` 命名一致；后端字段 `name`、请求方法 `PATCH` 前后端一致。
