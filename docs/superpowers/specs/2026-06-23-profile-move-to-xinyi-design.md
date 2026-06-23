# 个人资料迁移到 xinyi-platform — 设计

- **日期**: 2026-06-23
- **状态**: 设计已对齐各节，待 spec 审阅

## 1. 背景与动机

平台 / 业务代码分离后，hindsight-manager 的 `/profile` 仍在用 `XinyiPlatformClient.batch_get_users` 跨服务拉自己的 display_name、email、auth_provider、is_active——这些字段都来自 xinyi 自己的 users 表。这种"业务服务回拉自己数据的权威源"是 smell；现状已经造成跨服务 RTT + 失败时静默退化为只显示 3 个 session 字段。

xinyi 自己的 `/account` 又只显示 username + role。结论：**HM 的 `/profile` 是冗余的、错误的页**；xinyi 的 `/account` 是缺字段的、不完整的页**。合二为一为正解。

## 2. 目标与非目标

### 目标

- 用户在 HM 顶栏点"个人资料"时，跨站跳到 xinyi 的 `/account` 看完整资料。
- xinyi `/account` 显示 6 个字段：username、role、display_name、email、auth_provider、is_active，全部只读。
- HM 不再持有或拉取任何 profile 扩展数据。
- 把当前在 `hm.css` 的 `.profile-card` / `.profile-field` 样式提升到 `ui.css` 通用部分，未来任何业务"看资料"都能复用。

### 非目标

- **不**实现"xinyi session 缺失时反向种 cookie"（spec §7.1 已知限制，本期不解决）。
- **不**在 xinyi 加 `PATCH /me` 编辑端点——你说只读。
- **不**改 `/me` JSON 端点（HM 仍可能调用它）。

## 3. 改动清单

### 3.1 xinyi-platform

**`xinyi_platform/api/me.py`** —— `account_page` 改造：

```python
@router.get("/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    db_user = await session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    full_user = {
        "id": str(db_user.id),
        "username": db_user.username,
        "role": db_user.role.value,
        "display_name": db_user.display_name,
        "email": db_user.email,
        "auth_provider": db_user.auth_provider.value,
        "is_active": db_user.is_active,
    }
    return templates.TemplateResponse(
        request, "account.html",
        {**_ui_ctx(request), "current_user": full_user},
    )
```

`User` 模型字段假设：`id, username, role (Enum), display_name, email, auth_provider (Enum), is_active`——需要按 `xinyi_platform/models/user.py` 实际字段名核对。

**`xinyi_platform/templates/account.html`** —— 完整重写，参考原 HM `/profile` 的 `.profile-card` 风格：

```html
{% extends "admin/base.html" %}
{% block title %}个人资料 - {{ brand }}{% endblock %}
{% block main %}
<div class="content-header">
    <h2>个人资料</h2>
</div>

<div class="profile-card">
    <div class="profile-field">
        <label>用户名</label>
        <input type="text" value="{{ current_user.username }}" readonly>
    </div>
    <div class="profile-field">
        <label>显示名称</label>
        <input type="text" value="{{ current_user.display_name or '—' }}" readonly>
    </div>
    <div class="profile-field">
        <label>邮箱</label>
        <input type="email" value="{{ current_user.email or '未设置' }}" readonly>
    </div>
    <div class="profile-field">
        <label>角色</label>
        <input type="text" value="{{ current_user.role }}" readonly>
    </div>
    <div class="profile-field">
        <label>认证方式</label>
        <input type="text" value="{{ current_user.auth_provider }}" readonly>
    </div>
    <div class="profile-field">
        <label>账号状态</label>
        <input type="text" value="{% if current_user.is_active %}正常{% else %}已禁用{% endif %}" readonly>
    </div>
</div>
{% endblock %}
```

### 3.2 xinyi-platform（CSS 提升）

**`xinyi_platform/ui_common/static/ui.css`** —— 追加（从 HM `hm.css` 搬过来，去掉 HM-specific 痕迹）：

```css
/* ── Profile card ── */
.profile-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 32px;
    max-width: 640px;
}
.profile-field { margin-bottom: 18px; }
.profile-field label {
    display: block;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 6px;
}
.profile-field input {
    width: 100%;
    padding: 9px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--text);
    font-size: 14px;
    font-family: var(--font);
}
.profile-field input[readonly] { cursor: default; }
```

**`hindsight_manager/static/hm.css`** —— 删除 `.profile-card` / `.profile-field` 相关规则（已搬到 ui.css）。

### 3.3 hindsight-manager

**`hindsight_manager/api/pages.py`** —— 删除 `profile_page` 整个函数 + 它的 import（`uuid`, `XinyiPlatformClient`, `PlatformSettings`, `asynccontextmanager` 中只在该函数用的部分）。

**`hindsight_manager/main.py`** —— 修改 `HM_NAV_MENU`：

```python
HM_NAV_MENU = [
    {
        "type": "section",
        "label": "记忆库",
        "items": [
            {"id": "dashboard", "label": "记忆库", "href": "/dashboard"},
            # href 用 sentinel：sidebar.html 渲染时若 current_service != "platform"
            # 就替换为 {{ platform_url }}/account
            {"id": "profile", "label": "个人资料", "href": "__PLATFORM_ACCOUNT__"},
        ],
    },
    ...
]
```

**`xinyi_platform/ui_common/templates/ui/sidebar.html`** —— `__PLATFORM_ACCOUNT__` sentinel 解析（这是 ui_common 的修改，所有业务受益）：

```html
{% for item in section.items %}
    {% set _href = platform_url + '/account' if item.href == '__PLATFORM_ACCOUNT__' and current_service != 'platform' else item.href %}
    <a href="{{ _href }}" class="nav-item{% if _isActive %} active{% endif %}">{{ item.label }}</a>
{% endfor %}
```

注意：原 sidebar 模板里 nav_menu 渲染是单行 `{% for item in section.items %}`，本改动需要把单行拆成 2 行加 `{% set %}` 赋值。

**`hindsight_manager/templates/profile.html`** —— 删除文件。

**`hindsight_manager/static/app.js`** —— 检查并清理任何对 `/profile` 或 `profile.html` 的引用（运行 `grep -n "profile" hindsight_manager/static/app.js` 验证；如有，删掉）。

## 4. 行为变化

### 用户视角

| 之前 | 之后 |
|---|---|
| 在 HM 侧栏点"个人资料" → 跳 `/profile` → 跨服务 batch_get_users → 渲染 HM 模板 | 在 HM 侧栏点"个人资料" → 跳 `{{ platform_url }}/account` → xinyi 直接查 DB 渲染 |
| 在 xinyi 侧栏点"我的账户" → 跳 `/account` → 只显示 username + role | 在 xinyi 侧栏点"我的账户" → 跳 `/account` → 显示 6 字段 |

### 边界

- 用户在 HM（HM session 有效）点"个人资料" → 跳到 `{{ platform_url }}/account`
- xinyi 自身 session cookie 在浏览器里若 24h 内有效则直进
- 若 xinyi session 失效：落到 xinyi 登录页（spec §7.1 已知限制，本期不解决）

## 5. 测试

### xinyi 端

- 新增或扩展 `tests/api/test_me_api.py`：访问 `/account`，断言 6 字段全部出现（`username`, `role`, `display_name`, `email`, `auth_provider`, `is_active`）
- 跑 `uv run pytest --ignore=tests/test_integration_full.py`，全过（106+ 个测试）

### HM 端

- 删除 `tests/test_pages.py` 中任何对 `/profile` 的测试（如果存在）
- dashboard 侧栏 active 断言不变（"个人资料" 这条 nav label 仍在）
- 跑 `uv run pytest --ignore=tests/test_manager_tenant.py`，全过（113+ 个测试）

### 手动验证

- 浏览器登录 HM → 点侧栏"个人资料" → 跳到 `http://localhost:8000/account` → 6 字段显示

## 6. 风险

- **`User` 模型字段名不一致**：先读 `xinyi_platform/models/user.py` 确认 `role` / `auth_provider` 是 Enum 而非字符串；如果是 Enum 在模板里要 `{{ current_user.auth_provider.value }}`（spec 已知 Enum 显示问题）。**Phase 1 实施时必须先看模型再写 handler**。
- **`.profile-card` 提升到 ui.css 后视觉差异**：HM 现有 `.profile-card` 用的是 32px padding、640px max-width；照搬不会差，但若两服务的 `.profile-card` 边界设置不一致（圆角、阴影）会有视觉漂移。**Phase 1 实施时把 hm.css 的 `.profile-card` 完整 CSS 块复制到 ui.css**，不要改字面值。
- **`sidebar.html` 的 sentinel 解析破坏 platform 自己**：当 `current_service == "platform"` 时，sidebar 用 `item.href` 原始值（`__PLATFORM_ACCOUNT__`），会出错。**Phase 1 实施时检查 platform 自己的 nav_menu 是否也用 `__PLATFORM_ACCOUNT__`**——按本设计，platform 的"我的账户"用 `/account`（不需要 sentinel），HM 才有 sentinel。
