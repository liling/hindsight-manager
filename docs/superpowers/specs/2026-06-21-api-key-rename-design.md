# API Key 改名功能设计

**日期**：2026-06-21
**范围**：仅仪表盘租户卡片内的 API Key 列表项；管理后台本次不动

## 背景与动机

仪表盘租户卡片中展开的 API Key 列表目前支持创建、复制前缀、删除，但不能修改名称。用户在创建时填错名称、或希望让名称更好地反映用途时，只能删除后重建——而删除会导致使用该 key 的应用立即失效，代价过大。

租户卡片本身已有改名能力（PATCH `/tenants/{tenant_id}` + 模态框），API Key 改名应与之保持一致的交互。

## 目标

- 让 owner 在仪表盘租户卡片内直接修改非系统 API Key 的名称
- 交互（编辑图标 + 模态框）、权限（owner-only）、校验规则（1-255 字符）均与租户改名对齐
- 系统 key 显式拒绝改名（前后端双重防护）

## 非目标

- 不在管理后台 `/admin/api-keys` 页面提供改名（用户已确认）
- 不引入版本号 / 乐观并发控制（改名是低冲突操作，YAGNI）
- 不补建审计日志（与现有用户面的创建/删除/租户改名保持一致，仅 admin 端点写审计）
- 不动现有的"原始 key 仅创建时返回一次"的安全模型

## 后端接口

**新增端点**：`PATCH /tenants/{tenant_id}/api-keys/{key_id}`（在 `hindsight_manager/api/api_keys.py` 中）

**请求体**：
```json
{ "name": "new name" }
```

**响应**：复用现有 `ApiKeyResponse` 模型（与列表项结构一致）

**实现要点**：
- 权限：复用 `_require_owner(session, current_user, tenant_id)`，与创建/删除一致
- 查询：`select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)` —— 同时过滤 tenant_id，跨租户访问返回 404
- 系统 key 拒绝：`if api_key.is_system: raise HTTPException(403, "System API key cannot be renamed")`
- 校验：`trimmed = req.name.strip()`，要求 `1 <= len(trimmed) <= 255`，否则 422，错误信息 `"名称长度需在 1-255 之间"`
- 写入：`api_key.name = trimmed` → commit → refresh
- 返回：构造 `ApiKeyResponse`（与 `list_api_keys` 中相同的字段填充方式，含 `id/name/key_prefix/is_system/created_at/last_used_at`）

**新增 Pydantic 模型**：
```python
class UpdateApiKeyRequest(BaseModel):
    name: str
```

## 前端实现

### 模态框（`templates/dashboard.html`）

紧跟现有 `#rename-modal` 之后插入 `#rename-apikey-modal`，结构与 `#rename-modal` 完全对齐：
- 三个字段：可见的 `rename-apikey-name` 文本输入 + 两个 hidden 字段 `rename-apikey-id` / `rename-apikey-tenant`
- 表单 `onsubmit="renameApiKey(event)"`
- 取消按钮 `onclick="hideRenameApikeyModal()"`

### 列表渲染（`static/app.js` 中 `renderApiKeysList`）

在 `.api-key-item-name` span 内、名称文本与可选系统 badge 之后，为非系统 key 追加编辑按钮：
```javascript
<span class="api-key-item-name">
  ${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}
  ${!k.is_system ? `<button type="button" class="api-key-edit-btn" title="重命名" aria-label="重命名" onclick="showRenameApikeyModal('${tenantId}', '${k.id}', ${JSON.stringify(k.name)})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg></button>` : ''}
</span>
```

### 新增三个 JS 函数

**`showRenameApikeyModal(tenantId, keyId, currentName)`**：
- 写入两个 hidden 字段
- 输入框预填 `currentName`，并 `focus()` + `select()`（与 `showRenameModal` 一致，便于直接覆盖）

**`hideRenameApikeyModal()`**：仅切换 `hidden` 类

**`renameApiKey(event)`**：
- `e.preventDefault()`
- 从 hidden 字段读出 `keyId`、`tenantId`，从输入框读出 `name`
- `fetch(\`/tenants/${tenantId}/api-keys/${keyId}\`, { method: "PATCH", headers: {"Content-Type": "application/json"}, credentials: "include", body: JSON.stringify({ name }) })`
- 成功（`resp.ok`）：`hideRenameApikeyModal()` + `loadApiKeys(tenantId)` **局部刷新面板**（不整页 reload，因为只影响列表中一项）
- 失败：解析 `resp.json().detail`，`alert(detail || "重命名失败")`
- 异常：`catch` 后 `alert("网络错误，重命名失败")`

## 视觉样式（`static/style.css`）

新增 `.api-key-edit-btn`，复用 `.tenant-edit-btn` 的视觉约定，但**始终可见**（不像租户卡片那样 hover 才显示，因为 API key 列表项视觉权重低，hover 难以发现）：
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

图标使用与租户改名相同的 Feather 风格 inline SVG（铅笔），不引入外部图标库。

## 错误处理矩阵

| 场景 | 后端响应 | 前端行为 |
|---|---|---|
| 名称空 / 全空格 / 超 255 字 | 422 `"名称长度需在 1-255 之间"` | `alert(detail)` |
| 系统 key 改名 | 403 `"System API key cannot be renamed"` | `alert(detail)` |
| key 不存在或属其他租户 | 404 `"API key not found"` | `alert(detail)` + 局部刷新 |
| 非 owner 调用 | 403（`_require_owner`） | `alert(detail)` |
| 未登录 | 401 | 由现有全局 `fetch` 处理（重定向到登录） |
| 网络错误 / 异常 | - | `alert("网络错误，重命名失败")` |

## 安全考量

- **不变更原始 key 的安全模型**：原始 key 仍然只在创建时一次性返回，DB 中只存 SHA256 hash + 前 16 字符 prefix，本次改动只动 `name` 字段
- **名称经 `escapeHtml` 渲染**：避免 XSS（与现有列表项渲染一致）
- **名称注入模态框时用 `JSON.stringify`**：规避名称含引号、反斜杠导致的 JS 语法错误与注入（参考近期 commit `a2cef26` 解决过的同类问题）
- **跨租户隔离**：查询同时过滤 `tenant_id`，且 `_require_owner` 已确认用户在该租户的 owner 身份
- **系统 key 双重防护**：前端不渲染按钮 + 后端 403 显式拒绝

## 测试计划

当前代码库没有专门的 `test_api_keys.py`，用户面 API key 端点（路径前缀 `/tenants/{tenant_id}/api-keys`）属于租户作用域。本次测试加到 `tests/test_tenants_api.py`（沿用其现有 tenant/member fixture 体系），不另开新文件：

1. `test_update_api_key_name_success` —— 正常改名，断言 DB 中 `name` 已更新、响应 200、返回结构完整
2. `test_update_api_key_empty_name_rejected` —— 空字符串与全空格 → 422
3. `test_update_api_key_name_too_long` —— 256 字符 → 422
4. `test_update_api_key_system_key_forbidden` —— `is_system=True` → 403，且 DB 中 name 未变
5. `test_update_api_key_not_owner` —— 非 owner 成员调用 → 403
6. `test_update_api_key_not_found` —— 不存在的 `key_id` → 404
7. `test_update_api_key_wrong_tenant` —— key 属于其他租户 → 404（不是 403，避免泄露存在性）
8. `test_update_api_key_strips_whitespace` —— `"  new name  "` → 存储为 `"new name"`

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `hindsight_manager/api/api_keys.py` | 新增 `UpdateApiKeyRequest` + PATCH 端点 |
| `hindsight_manager/static/app.js` | 3 个新函数 + `renderApiKeysList` 内编辑按钮 |
| `hindsight_manager/templates/dashboard.html` | 新增 `#rename-apikey-modal` |
| `hindsight_manager/static/style.css` | 新增 `.api-key-edit-btn` |
| `tests/test_tenants_api.py` | 8 个测试用例（沿用现有 tenant fixture 体系） |

## 验证标准

- 后端：8 个测试全部通过；`uv run pytest tests/test_tenants_api.py -v`
- 前端：手动验证创建一个 key → 改名 → 列表显示新名称；尝试空名称 → 弹出错误；系统 key 上看不到编辑图标
- 一致性：与租户改名的交互、校验、错误提示完全对齐
