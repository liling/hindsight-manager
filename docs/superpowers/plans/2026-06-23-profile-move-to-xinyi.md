# Profile 迁移到 xinyi-platform — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 HM 的 `/profile` 整个删掉，把"个人资料"页面合到 xinyi 的 `/account`（6 字段只读），HM 顶栏"个人资料"跨站跳过去。`batch_get_users` 跨服务拉 profile 数据的 smell 消除。

**Architecture:** 在 xinyi 端查 DB 直接拿 user 完整信息渲染 `/account`；HM 顶栏 nav_menu 用 `__PLATFORM_ACCOUNT__` sentinel，sidebar 模板解析为 `{platform_url}/account`；`.profile-card`/`.profile-field` 样式从 hm.css 提升到 ui.css 通用部分。

**Tech Stack:** Python 3.12, FastAPI, Jinja2, hand-written CSS (no build chain).

## Global Constraints

- 共享 CSS 路径前缀 `/_ui/static/`。
- 两个仓库都挂在 `/_ui/static`，所以 CSS 引用 URL 在任一服务下都解析到同一份资源。
- `xinyi_platform.ui_common` 由 HM 依赖（开发期 `[tool.uv.sources]` editable=true + path，相对路径 `../xinyi-platform`）。
- `User` 模型字段：`id` (UUID), `username` (str), `email` (str|None), `display_name` (str), `auth_provider` (Enum: LOCAL/CAS), `role` (Enum: ADMIN/USER), `is_active` (bool)。
- 模板渲染 Enum 用 `.value` 取字符串。
- **不**改 OAuth2 / IdP 协议；**不**加 PATCH /me；**不**解决 spec §7.1 跨子域 SSO 缺失。

## File Structure

### xinyi-platform 仓库
```
xinyi_platform/
├── api/me.py                          # Modify: account_page 查 DB
├── templates/account.html             # Modify: 重写 6 字段
├── ui_common/static/ui.css            # Modify: 追加 .profile-card / .profile-field
└── tests/api/test_me_api.py           # Modify: 增 /account 渲染测试
```

### hindsight-manager 仓库
```
hindsight_manager/
├── main.py                            # Modify: HM_NAV_MENU 改 href
├── api/pages.py                       # Modify: 删 profile_page + 它的 import
├── templates/profile.html             # Delete
├── static/hm.css                      # Modify: 删 .profile-card / .profile-field
└── static/app.js                      # Modify: 清理 /profile 引用
```

### xinyi-platform 共享部分
```
xinyi_platform/ui_common/templates/ui/sidebar.html  # Modify: __PLATFORM_ACCOUNT__ sentinel
```

---

## Task 1: xinyi-platform 提升 .profile-card 样式到 ui.css

**Files:**
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/ui_common/static/ui.css`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/hm.css`

**Interfaces:**
- 产生通用 `.profile-card` / `.profile-field` / `.profile-field label` / `.profile-field input` 样式（来自 hm.css 现有 31 行，搬到 ui.css 末尾）
- 从 hm.css 删除对应样式块

### 步骤

- [ ] **Step 1: 打开两个文件**

读 `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/hm.css` 找到 184-213 行（`.profile-card` 起始到 `.profile-field input` 结束）。读 `/Users/liling/src/lab/xinyi-platform/xinyi_platform/ui_common/static/ui.css` 找到最后一行（要追加的位置）。

- [ ] **Step 2: 把样式块从 hm.css 追加到 ui.css**

Edit `/Users/liling/src/lab/xinyi-platform/xinyi_platform/ui_common/static/ui.css`，在文件末尾追加（保持与原 hm.css 完全一致的字面值）：

```css

/* ── Profile card ── */
.profile-card {
    background: var(--surface);
    padding: 32px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: var(--shadow-sm);
    max-width: 520px;
}
.profile-field {
    margin-bottom: 22px;
}
.profile-field label {
    display: block;
    margin-bottom: 7px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: .04em;
}
.profile-field input {
    width: 100%;
    padding: 10px 13px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 14px;
    background: var(--bg);
    color: var(--text-secondary);
    font-family: var(--font);
}
```

- [ ] **Step 3: 从 hm.css 删除 .profile-card 块**

Edit `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/hm.css`，删除 183 行（`/* ── Profile Card ── */` 注释）到 213 行（`.profile-field input` 闭合 `}`）共 31 行。

- [ ] **Step 4: 跑 xinyi-platform 测试确认未回归**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/test_ui_install.py tests/test_ui_integration.py -v
```

Expected: 6 passed (4 + 2)。

- [ ] **Step 5: 跑 HM 测试确认未回归**

```bash
cd /Users/liling/src/lab/hindsight-manager && uv run pytest --ignore=tests/test_manager_tenant.py -x
```

Expected: 113 passed (style.css 改了不影响模板渲染逻辑)。

- [ ] **Step 6: 提交**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add xinyi_platform/ui_common/static/ui.css && git commit -m "feat(ui_common): promote .profile-card / .profile-field to shared design system"

cd /Users/liling/src/lab/hindsight-manager && git add hindsight_manager/static/hm.css && git commit -m "refactor(hm): drop .profile-card / .profile-field (moved to ui_common)"
```

---

## Task 2: xinyi-platform 重写 /account 页面（me.py + account.html + 测试）

**Files:**
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/api/me.py`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/account.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/tests/api/test_me_api.py`

**Interfaces:**
- 产生 `account_page` handler 接受 `user: dict = Depends(get_current_user)` + `session: AsyncSession = Depends(get_session)`，查 DB 拿完整 User 对象后渲染 6 字段
- User 字段：`id, username, email, display_name, auth_provider (Enum), role (Enum), is_active`
- 模板 `account.html` 改用 ui.css 的 `.profile-card` / `.profile-field`

### 步骤

- [ ] **Step 1: 写失败测试**

读 `/Users/liling/src/lab/xinyi-platform/tests/api/test_me_api.py` 找到现有 `/account` 或 `/me` 测试，追加 1 个：

```python
def test_account_page_shows_all_six_profile_fields():
    """GET /account renders username, role, display_name, email, auth_provider, is_active."""
    from fastapi.testclient import TestClient
    from xinyi_platform.main import app
    from xinyi_platform.auth.session import create_access_token
    from xinyi_platform.config import Settings

    settings = Settings()
    token = create_access_token(
        sub="00000000-0000-0000-0000-000000000001",
        username="testuser",
        role="user",
        client_id="xinyi-platform-self",
        secret=settings.jwt_secret,
        ttl_seconds=3600,
    )
    client = TestClient(app)
    cookies = {"xinyi_session": token}
    # Pre-create user in DB so /account can fetch it
    # (Assumes tests have a fixture; if not, run migrations + seed)
    resp = client.get("/account", cookies=cookies)
    assert resp.status_code == 200
    html = resp.text
    for label in ["用户名", "显示名称", "邮箱", "角色", "认证方式", "账号状态"]:
        assert label in html, f"missing field label: {label}"
```

**Note**: Test needs a real user in DB. If the test infra doesn't have one, use the existing test patterns in `test_me_api.py` or `conftest.py` to seed one. Look at how other tests create users.

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/api/test_me_api.py::test_account_page_shows_all_six_profile_fields -v
```

Expected: FAIL (current `account.html` only has username + role).

- [ ] **Step 3: 重写 account.html**

Edit `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/account.html`，完整替换为：

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

- [ ] **Step 4: 修改 me.py 的 account_page**

读 `/Users/liling/src/lab/xinyi-platform/xinyi_platform/api/me.py` 当前内容。在文件中 Edit `account_page` 函数：

原：
```python
@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "account.html", {"current_user": user})
```

替换为（按现有 import 风格调整；如已有 `uuid` / `User` import 则保留，缺的从 `xinyi_platform.models.user import User` 加）：

```python
@router.get("/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    db_user = await session.get(User, uuid.UUID(user["id"]))
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

并在文件顶部 import 区域（按 me.py 现有风格）补足：
- `import uuid`（如无）
- `from sqlalchemy.ext.asyncio import AsyncSession`（如无）
- `from xinyi_platform.db import get_session`（如无）
- `from xinyi_platform.models.user import User`（如无）
- `from fastapi import HTTPException`（如已有 `from fastapi import ...` 则加入；如无则新加）

**注意**：如 `me.py` 顶部已有 `from xinyi_platform.auth.dependencies import get_current_user` 等 import，不要重复加。

- [ ] **Step 5: 运行测试，确认通过**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/api/test_me_api.py -v
```

Expected: 全部 passed（含新增的 6 字段测试）。

- [ ] **Step 6: 跑 xinyi 全套测试确认未回归**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest --ignore=tests/test_integration_full.py -x
```

Expected: 107+ passed（比 106 多 1 个新测试）。

- [ ] **Step 7: 提交**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add xinyi_platform/api/me.py xinyi_platform/templates/account.html tests/api/test_me_api.py
git commit -m "feat(xinyi): expand /account to show all 6 profile fields (read-only)"
```

---

## Task 3: xinyi-platform sidebar.html 解析 __PLATFORM_ACCOUNT__ sentinel

**Files:**
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/ui_common/templates/ui/sidebar.html`

**Interfaces:**
- nav_menu 渲染时如果 `item.href == "__PLATFORM_ACCOUNT__"` 且 `current_service != "platform"`，把 href 替换为 `{{ platform_url }}/account`
- platform 自己渲染时（`current_service == "platform"`），用 `item.href` 原值（platform 的 nav_menu 应直接用 `/account`，不依赖 sentinel）

### 步骤

- [ ] **Step 1: 读 sidebar.html 当前内容**

读 `/Users/liling/src/lab/xinyi-platform/xinyi_platform/ui_common/templates/ui/sidebar.html` 找到 nav 渲染的 for 循环（spec 提示原模板单行 `{% for item in section.items %}`）。

- [ ] **Step 2: 修改 for 循环**

原代码（大致）：
```html
{% for item in section.items %}
{% set _isActive = _path == item.href or _path.startswith(item.href + '/') %}
<a href="{{ item.href }}" class="nav-item{% if _isActive %} active{% endif %}">{{ item.label }}</a>
{% endfor %}
```

替换为：
```html
{% for item in section.items %}
{% set _isActive = _path == item.href or _path.startswith(item.href + '/') %}
{% set _href = platform_url + '/account' if item.href == '__PLATFORM_ACCOUNT__' and current_service != 'platform' else item.href %}
<a href="{{ _href }}" class="nav-item{% if _isActive %} active{% endif %}">{{ item.label }}</a>
{% endfor %}
```

- [ ] **Step 3: 跑 xinyi 测试确认未回归**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest --ignore=tests/test_integration_full.py -x
```

Expected: 107+ passed。xinyi 自己的 nav_menu 用 `/account`（不是 sentinel），所以当前 active 判断不受影响。

- [ ] **Step 4: 提交**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add xinyi_platform/ui_common/templates/ui/sidebar.html
git commit -m "feat(ui_common): sidebar.html resolves __PLATFORM_ACCOUNT__ sentinel to cross-service account URL"
```

---

## Task 4: HM 删 /profile + 改 nav_menu

**Files:**
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/main.py`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/api/pages.py`
- Delete: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/profile.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/app.js`
- Modify: `/Users/liling/src/lab/hindsight-manager/tests/test_pages.py` (if /profile tests exist)

**Interfaces:**
- 删 `profile_page` 函数 + 清理它专用的 import
- `HM_NAV_MENU` 的"个人资料"项 href 改为 `__PLATFORM_ACCOUNT__`
- 删除 `templates/profile.html`
- 检查并清理 `app.js` 中 `/profile` 引用
- 删除 `tests/test_pages.py` 中 `/profile` 相关测试（如有）

### 步骤

- [ ] **Step 1: 修改 HM_NAV_MENU**

Edit `/Users/liling/src/lab/hindsight-manager/hindsight_manager/main.py`，找到 HM_NAV_MENU 顶栏中"个人资料"项：

原：
```python
{"id": "profile",   "label": "个人资料", "href": "/profile"},
```

替换为：
```python
{"id": "profile",   "label": "个人资料", "href": "__PLATFORM_ACCOUNT__"},
```

- [ ] **Step 2: 删除 profile_page + 它的 import**

读 `/Users/liling/src/lab/hindsight-manager/hindsight_manager/api/pages.py`。删除整个 `profile_page` 函数（行 138-178 范围，按实际定位）。

清理顶部 import：
- 如果 `import uuid` / `from contextlib import asynccontextmanager` / `from hindsight_manager.platform.client import XinyiPlatformClient` / `from hindsight_manager.platform.config import PlatformSettings` 整个文件别处不用，从顶部 import 区删除。
- 用 `grep -n "uuid\|XinyiPlatformClient\|PlatformSettings\|asynccontextmanager" hindsight_manager/api/pages.py` 确认是否别处用了。

- [ ] **Step 3: 删除 profile.html**

```bash
git rm /Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/profile.html
```

- [ ] **Step 4: 检查 app.js**

```bash
grep -n "profile" /Users/liling/src/lab/hindsight-manager/hindsight_manager/static/app.js
```

如有任何引用 `/profile` 或 `profile.html`，删除对应行（保留其他逻辑）。如无引用，跳过。

- [ ] **Step 5: 检查并删除 test_pages.py 中的 /profile 测试**

```bash
grep -n "/profile\|profile_page" /Users/liling/src/lab/hindsight-manager/tests/test_pages.py
```

如有，删除对应测试函数。保留 dashboard / api_keys / admin_* 测试不变。

- [ ] **Step 6: 跑 HM 测试确认未回归**

```bash
cd /Users/liling/src/lab/hindsight-manager && uv run pytest --ignore=tests/test_manager_tenant.py -x
```

Expected: 113 passed（不变或减少——如果删了 /profile 测试可能少 1-2 个）。

- [ ] **Step 7: 提交**

```bash
cd /Users/liling/src/lab/hindsight-manager && git add -A
git commit -m "refactor(hm): drop /profile route + template; nav points to platform /account via sentinel"
```

---

## Task 5: 端到端手动验证

**Files:** 无（只验证）

### 步骤

- [ ] **Step 1: 重启两个服务**

```bash
# 在已运行的 HM 进程所在的终端按 Ctrl+C 停止
# 然后启动：
cd /Users/liling/src/lab/hindsight-manager && uv run uvicorn hindsight_manager.main:app --port 8001 --reload > /tmp/hm.log 2>&1 &

# xinyi 类似：
cd /Users/liling/src/lab/xinyi-platform && uv run uvicorn xinyi_platform.main:app --port 8000 --reload > /tmp/xinyi.log 2>&1 &
```

- [ ] **Step 2: 验证 HM 端到端**

```bash
# 1. HM 未登录访问 /dashboard → 401 + Location /auth/login-redirect
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/dashboard
# Expected: 401

# 2. HM 访问 / → 302 → /login → 303 → xinyi /oauth/authorize
curl -sI http://localhost:8001/ | grep -i location
# Expected: location: /login

# 3. xinyi /account 渲染包含 6 字段标签（需要登录 token；手动用浏览器验证）
```

- [ ] **Step 3: 浏览器验证**

1. 打开 `http://localhost:8001/`
2. 走完 OAuth 登录（在 xinyi 登录页输入 admin/admin）
3. 跳回 HM
4. 点侧栏"个人资料" → 应跳到 `http://localhost:8000/account` → 6 字段全部显示
5. 检查 `/admin/users` 等其他管理页未受影响

- [ ] **Step 4: 检查日志**

```bash
tail -20 /tmp/hm.log
tail -20 /tmp/xinyi.log
```

Expected: 无 traceback。

- [ ] **Step 5: 验收**

回答以下确认：
- [ ] HM `/profile` 访问返回 404（已删）
- [ ] xinyi `/account` 显示 6 字段
- [ ] HM 顶栏"个人资料"跳转到 xinyi
- [ ] HM dashboard / api_keys / admin / task_monitor 仍正常

## Self-Review

### Spec coverage

| Spec 段 | 覆盖任务 |
|---|---|
| §3.1 xinyi me.py + account.html 6 字段 | Task 2 |
| §3.2 .profile-card 提升到 ui.css | Task 1 |
| §3.3 HM pages.py 删 profile_page + main.py nav_menu | Task 4 |
| §3.3 sidebar.html __PLATFORM_ACCOUNT__ sentinel | Task 3 |
| §3.3 删 profile.html + app.js 清理 | Task 4 |
| §4 行为变化说明 | Task 5 验证 |
| §5 测试（xinyi 6 字段 + HM 不回归） | Task 2 Step 5-6, Task 4 Step 6 |

### Placeholder scan

- 无 TBD / TODO / "implement later"。
- Task 1 Step 1-2 用了具体行号（"184-213"），是从 `grep -n` + 实际读文件得出的。**Phase 1 实施时需要用 `grep -n` 重新定位当前 hm.css 的行号**——因为 hm.css 在前一阶段（HM refactoring）已修改过，行号可能已偏移。
- Task 2 Step 4 用了"如已有 `uuid` import 则保留"——这是显式条件，不是 placeholder。

### Type consistency

- `account_page` 签名 `user: dict = Depends(get_current_user)` + `session: AsyncSession = Depends(get_session)` 在 Task 2 Step 4 出现，并在 Task 5 验证。
- `__PLATFORM_ACCOUNT__` sentinel 字符串在 Task 3 模板和 Task 4 nav_menu 中一致。
- `current_user` dict 字段：`id, username, role, display_name, email, auth_provider, is_active` 在 Task 2 Step 4 完整映射。

### Risks

- **行号偏移**：hm.css 行号在新版可能偏移。Task 1 Step 1 要求实施人用 `grep` 重新定位。
- **User 模型字段名**：Task 2 Step 4 已按读过的模型文件确认了字段名。
- **active 状态判断**：sidebar.html 的 `_isActive` 仍按原 `item.href` 判断（不会被 sentinel 改变，因为 sentinel 只在渲染 href 时生效，不影响 active 计算）。Task 3 没改 active 逻辑。

---

Plan complete and saved to `docs/superpowers/plans/2026-06-23-profile-move-to-xinyi.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task + review per task
2. **Inline Execution** — execute in current session

Which approach?
