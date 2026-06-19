# 共享记忆库（成员管理 UI）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 dashboard 每个 tenant 卡片增加"成员"slide-out 面板，让 owner 与 member 都能查看成员列表，owner 还能添加/移除/改角色——纯前端增量，后端零改动。

**Architecture:** 复用现有 `.api-keys-panel` slide-out 模式与 `/tenants/{id}/members` API。把 `_activeApiKeysTenantId` 重构为统一的 `_activePanel = {tenantId, type}` 状态，使 API Keys 与 members 面板互斥展开。模板渲染按钮 + 空容器，成员行通过 JS fetch + 渲染；按当前用户在卡片上的 role（owner/member）决定是否渲染管理控件。

**Tech Stack:** FastAPI + Jinja2（已存在，仅模板调整）；原生 JS（已存在，仅 app.js 增量）；pytest + httpx ASGITransport + unittest.mock（新增测试）。

## Global Constraints

- **后端零改动**：`hindsight_manager/api/members.py`、models、migrations 不允许触碰。如发现端点行为与本计划描述不一致，停下来报告（不要改后端）。
- **UI 文案使用简体中文**，与现有 dashboard 一致（"成员"、"添加成员"、"移除"、"改角色"）。
- **错误反馈沿用现有模式**：`alert()` + 表单内联红字，不引入 toast 库。
- **不引入新前端依赖**：纯原生 JS。
- **测试用 mock，不依赖真实 PostgreSQL**：参考 `tests/test_pages.py` 的 `app.dependency_overrides` 模式。
- **所有 commit 走项目惯例**：`feat:` / `test:` / `refactor:` 前缀，简体中文/英文均可（看 git log 现状混合使用）。

## File Structure

| 文件 | 角色 |
|---|---|
| `tests/test_members_api.py` | 新建。后端 /members API 的烟雾测试（owner/member/非成员 的 GET 权限；POST/DELETE/PATCH 的 200/403/404/409）。 |
| `hindsight_manager/templates/dashboard.html` | 修改。每个 tenant 卡片的 `.tenant-actions` 内新增"成员"按钮（owner 和 member 都可见，不放在 `{% if t.role == 'owner' %}` 块内）；每个卡片下新增 `<div id="members-panel-{id}">` 容器。 |
| `hindsight_manager/static/app.js` | 修改。新增 `toggleMembers / loadMembers / renderMembersPanel / addMember / removeMember / changeMemberRole`；把 `_activeApiKeysTenantId` 重构为 `_activePanel`（含 type 字段）。 |
| `hindsight_manager/static/style.css` | 修改。新增 `.members-panel`（与 `.api-keys-panel` 共享样式声明）、`.role-badge`、`.member-row`、`.member-actions`、`.member-add-form`、`.member-error` 等少量类。 |
| `hindsight_manager/api/members.py`、models/*、migrations/* | **零改动**。 |

---

## Task 1: 后端 /members API 烟雾测试

后端已实现，本任务补齐测试覆盖（spec §5 要求）。采用 TDD 顺序：先写测试，运行；如全部通过即验证后端行为符合本计划假设；如任一失败，停下报告（不修后端）。

**Files:**
- Create: `tests/test_members_api.py`

**Interfaces:**
- Consumes: `hindsight_manager.main:app`、`hindsight_manager.db.get_session`、`hindsight_manager.auth.dependencies.get_current_user`（通过 `app.dependency_overrides`）
- Produces: `tests/test_members_api.py`（覆盖 11 个用例，详见 spec §5）

- [ ] **Step 1: 新建测试文件**

创建 `tests/test_members_api.py`：

```python
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


def _login_as(user_id: str, username: str):
    app.dependency_overrides[get_current_user] = lambda: _make_user(user_id, username)


# ---------- GET /tenants/{id}/members ----------

@pytest.mark.asyncio
async def test_list_members_as_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    other_membership = _make_membership(MEMBER_ID, TENANT_ID, MemberRole.MEMBER)
    membership_result = MagicMock()
    membership_result.scalar_one_or_none.return_value = owner_membership

    list_rows = [
        (owner_membership, _make_user(OWNER_ID, "owner")),
        (other_membership, _make_user(MEMBER_ID, "member")),
    ]
    list_result = MagicMock()
    list_result.all.return_value = list_rows

    _override_session_side_effect([membership_result, list_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/members")
    assert resp.status_code == 200
    body = resp.json()
    usernames = [m["username"] for m in body]
    assert "owner" in usernames and "member" in usernames


@pytest.mark.asyncio
async def test_list_members_as_member(client: AsyncClient):
    _login_as(MEMBER_ID, "member")
    membership_result = MagicMock()
    membership_result.scalar_one_or_none.return_value = _make_membership(
        MEMBER_ID, TENANT_ID, MemberRole.MEMBER
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
    membership_result.scalar_one_or_none.return_value = None
    _override_session_side_effect([membership_result])

    resp = await client.get(f"/tenants/{TENANT_ID}/members")
    assert resp.status_code == 404


# ---------- POST /tenants/{id}/members ----------

@pytest.mark.asyncio
async def test_add_member_by_owner(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    # _require_owner does one query (membership + tenant join), then target user lookup,
    # then existing-membership check.
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    owner_join_result = MagicMock()
    owner_join_result.one_or_none.return_value = (
        owner_membership,
        _make_tenant(TENANT_ID),
    )

    target_user_result = MagicMock()
    target_user_result.scalar_one_or_none.return_value = _make_user(TARGET_USER_ID, "newbie")

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None

    mock_session = _override_session_side_effect(
        [owner_join_result, target_user_result, existing_result]
    )

    resp = await client.post(
        f"/tenants/{TENANT_ID}/members",
        json={"username": "newbie", "role": "member"},
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == "newbie"
    assert resp.json()["role"] == "member"
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


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

    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = None

    _override_session_side_effect([join_result, target_result])

    resp = await client.post(
        f"/tenants/{TENANT_ID}/members",
        json={"username": "ghost", "role": "member"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_duplicate_member(client: AsyncClient):
    _login_as(OWNER_ID, "owner")
    owner_membership = _make_membership(OWNER_ID, TENANT_ID, MemberRole.OWNER)
    join_result = MagicMock()
    join_result.one_or_none.return_value = (owner_membership, _make_tenant(TENANT_ID))

    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = _make_user(TARGET_USER_ID, "newbie")

    existing = _make_membership(TARGET_USER_ID, TENANT_ID, MemberRole.MEMBER)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing

    _override_session_side_effect([join_result, target_result, existing_result])

    resp = await client.post(
        f"/tenants/{TENANT_ID}/members",
        json={"username": "newbie", "role": "member"},
    )
    assert resp.status_code == 409


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
```

- [ ] **Step 2: 运行测试，验证全绿**

Run: `uv run pytest tests/test_members_api.py -v`

Expected: 11 passed。如任一 fail，停下报告——后端行为与本计划假设不符，需用户决策（按 spec "后端零改动"）。

- [ ] **Step 3: 提交**

```bash
git add tests/test_members_api.py
git commit -m "test: add smoke tests for /tenants/{id}/members endpoints"
```

---

## Task 2: HTML 与 CSS 脚手架（按钮 + 空容器 + 样式）

仅加结构与样式，按钮 onclick 指向下一任务实现的 `toggleMembers`。本任务结束时页面已经能显示按钮，但点击会报 `toggleMembers is not defined`——这是预期的，下一任务补 JS。

**Files:**
- Modify: `hindsight_manager/templates/dashboard.html`
- Modify: `hindsight_manager/static/style.css`

**Interfaces:**
- Consumes: 现有模板 `{{ t.id }}`、`{{ t.role }}`、`{{ user.id }}`
- Produces: dashboard 每个 tenant 卡片渲染一个"成员"按钮 + `members-panel-{id}` 空容器；CSS 提供 `.members-panel`、`.member-row`、`.role-badge`、`.member-actions`、`.member-add-form`、`.member-error` 类

- [ ] **Step 1: 在 dashboard.html 的 `.tenant-actions` 内添加"成员"按钮**

定位 `hindsight_manager/templates/dashboard.html` 第 40-46 行的 `.tenant-actions` 块，**在 `{% if t.role == 'owner' %}` 之前**插入"成员"按钮（确保 owner 和 member 都能看到）：

```html
<div class="tenant-actions">
    <button class="btn btn-primary btn-sm" onclick="enterConsole('{{ t.id }}', '{{ t.schema_name }}')">进入控制台</button>
    <button class="btn btn-secondary btn-sm" onclick="toggleMembers('{{ t.id }}', '{{ t.role }}', '{{ user.id }}')">成员</button>
    {% if t.role == 'owner' %}
    <button class="btn btn-secondary btn-sm" onclick="toggleApiKeys('{{ t.id }}')">API Keys</button>
    <button class="btn btn-danger btn-sm" onclick="deleteTenant('{{ t.id }}', '{{ t.name }}')">删除</button>
    {% endif %}
</div>
```

- [ ] **Step 2: 在 dashboard.html 的 api-keys-panel 后添加 members-panel 容器**

定位第 48 行 `<div id="api-keys-panel-{{ t.id }}" class="api-keys-panel" style="display:none"></div>`，**紧接其下**添加：

```html
<div id="members-panel-{{ t.id }}" class="members-panel" style="display:none"></div>
```

- [ ] **Step 3: 在 style.css 末尾追加样式**

打开 `hindsight_manager/static/style.css`，找到 `.api-keys-panel` 块（约第 538 行起）。在文件末尾追加：

```css
/* 共享记忆库：成员管理面板 */
.members-panel {
  margin-top: 12px;
  padding: 16px;
  background: var(--bg-secondary, #f7f8fa);
  border-radius: var(--radius, 8px);
  border: 1px solid var(--border, #e5e7eb);
}

.members-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.members-panel-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.member-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border, #eef0f3);
}

.member-row:last-child {
  border-bottom: none;
}

.member-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.role-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  background: var(--bg-tertiary, #eef0f3);
  color: var(--text-secondary, #6b7280);
}

.role-badge.role-owner {
  background: #dbeafe;
  color: #1e40af;
}

.member-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.member-actions select {
  padding: 4px 8px;
  font-size: 12px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: var(--radius-sm, 4px);
  background: var(--surface, #fff);
  color: var(--text-primary, #111);
}

.member-add-form {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border, #e5e7eb);
  align-items: center;
  flex-wrap: wrap;
}

.member-add-form input,
.member-add-form select {
  padding: 6px 10px;
  font-size: 13px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: var(--radius-sm, 4px);
  background: var(--surface, #fff);
  color: var(--text-primary, #111);
}

.member-add-form input {
  flex: 1;
  min-width: 160px;
}

.member-error {
  width: 100%;
  color: var(--danger, #dc2626);
  font-size: 12px;
  margin-top: 4px;
}

.member-empty {
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}
```

- [ ] **Step 4: 启动 dev server，肉眼验证按钮显示**

Run: `uvicorn hindsight_manager.main:app --reload --port 8001`

登录后访问 `/dashboard`，验证：
- 每个 tenant 卡片在"进入控制台"右侧、"API Keys"左侧（仅 owner 卡片）出现"成员"按钮
- owner 卡片和 member 卡片（如果当前用户是某 tenant 的 member）都看到"成员"按钮
- 点按钮会触发 `toggleMembers is not defined` 错误（预期，下一任务实现）

- [ ] **Step 5: 提交**

```bash
git add hindsight_manager/templates/dashboard.html hindsight_manager/static/style.css
git commit -m "feat: add members panel button and CSS scaffolding to dashboard"
```

---

## Task 3: JS 读取流——面板状态重构 + toggleMembers + loadMembers + renderMembersPanel

实现面板互斥状态机和只读视图。本任务结束时：点击"成员"按钮会展开面板并显示成员列表；owner 看到的列表行暂不带管理控件（下个任务加）；member 看到只读列表。

**Files:**
- Modify: `hindsight_manager/static/app.js`

**Interfaces:**
- Consumes: Task 2 的 `<button onclick="toggleMembers(tenantId, role, currentUserId)">`、`<div id="members-panel-{id}">`、GET `/tenants/{id}/members`（返回 `{user_id, username, role}[]`）
- Produces: 全局函数 `toggleMembers(tenantId, role, currentUserId)`、`loadMembers(tenantId, role, currentUserId)`、`renderMembersPanel(panel, tenantId, members, role, currentUserId)`；`_activePanel = {tenantId, type}` 状态变量；改写 `toggleApiKeys` 使用同一状态

- [ ] **Step 1: 重构 `_activeApiKeysTenantId` 为 `_activePanel`**

打开 `hindsight_manager/static/app.js`。第 1 行的 `let _activeApiKeysTenantId = null;` 改为：

```javascript
let _activePanel = null; // { tenantId: string, type: 'api-keys' | 'members' }
```

- [ ] **Step 2: 改写 `toggleApiKeys` 使用新状态**

定位现有 `function toggleApiKeys(tenantId)`（第 69 行起），整体替换为：

```javascript
function _closePanel() {
  if (!_activePanel) return;
  const prevPanel = document.getElementById(
    _activePanel.type === 'api-keys'
      ? `api-keys-panel-${_activePanel.tenantId}`
      : `members-panel-${_activePanel.tenantId}`
  );
  const prevCard = document.getElementById(`tenant-card-${_activePanel.tenantId}`);
  if (prevPanel) prevPanel.style.display = 'none';
  if (prevCard) prevCard.classList.remove('has-panel');
  _activePanel = null;
}

function toggleApiKeys(tenantId) {
  const panel = document.getElementById(`api-keys-panel-${tenantId}`);
  const card = document.getElementById(`tenant-card-${tenantId}`);
  if (!panel) return;

  if (_activePanel && _activePanel.tenantId === tenantId && _activePanel.type === 'api-keys') {
    _closePanel();
    return;
  }

  _closePanel();
  _activePanel = { tenantId, type: 'api-keys' };
  card.classList.add('has-panel');
  panel.style.display = 'block';
  loadApiKeys(tenantId);
}
```

- [ ] **Step 3: 在 `hideApiKeyModal` 里改用新状态**

定位现有 `function hideApiKeyModal()`（约第 164 行），把其中：

```javascript
  if (_activeApiKeysTenantId) {
    loadApiKeys(_activeApiKeysTenantId);
  }
```

替换为：

```javascript
  if (_activePanel && _activePanel.type === 'api-keys') {
    loadApiKeys(_activePanel.tenantId);
  }
```

- [ ] **Step 4: 在文件末尾追加 `toggleMembers`、`loadMembers`、`renderMembersPanel`**

在 `hindsight_manager/static/app.js` 末尾追加：

```javascript
// ============ 成员管理面板 ============

function toggleMembers(tenantId, role, currentUserId) {
  const panel = document.getElementById(`members-panel-${tenantId}`);
  const card = document.getElementById(`tenant-card-${tenantId}`);
  if (!panel) return;

  if (_activePanel && _activePanel.tenantId === tenantId && _activePanel.type === 'members') {
    _closePanel();
    return;
  }

  _closePanel();
  _activePanel = { tenantId, type: 'members' };
  card.classList.add('has-panel');
  panel.style.display = 'block';
  loadMembers(tenantId, role, currentUserId);
}

async function loadMembers(tenantId, role, currentUserId) {
  const panel = document.getElementById(`members-panel-${tenantId}`);
  panel.innerHTML = '<div class="member-empty">加载中...</div>';

  try {
    const resp = await fetch(`/tenants/${tenantId}/members`, { credentials: 'include' });
    if (!resp.ok) {
      panel.innerHTML = '<div class="member-empty">加载失败，<a href="#" class="member-retry">重试</a></div>';
      panel.querySelector('.member-retry').addEventListener('click', (e) => {
        e.preventDefault();
        loadMembers(tenantId, role, currentUserId);
      });
      return;
    }
    const members = await resp.json();
    renderMembersPanel(panel, tenantId, members, role, currentUserId);
  } catch (e) {
    panel.innerHTML = '<div class="member-empty">网络错误</div>';
  }
}

function renderMembersPanel(panel, tenantId, members, role, currentUserId) {
  // 缓存上下文到 dataset，供 changeMemberRole / removeMember 在事件回调里取回
  panel.dataset.currentRole = role;
  panel.dataset.currentUserId = currentUserId;
  panel.dataset.tenantId = tenantId;

  const isOwner = role === 'owner';
  const ownerCount = members.filter(m => m.role === 'owner').length;

  let html = '<div class="members-panel-header"><h4>成员</h4></div>';

  if (members.length === 0) {
    html += '<div class="member-empty">暂无成员</div>';
    panel.innerHTML = html;
    return;
  }

  html += members.map(m => {
    const isSelf = m.user_id === currentUserId;
    const selfLastOwner = isSelf && m.role === 'owner' && ownerCount <= 1;
    const badge = m.role === 'owner'
      ? '<span class="role-badge role-owner">owner</span>'
      : '<span class="role-badge">member</span>';

    let actions = '';
    if (isOwner) {
      // 最后一个 owner 的下拉整体 disabled，防止降级导致无人管理
      const selectDisabled = selfLastOwner ? 'disabled' : '';
      actions = `<div class="member-actions">
        <select onchange="changeMemberRole('${tenantId}','${m.user_id}',this.value)" ${selectDisabled}>
          <option value="member" ${m.role === 'member' ? 'selected' : ''}>member</option>
          <option value="owner" ${m.role === 'owner' ? 'selected' : ''}>owner</option>
        </select>
        ${!isSelf ? `<button class="btn btn-danger btn-sm" onclick="removeMember('${tenantId}','${m.user_id}','${escapeHtml(m.username)}')">移除</button>` : ''}
      </div>`;
    }

    return `<div class="member-row" id="member-${m.user_id}">
      <div class="member-info">
        <span>${escapeHtml(m.username)}${isSelf ? '（你）' : ''}</span>
        ${badge}
      </div>
      ${actions}
    </div>`;
  }).join('');

  if (isOwner) {
    html += `<form class="member-add-form" onsubmit="addMember(event,'${tenantId}','${role}','${currentUserId}')">
      <input type="text" name="username" placeholder="用户名" required>
      <select name="role">
        <option value="member" selected>member</option>
        <option value="owner">owner</option>
      </select>
      <button type="submit" class="btn btn-primary btn-sm">添加</button>
      <div class="member-error" id="member-add-error-${tenantId}" style="display:none"></div>
    </form>`;
  }

  panel.innerHTML = html;
}
```

- [ ] **Step 5: 手动验证（dev server 已在 Task 2 启动，或重新启动）**

Run: `uv run pytest tests/test_members_api.py -v`（确保 Task 1 测试仍绿）

然后启动 `uvicorn hindsight_manager.main:app --reload --port 8001`，登录 dashboard：

- 点击 owner 卡片的"成员"按钮 → 面板展开，显示成员列表（含"（你）"标记 + role 徽章），底部出现"添加"表单
- 点击 member 卡片的"成员"按钮 → 面板展开，只读列表，无表单与下拉
- 同时打开 API Keys 面板和 members 面板：先开 API Keys 再点成员 → API Keys 面板自动收起
- 反之亦然
- 点同一个"成员"按钮第二次 → 面板收起

注意：本任务暂未实现 `addMember / changeMemberRole / removeMember`，触发它们会报 `is not defined`——下三个任务补。

- [ ] **Step 6: 提交**

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: add members panel read-only view with mutual-exclusion state"
```

---

## Task 4: addMember（POST 流）

实现添加成员表单的提交逻辑，包括内联错误显示。

**Files:**
- Modify: `hindsight_manager/static/app.js`

**Interfaces:**
- Consumes: Task 3 的 `<form onsubmit="addMember(event, tenantId, role, currentUserId)">`、POST `/tenants/{id}/members {username, role}`
- Produces: 全局函数 `addMember(event, tenantId, role, currentUserId)`

- [ ] **Step 1: 在 app.js 末尾追加 `addMember`**

```javascript
async function addMember(event, tenantId, role, currentUserId) {
  event.preventDefault();
  const form = event.target;
  const username = form.username.value.trim();
  const newRole = form.role.value;
  const errEl = document.getElementById(`member-add-error-${tenantId}`);
  errEl.style.display = 'none';
  errEl.textContent = '';

  if (!username) return;

  try {
    const resp = await fetch(`/tenants/${tenantId}/members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, role: newRole }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const msg = data.detail || '添加失败';
      errEl.textContent = msg === 'User not found' ? '找不到该用户'
        : msg === 'User is already a member' ? '该用户已是成员'
        : msg === 'Owner access required' ? '无权限'
        : msg;
      errEl.style.display = 'block';
      return;
    }
    form.username.value = '';
    await loadMembers(tenantId, role, currentUserId);
  } catch (e) {
    alert('网络错误');
  }
}
```

- [ ] **Step 2: 手动验证**

dev server（仍在运行或重启）。在 owner 卡片的成员面板：
- 输入不存在的用户名 → 表单下出现红字"找不到该用户"
- 输入已是成员的用户名 → 出现"该用户已是成员"
- 输入合法用户名（先在 `/admin/users` 创建一个）→ 列表立即刷新包含新成员
- 切换角色下拉到 owner 后添加 → 新成员以 owner 身份出现

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: implement addMember with inline error display"
```

---

## Task 5: changeMemberRole（PATCH 流 + 守卫）

实现角色变更，含两个守卫：最后一个 owner 不允许降级、自己降级弹 confirm 后整页 reload。

**Files:**
- Modify: `hindsight_manager/static/app.js`

**Interfaces:**
- Consumes: Task 3 的 `<select onchange="changeMemberRole(tenantId, userId, newRole)">`、Task 3 在 `renderMembersPanel` 中写入的 `panel.dataset.currentUserId` / `panel.dataset.currentRole` / `panel.dataset.tenantId`、PATCH `/tenants/{id}/members/{user_id} {role}`
- Produces: 全局函数 `changeMemberRole(tenantId, userId, newRole)`

- [ ] **Step 1: 在 app.js 末尾追加 `changeMemberRole`**

```javascript
async function changeMemberRole(tenantId, userId, newRole) {
  const panel = document.getElementById(`members-panel-${tenantId}`);
  if (!panel) return;
  const currentUserId = panel.dataset.currentUserId;
  const role = panel.dataset.currentRole;
  const isSelfDowngrade = userId === currentUserId && newRole === 'member';

  if (isSelfDowngrade) {
    if (!confirm('你将失去管理权限，确定？')) {
      // 用户取消：重渲染面板让下拉还原到真实角色
      await loadMembers(tenantId, role, currentUserId);
      return;
    }
  }

  try {
    const resp = await fetch(`/tenants/${tenantId}/members/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ role: newRole }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const msg = data.detail || '修改失败';
      alert(msg === 'Owner access required' ? '无权限' : msg);
      // 失败时下拉视觉会停在错误选项上，重渲染面板还原
      await loadMembers(tenantId, role, currentUserId);
      return;
    }
    if (isSelfDowngrade) {
      // 自降级后当前面板 role 已过期，按 spec 整页 reload
      window.location.reload();
      return;
    }
    await loadMembers(tenantId, role, currentUserId);
  } catch (e) {
    alert('网络错误');
  }
}
```

- [ ] **Step 2: 手动验证**

dev server。在 owner 卡片：
- 把另一成员从 member 改为 owner → 列表立即刷新，对方徽章变 owner
- 把对方从 owner 改回 member → 同上
- 当只剩自己一个 owner 时，自己的下拉被 disabled（无法选择 member）
- 把自己从 owner 改为 member → 弹 confirm "你将失去管理权限，确定？"
  - 取消 → 无变化
  - 确认 → 整页刷新，刷新后该 tenant 的卡片按钮变为 member 视图（只有"进入控制台"和"成员"，无 API Keys/删除）

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: implement changeMemberRole with self-downgrade and last-owner guards"
```

---

## Task 6: removeMember（DELETE 流 + 自移除守卫）

实现移除成员，含守卫：UI 不渲染自己的"移除"按钮（已在 Task 3 的 renderMembersPanel 实现）+ 二次 confirm。

**Files:**
- Modify: `hindsight_manager/static/app.js`

**Interfaces:**
- Consumes: Task 3 的 `<button onclick="removeMember(tenantId, userId, username)">`（仅非自己行渲染）、DELETE `/tenants/{id}/members/{user_id}`
- Produces: 全局函数 `removeMember(tenantId, userId, username)`

- [ ] **Step 1: 在 app.js 末尾追加 `removeMember`**

```javascript
async function removeMember(tenantId, userId, username) {
  if (!confirm(`确定移除用户 ${username} 吗？`)) return;

  try {
    const resp = await fetch(`/tenants/${tenantId}/members/${userId}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const msg = data.detail || '移除失败';
      alert(msg === 'Owner access required' ? '无权限' : msg);
      return;
    }
    const panel = document.getElementById(`members-panel-${tenantId}`);
    const role = panel.dataset.currentRole;
    const currentUserId = panel.dataset.currentUserId;
    await loadMembers(tenantId, role, currentUserId);
  } catch (e) {
    alert('网络错误');
  }
}
```

- [ ] **Step 2: 手动验证**

dev server。在 owner 卡片：
- 自己所在行不出现"移除"按钮（只有"（你）"+徽章，无下拉/移除）
- 其他成员行点"移除" → 弹 confirm "确定移除用户 X 吗？"
  - 取消 → 无变化
  - 确认 → 列表刷新，对方消失
- 移除最后一个其他成员（只剩自己）→ 列表只剩自己一行，自己无控件

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: implement removeMember with confirm and self-guard"
```

---

## Task 7: 全量回归与最终验证

无新代码，只跑测试和 spec §5 手动清单。

**Files:** 无修改

- [ ] **Step 1: 全套测试绿**

Run: `uv run pytest -v`

Expected: 全部 pass，包括 Task 1 新增的 11 个 members 测试。

- [ ] **Step 2: 按 spec §5 的 12 项手动验证清单逐项确认**

启动 dev server，登录后逐项验证（详见 spec）：

1. owner 看到"成员"按钮、点击后面板出现，控件齐全
2. owner 添加新成员（合法用户名）→ 列表实时刷新
3. owner 添加不存在用户名 → 出现"找不到该用户"
4. owner 添加已是成员的用户 → 出现"该用户已是成员"
5. owner 改其他成员角色 → 列表立即反映
6. owner 移除其他成员 → confirm 后刷新
7. owner 自己行的 [移除] 按钮不出现
8. owner 自降级 → 弹 confirm → 确认后整页刷新为 member 只读视图
9. 仅剩 1 个 owner 时，降级/移除被禁用且显示提示
10. member 进入面板：只读列表，无任何改/删/加控件
11. 切换到另一个 tenant 的 API Keys 面板时，members 面板自动收起（反之亦然）
12. 列表加载失败时显示"加载失败，[重试]"

第 9 项的实现是下拉 disabled；如果 spec 期望额外的"显示提示"文字，则需在 `renderMembersPanel` 里给最后一个 owner 行加一行小字解释——如手动验证觉得 disabled 已足够清晰则不强求文字提示，按用户实际反馈调整。

- [ ] **Step 3: 最终提交（如有调整）**

如手动验证发现任何小调整需求（文案、间距等），改完提交：

```bash
git add -p
git commit -m "fix: polish members panel based on manual verification"
```

如无调整，跳过此步。

---

## 完成标志

- 6 个 feature/test/refactor commit 全部入主分支
- `uv run pytest` 全绿
- spec §5 的 12 项手动验证清单全部通过
- 后端代码 0 行改动（`git diff master -- hindsight_manager/api/members.py hindsight_manager/models/ hindsight_manager/migrations/` 应为空）
