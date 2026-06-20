# 记忆库重命名功能 设计文档

日期：2026-06-20

## 背景

Hindsight Manager 的普通用户控制台（`/dashboard`）展示用户所属的记忆库（tenant）列表，每张卡片提供"进入控制台 / 成员 / API Keys / 删除"操作，但**没有修改记忆库名称的入口**。后端 `PATCH /tenants/{tenant_id}` 已存在，目前只用于更新 LLM `config`，不接受 `name`。

## 目标

让 owner 在 dashboard 上直接修改记忆库名称。

## 非目标

- 不在 admin 后台页面 (`/admin/tenants`) 加改名入口。
- 不做名称唯一性校验（`schema_name` 才是唯一键，`name` 允许重复）。
- 不写审计日志（项目内其他 `PATCH` 也没记）。
- 不做数据库迁移（`Tenant.name` 字段已存在，`String(255)`）。
- 不引入无刷新局部更新；改名成功后沿用现有 `window.location.reload()` 模式。

## 权限

仅 owner 可改。与现有"删除 / API Keys / 成员管理"一致，复用 `_require_membership(..., require_owner=True)`。

## 后端设计

文件：`hindsight_manager/api/tenants.py`

### 请求模型扩展

`TenantConfigUpdateRequest` 增加可选字段：

```python
class TenantConfigUpdateRequest(BaseModel):
    name: str | None = None
    llm_provider: str | None = None
    # ... 其余字段保持不变
```

### 处理逻辑

`update_tenant_config` 中，在更新 config 之前：

1. 若 `req.name` 不为 `None`：
   - `trimmed = req.name.strip()`
   - 校验 `1 <= len(trimmed) <= 255`，否则 `HTTPException(422, ...)`
   - `tenant.name = trimmed`
2. config 部分保持现有 `model_dump(exclude_none=True)` + `dict.update` 逻辑。

由于 `exclude_none=True` 会跳过未传字段，name 和 config 可以独立或同时更新，互不影响。

### 端点

无新增端点。复用 `PATCH /tenants/{tenant_id}`。

## 前端设计

### `templates/dashboard.html`

在 `{% if t.role == 'owner' %}` 区块内（"删除"按钮之前）增加：

```html
<button class="btn btn-secondary btn-sm" onclick="showRenameModal('{{ t.id }}', '{{ t.name | e }}')">重命名</button>
```

并在 create-modal 之后增加 rename-modal，结构参照 create-modal：

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

### `static/app.js`

新增三个函数：

- `showRenameModal(tenantId, currentName)`：填入 hidden id 与当前名、显示 modal、focus 输入框。
- `hideRenameModal()`：隐藏 modal。
- `renameTenant(event)`：`event.preventDefault()`，`PATCH /tenants/{id}` with `{name: ...}`；成功 `window.location.reload()`；失败 `alert(err.detail || "重命名失败")`。

整体形态与现有 `createTenant` / `deleteTenant` 一致。

## 校验

- 后端：trim 后长度 1–255；422 错误返回中文文案。
- 前端：HTML `required`，浏览器原生提示。

## 测试计划

后端（`tests/`）：
1. owner 调用 `PATCH /tenants/{id}` body `{name: "新名"}` → 200，响应中 name 更新。
2. member（非 owner）调用 → 403。
3. 空字符串 / 全空白 name → 422。
4. 超过 255 字符 → 422。
5. 同时传 `name` 和某个 config 字段 → 两者都更新。
6. 只传 config 字段（不传 name）→ name 不变（回归）。

前端：手动验证 dashboard 重命名按钮、modal、错误提示。

## 改动文件清单

- `hindsight_manager/api/tenants.py`
- `hindsight_manager/templates/dashboard.html`
- `hindsight_manager/static/app.js`
- `tests/test_tenants.py`（或就近的现有测试文件）
