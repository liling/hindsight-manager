# API Key 改名功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 owner 在仪表盘租户卡片内通过编辑图标 + 模态框修改非系统 API Key 的名称。

**Architecture:** 后端新增 `PATCH /tenants/{tenant_id}/api-keys/{key_id}` 端点，复用现有 `_require_owner` 权限校验，对系统 key 显式拒绝；前端在 `renderApiKeysList` 中给非系统 key 名称旁渲染编辑按钮，点击弹出复用现有 modal 模式的 `#rename-apikey-modal`，成功后局部刷新 API key 列表。

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy async（后端）；原生 JS + Jinja2 + CSS（前端）；pytest + httpx AsyncClient + unittest.mock（测试）

## Global Constraints

- 权限：复用 `_require_owner(session, current_user, tenant_id)` —— 仅 owner 可改名
- 校验：`name.strip()`，长度 1-255，错误信息 `"名称长度需在 1-255 之间"`，HTTP 422
- 系统 key 拒绝：`is_system=True` 时返回 403 `"System API key cannot be renamed"`
- 跨租户隔离：查询同时过滤 `ApiKey.id == key_id AND ApiKey.tenant_id == tenant_id`，跨租户访问返回 404（避免泄露存在性）
- 编辑图标仅在非系统 key 上渲染（前端 + 后端双重防护）
- 名称经 `escapeHtml` 渲染、经 `JSON.stringify` 注入模态框（XSS 与语法安全）
- 成功后只调 `loadApiKeys(tenantId)` 局部刷新面板，不 `window.location.reload()`
- 与现有租户改名交互（`showRenameModal`/`hideRenameModal`/`renameTenant`）的写法完全对齐

---

## File Structure

| 文件 | 改动类型 | 责任 |
|---|---|---|
| `hindsight_manager/api/api_keys.py` | Modify | 新增 `UpdateApiKeyRequest` 模型与 PATCH 端点 |
| `tests/test_tenants_api.py` | Modify | 在文件末尾追加 8 个 API key 改名测试 |
| `hindsight_manager/templates/dashboard.html` | Modify | 在 `#rename-modal` 之后插入 `#rename-apikey-modal` |
| `hindsight_manager/static/style.css` | Modify | 新增 `.api-key-edit-btn` 样式 |
| `hindsight_manager/static/app.js` | Modify | 新增 3 个函数 + 修改 `renderApiKeysList` 加编辑按钮 |

---

## Task 1: 后端 PATCH 端点 + 8 个测试（TDD）

**Files:**
- Modify: `hindsight_manager/api/api_keys.py`（在 `revoke_api_key` 函数之后追加 PATCH 端点；在 `CreateApiKeyRequest` 之后追加 `UpdateApiKeyRequest`）
- Test: `tests/test_tenants_api.py`（在文件末尾追加 8 个测试）

**Interfaces:**
- Consumes: `ApiKey` 模型（`hindsight_manager/models/api_key.py`，已有字段 `id/tenant_id/key_hash/key_prefix/name/is_system/encrypted_key/created_at/last_used_at`）、`_require_owner`（`api/api_keys.py:27`）、`ApiKeyResponse`（`api/api_keys.py:46`）
- Produces: `PATCH /tenants/{tenant_id}/api-keys/{key_id}` 端点；`UpdateApiKeyRequest(name: str)` 模型

- [ ] **Step 1: 写 8 个失败测试**

打开 `tests/test_tenants_api.py`，在文件末尾追加以下代码块。需要先在文件顶部追加一个 `_make_api_key` 辅助函数（紧随 `_make_tenant` 之后）：

```python
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
```

然后在文件末尾追加 8 个测试：

```python
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
```

- [ ] **Step 2: 运行测试，确认全部失败**

Run:
```bash
uv run pytest tests/test_tenants_api.py -v -k "update_api_key"
```

Expected: 8 个测试全部 FAIL（端点不存在，返回 404 / 405 而非预期状态码）

- [ ] **Step 3: 实现 `UpdateApiKeyRequest` 模型**

打开 `hindsight_manager/api/api_keys.py`，在 `class CreateApiKeyRequest(BaseModel):` 那行（约 42-43 行）之后追加：

```python
class UpdateApiKeyRequest(BaseModel):
    name: str
```

- [ ] **Step 4: 实现 PATCH 端点**

在 `hindsight_manager/api/api_keys.py` 中，紧接 `revoke_api_key` 函数（约 130 行 `return {"ok": True}` 之后）追加：

```python
@router.patch("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    req: UpdateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if api_key.is_system:
        raise HTTPException(status_code=403, detail="System API key cannot be renamed")

    trimmed = req.name.strip()
    if not (1 <= len(trimmed) <= 255):
        raise HTTPException(status_code=422, detail="名称长度需在 1-255 之间")
    api_key.name = trimmed
    await session.commit()
    await session.refresh(api_key)

    def _fmt(v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return ApiKeyResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        is_system=api_key.is_system,
        created_at=_fmt(api_key.created_at),
        last_used_at=_fmt(api_key.last_used_at) if api_key.last_used_at else None,
    )
```

- [ ] **Step 5: 运行测试，确认全部通过**

Run:
```bash
uv run pytest tests/test_tenants_api.py -v -k "update_api_key"
```

Expected: 8 个测试全部 PASS

- [ ] **Step 6: 跑一次整个文件，确保没有回归**

Run:
```bash
uv run pytest tests/test_tenants_api.py -v
```

Expected: 所有测试（含原有租户改名测试 + 8 个新测试）全部 PASS

- [ ] **Step 7: 提交**

```bash
git add hindsight_manager/api/api_keys.py tests/test_tenants_api.py
git commit -m "feat: add PATCH endpoint for renaming non-system API keys"
```

---

## Task 2: 前端模态框 + 编辑按钮 + JS（端到端交互）

**Files:**
- Modify: `hindsight_manager/templates/dashboard.html`（在 `#rename-modal` 之后插入 `#rename-apikey-modal`）
- Modify: `hindsight_manager/static/style.css`（追加 `.api-key-edit-btn` 样式）
- Modify: `hindsight_manager/static/app.js`（修改 `renderApiKeysList` + 新增 3 个函数）

**Interfaces:**
- Consumes: Task 1 的 `PATCH /tenants/{tenant_id}/api-keys/{key_id}` 端点；现有 `loadApiKeys(tenantId)` 函数（`app.js:134`）；现有 `escapeHtml` 函数（`app.js:183`）
- Produces: 全局 JS 函数 `showRenameApikeyModal(tenantId, keyId, currentName)`、`hideRenameApikeyModal()`、`renameApiKey(event)`；DOM 节点 `#rename-apikey-modal`、`#rename-apikey-name`、`#rename-apikey-id`、`#rename-apikey-tenant`

- [ ] **Step 1: 在 `dashboard.html` 加模态框**

打开 `hindsight_manager/templates/dashboard.html`，找到 `#rename-modal` 的闭合 `</div>`（约第 96 行）。在该 `</div>` 之后、`<div id="apikey-modal" ...>` 之前插入：

```html
<div id="rename-apikey-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideRenameApikeyModal()"></div>
    <div class="modal-content">
        <h3>重命名 API Key</h3>
        <form id="rename-apikey-form" onsubmit="renameApiKey(event)">
            <div class="form-group">
                <label for="rename-apikey-name">名称</label>
                <input type="text" id="rename-apikey-name" name="name" required placeholder="输入新名称">
                <input type="hidden" id="rename-apikey-id">
                <input type="hidden" id="rename-apikey-tenant">
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="hideRenameApikeyModal()">取消</button>
                <button type="submit" class="btn btn-primary">保存</button>
            </div>
        </form>
    </div>
</div>
```

- [ ] **Step 2: 在 `style.css` 加 `.api-key-edit-btn`**

打开 `hindsight_manager/static/style.css`，在 `.tenant-edit-btn:hover { ... }` 那行（约第 417 行）之后追加：

```css
.api-key-edit-btn {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-muted);
    padding: 2px;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    vertical-align: middle;
    margin-left: 6px;
    transition: color 0.15s, background 0.15s;
}
.api-key-edit-btn:hover { color: var(--text-primary); background: var(--border); }
```

- [ ] **Step 3: 修改 `renderApiKeysList` 加编辑按钮**

打开 `hindsight_manager/static/app.js`，定位到 `renderApiKeysList` 函数中渲染 `.api-key-item-name` 那一行（约第 166 行），原代码：

```javascript
        <span class="api-key-item-name">${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}</span>
```

替换为：

```javascript
        <span class="api-key-item-name">${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}${!k.is_system ? ` <button type="button" class="api-key-edit-btn" title="重命名" aria-label="重命名" onclick="showRenameApikeyModal('${tenantId}', '${k.id}', ${JSON.stringify(k.name)})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg></button>` : ''}</span>
```

- [ ] **Step 4: 新增 3 个 JS 函数**

打开 `hindsight_manager/static/app.js`，定位到 `hideRenameModal` 函数（约第 78-80 行）。在 `hideRenameModal` 函数闭合 `}` 之后、`async function renameTenant` 之前插入以下三个函数：

```javascript
function showRenameApikeyModal(tenantId, keyId, currentName) {
  document.getElementById("rename-apikey-id").value = keyId;
  document.getElementById("rename-apikey-tenant").value = tenantId;
  const input = document.getElementById("rename-apikey-name");
  input.value = currentName;
  document.getElementById("rename-apikey-modal").classList.remove("hidden");
  input.focus();
  input.select();
}

function hideRenameApikeyModal() {
  document.getElementById("rename-apikey-modal").classList.add("hidden");
}

async function renameApiKey(e) {
  e.preventDefault();
  const keyId = document.getElementById("rename-apikey-id").value;
  const tenantId = document.getElementById("rename-apikey-tenant").value;
  const name = document.getElementById("rename-apikey-name").value;
  try {
    const resp = await fetch(`/tenants/${tenantId}/api-keys/${keyId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name }),
    });
    if (resp.ok) {
      hideRenameApikeyModal();
      loadApiKeys(tenantId);
    } else {
      const data = await resp.json().catch(() => ({}));
      alert(data.detail || "重命名失败");
    }
  } catch (err) {
    alert("网络错误，重命名失败");
  }
}
```

- [ ] **Step 5: 手动验证**

启动开发服务器：
```bash
uvicorn hindsight_manager.main:app --reload --port 8001
```

浏览器打开 `http://localhost:8001/`，登录后：
1. 找到任意租户卡片，展开 API Key 面板
2. **场景 A**：若列表中已有非系统 key，跳到第 4 步；否则点击「创建 API Key」创建一个
3. **场景 B**：确认系统 key 行没有编辑图标（只有「系统」badge）
4. 点击非系统 key 名称旁的铅笔图标 → 模态框弹出，输入框预填当前名称且全选
5. **场景 C**：清空输入框点保存 → 弹出「名称长度需在 1-255 之间」
6. **场景 D**：输入新名称「测试改名」点保存 → 模态框关闭，列表中名称已更新
7. **场景 E**：刷新页面确认名称持久化

Expected: 所有场景按描述工作

- [ ] **Step 6: 提交**

```bash
git add hindsight_manager/templates/dashboard.html hindsight_manager/static/style.css hindsight_manager/static/app.js
git commit -m "feat: add rename UI for API keys in dashboard tenant card"
```

---

## Verification

实现完成后整体回归：

- [ ] **后端全测**

```bash
uv run pytest tests/test_tenants_api.py -v
```

Expected: 全部 PASS（原有 + 8 个新增）

- [ ] **全量测试**

```bash
uv run pytest
```

Expected: 全部 PASS，无回归

- [ ] **手动端到端验证**（已在 Task 2 Step 5 完成）

- [ ] **一致性检查**：与租户改名（`showRenameModal`/`hideRenameModal`/`renameTenant`）的代码风格、校验规则、错误提示完全对齐
