# UI 统一与跨业务导航重构 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抽出共享 UI 子包 `xinyi_platform/ui_common`，让 hindsight-manager 和 xinyi-platform 通过统一的页面骨架、设计系统、全局产品切换器呈现同一产品形象，并为未来接入新业务提供零 CSS 接入路径。

**Architecture:** 共享 Python 子包放在 xinyi-platform 仓库内（`xinyi_platform/ui_common/`）。每个服务在 `main.py` 调用 `install_ui(app, current_service=..., nav_menu=..., ...)`，由该函数注入 Jinja2 loader、挂载 `/​_ui/static` StaticFiles、注入 globals。业务模板 extends `ui/app_shell.html`（登录后）或 `ui/auth_shell.html`（未登录），不再承载样式与导航结构。

**Tech Stack:** Python 3.12（xinyi-platform）/ 3.11（HM），FastAPI，Jinja2，CSS（手写，无 build chain）。

## Global Constraints

- css 资产路径前缀 `/_ui/static/`（避免与每个服务本身的 `/static` 冲突）。
- 所有服务（含 xinyi-platform 自己）都挂载 `/_ui/static`，因此 css 引用 URL 在任一服务内都解析到同一份资源。
- HM 的 `pyproject.toml` 新增依赖 `xinyi-platform = { path = "../xinyi-platform" }`；本地通过 `uv sync` 装入。镜像层的共享由 docker build 时挂载 / 多 stage copy 处理（见 Task 1）。
- **不**改 OAuth2 / IdP 协议；**不**引入跨子域 cookie SSO；**不**引入 build 工具或前端框架。
- 任务路径约定：`current_service` 枚举是字符串字面量：`"platform" | "hindsight-manager"`（未来新增业务在此约定外扩充）。
- 每个任务结束都要 commit（见各 Task Step 5）。

---

## File Structure

### 新建（xinyi-platform 仓库）

```
xinyi_platform/ui_common/
├── __init__.py                 # 导出 install_ui / PRODUCTS / nav_menu 类型别名
├── install.py                  # install_ui 实现
├── registry.py                 # PRODUCTS 常量
├── static/
│   ├── ui.css                  # 通用设计系统（Task 4 中从 HM 迁移）
│   └── logo.svg                # 占位 logo
├── templates/
│   └── ui/
│       ├── base.html           # html 骨架
│       ├── app_shell.html      # 登录后外壳
│       ├── auth_shell.html     # 未登录外壳
│       ├── topbar.html         # 顶栏 partial
│       ├── sidebar.html        # 侧边栏 partial
│       └── product_switcher.html
└── tests/
    └── test_install.py         # install_ui 单元测试
```

### HM 仓库改动

```
hindsight_manager/
├── main.py                     # 调用 install_ui；删除 admin_users / admin_audit_logs 死路由
├── config.py                   # 新增 brand_name
├── jinja_filters.py            # 增加业务侧 nav_menu 与 ui_common loader 协调
├── templates/
│   ├── base.html               # 缩减为 {% extends "ui/base.html" %}
│   ├── admin_base.html         # 改为 extends ui/app_shell.html，删除内置侧边栏
│   ├── dashboard.html          # 改用新 base；删除 nav_active 设置
│   ├── api_keys.html           # 同上
│   ├── profile.html            # 同上
│   └── admin_{api_keys,task_monitor,tenants}.html  # 同上
├── static/
│   ├── style.css               # 删除（被 ui.css 取代）
│   └── hm.css                  # 新建：业务专属补丁（tenant-card 等）
└── tests/test_ui_integration.py# 新增：访问 /dashboard 含顶栏侧栏
```

### xinyi-platform 仓库改动

```
xinyi_platform/
├── main.py                     # install_ui 调用
├── config.py                   # 新增 brand_name、manager_url
├── templates/
│   ├── base.html               # 缩减
│   ├── admin/base.html         # 改为 extends ui/app_shell.html
│   ├── login.html              # 改为 extends ui/auth_shell.html
│   ├── register.html           # 同上
│   ├── forgot_password.html    # 同上
│   ├── reset_password.html     # 同上
│   ├── account.html            # extends app_shell
│   └── admin/{users,clients,audit_logs,login_history,user_form}.html  # 重写表单/表格样式
└── static/
    └── style.css               # 删除（6 行版本）
```

---

## Task 1: 在 xinyi-platform 中创建 ui_common 子包骨架与 install_ui

**Files:**
- Create: `xinyi_platform/ui_common/__init__.py`
- Create: `xinyi_platform/ui_common/install.py`
- Create: `xinyi_platform/ui_common/registry.py`
- Create: `xinyi_platform/ui_common/static/.gitkeep`
- Create: `xinyi_platform/ui_common/templates/ui/.gitkeep`
- Create: `xinyi_platform/tests/test_ui_install.py`
- Modify: `xinyi_platform/pyproject.toml` (把 `ui_common` 加入 `[tool.hatch.build.targets.wheel].packages`)

**Interfaces:**
- Produces:
  - `install_ui(app: FastAPI, *, current_service: str, nav_menu: list[dict], brand: str, platform_url: str, manager_url: str | None = None) -> None`
  - `PRODUCTS: list[dict]` — 见 `registry.py`

### 步骤

- [ ] **Step 1: 写失败测试**

新建 `xinyi_platform/tests/test_ui_install.py`：

```python
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from xinyi_platform.ui_common import install_ui, PRODUCTS


def test_install_ui_registers_globals_and_static():
    app = FastAPI()
    install_ui(
        app,
        current_service="hindsight-manager",
        nav_menu=[
            {"type": "section", "label": "业务", "items": [
                {"id": "dashboard", "label": "仪表盘", "href": "/dashboard"},
            ]},
        ],
        brand="Hindsight",
        platform_url="http://platform.test",
        manager_url="http://hm.test",
    )

    routes = {r.path: r for r in app.routes}
    assert "/_ui/static" in { getattr(r, "path", "") for r in app.routes }

    # Jinja2 globals — 验证可以通过创建一个 Jinja2Templates 实例后 env 是否带预期 globals
    # install_ui 在 app.state 上缓存了配置,这里验证 app.state.ui
    assert app.state.ui["current_service"] == "hindsight-manager"
    assert app.state.ui["brand"] == "Hindsight"
    products = app.state.ui["products"]
    assert any(p["id"] == "platform" for p in products)
    assert any(p["id"] == "hindsight-manager" for p in products)
    hm_entry = next(p for p in products if p["id"] == "hindsight-manager")
    assert hm_entry["url"] == "http://hm.test/dashboard"
    platform_entry = next(p for p in products if p["id"] == "platform")
    assert platform_entry["url"] == "http://platform.test/account"


def test_products_constant_shape():
    assert len(PRODUCTS) >= 2
    for p in PRODUCTS:
        assert {"id", "label", "subtitle", "kind", "url_template"} <= set(p.keys())
        assert p["kind"] in {"platform", "business"}


def test_install_ui_requires_main_app_and_current_service():
    import pytest
    with pytest.raises(TypeError):
        install_ui()  # type: ignore[call-arg]
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/test_ui_install.py -v
```

Expected: `ImportError: cannot import name 'install_ui' from 'xinyi_platform.ui_common'`

- [ ] **Step 3: 实现 registry.py**

```python
"""Global product registry used by the product switcher in the topbar.

`url_template` uses `{platform_url}` / `{manager_url}` placeholders that
`install_ui` substitutes with concrete URLs at app startup.
"""
from __future__ import annotations

PRODUCTS: list[dict] = [
    {
        "id": "platform",
        "label": "平台账户中心",
        "subtitle": "用户 · 审计 · 登录历史",
        "kind": "platform",
        "url_template": "{platform_url}/account",
    },
    {
        "id": "hindsight-manager",
        "label": "Hindsight",
        "subtitle": "RAG 记忆库",
        "kind": "business",
        "url_template": "{manager_url}/dashboard",
    },
]
```

- [ ] **Step 4: 实现 install.py**

```python
"""install_ui: wire shared UI assets and globals into a FastAPI app."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .registry import PRODUCTS

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATE_DIR = _HERE / "templates"


def _resolve_products(*, platform_url: str, manager_url: str | None) -> list[dict]:
    resolved: list[dict] = []
    for p in PRODUCTS:
        url = p["url_template"].format(
            platform_url=platform_url,
            manager_url=manager_url or "",
        )
        resolved.append({**p, "url_template": None, "url": url})
    return resolved


def install_ui(
    app: FastAPI,
    *,
    current_service: str,
    nav_menu: list[dict],
    brand: str,
    platform_url: str,
    manager_url: str | None = None,
) -> None:
    """Install shared UI: Jinja globals, templates loader, static files mount.

    Args:
        app: FastAPI instance to wire into.
        current_service: which key in PRODUCTS represents this service
            (used to mark active in topbar/sidebar). One of "platform",
            "hindsight-manager", or future business ids.
        nav_menu: list-of-sections describing this service's sidebar.
        brand: brand label shown next to logo in topbar.
        platform_url: base URL of the platform (xinyi-platform) service.
        manager_url: base URL of hindsight-manager (required for the
            platform service to render HM entry in the switcher; business
            services may leave None).

    Stores resolved config on `app.state.ui` so routers and Jinja globals
    can access it later. Mounts `/​_ui/static` so every service can serve
    ui.css at the same path.
    """
    app.state.ui = {
        "current_service": current_service,
        "nav_menu": nav_menu,
        "brand": brand,
        "platform_url": platform_url,
        "manager_url": manager_url,
        "products": _resolve_products(
            platform_url=platform_url, manager_url=manager_url
        ),
        "template_dir": str(_TEMPLATE_DIR),
    }

    app.mount(
        "/_ui/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="ui-static",
    )
```

- [ ] **Step 5: 实现 __init__.py**

```python
from .install import install_ui
from .registry import PRODUCTS

__all__ = ["install_ui", "PRODUCTS"]
```

- [ ] **Step 6: 创建占位目录文件**

`xinyi_platform/ui_common/static/.gitkeep`（空文件）
`xinyi_platform/ui_common/templates/ui/.gitkeep`（空文件）

- [ ] **Step 7: 修改 pyproject.toml 让 ui_common 被打入 wheel**

Modify: `xinyi-platform/pyproject.toml`

```toml
[tool.hatch.build.targets.wheel]
packages = ["xinyi_platform", "xinyi_platform/ui_common"]
```

- [ ] **Step 8: 运行测试，确认通过**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/test_ui_install.py -v
```

Expected: 3 passed

- [ ] **Step 9: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add xinyi_platform/ui_common/ xinyi_platform/tests/test_ui_install.py pyproject.toml
git commit -m "feat: add ui_common subpackage with install_ui and PRODUCTS registry"
```

---

## Task 2: 实现 ui_common 模板与 css（基础骨架）

**Files:**
- Create: `xinyi_platform/ui_common/templates/ui/base.html`
- Create: `xinyi_platform/ui_common/templates/ui/topbar.html`
- Create: `xinyi_platform/ui_common/templates/ui/sidebar.html`
- Create: `xinyi_platform/ui_common/templates/ui/product_switcher.html`
- Create: `xinyi_platform/ui_common/templates/ui/app_shell.html`
- Create: `xinyi_platform/ui_common/templates/ui/auth_shell.html`
- Create: `xinyi_platform/ui_common/static/ui.css`
- Create: `xinyi_platform/ui_common/static/logo.svg`
- Modify: `xinyi_platform/ui_common/install.py`（注入 Jinja globals generator）

**Interfaces:**
- Consumes: Task 1 `install_ui`、`PRODUCTS`
- Produces: 模板集 `ui/base.html`, `ui/app_shell.html`, `ui/auth_shell.html`, `ui/topbar.html`, `ui/sidebar.html`, `ui/product_switcher.html`，CSS `/​_ui/static/ui.css`。
  - 业务页面需要设置的上下文变量：
    - 业务页面必须通过 `templates.TemplateResponse` 提供的 `request` 自动从 `app.state.ui` 注入以下 Jinja globals：`current_service`, `nav_menu`, `brand`, `products`, `platform_url`, `manager_url`。
    - 业务侧需要传入模板上下文：`current_user`（dict；`username`, `role`, `id`, 等基础信息；admin 判断用 `current_user.get("role") == "admin"`）。
  - 业务页面模板只需要 `{% extends "ui/app_shell.html" %}` + `{% block main %}…{% endblock %}`。
  - 业务页面 URL active 判定由 sidebar partial 自己根据 `request.url.path` 自动匹配 nav item `href`，业务页面**不需要**再设置 `nav_active`。

### 步骤

- [ ] **Step 1: 修改 install.py 注入 Jinja2 globals generator**

我们要让业务侧的 `Jinja2Templates` 实例共享 ui_common 的模板目录，并且 globals 自动填上 `current_service` 等。给 `install_ui` 增加一个 helper：

Modify `xinyi_platform/ui_common/install.py`：

```python
"""install_ui: wire shared UI assets and globals into a FastAPI app."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .registry import PRODUCTS

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATE_DIR = _HERE / "templates"


def _resolve_products(*, platform_url: str, manager_url: str | None) -> list[dict]:
    resolved: list[dict] = []
    for p in PRODUCTS:
        url = p["url_template"].format(
            platform_url=platform_url,
            manager_url=manager_url or "",
        )
        resolved.append({**p, "url_template": None, "url": url})
    return resolved


def install_ui(
    app: FastAPI,
    *,
    current_service: str,
    nav_menu: list[dict],
    brand: str,
    platform_url: str,
    manager_url: str | None = None,
) -> None:
    """Install shared UI: Jinja globals, templates loader, static files mount."""
    app.state.ui = {
        "current_service": current_service,
        "nav_menu": nav_menu,
        "brand": brand,
        "platform_url": platform_url,
        "manager_url": manager_url,
        "products": _resolve_products(
            platform_url=platform_url, manager_url=manager_url
        ),
        "template_dir": str(_TEMPLATE_DIR),
    }

    app.mount(
        "/_ui/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="ui-static",
    )


def ui_jinja_globals(request: Request) -> dict:
    """Helper to be used by business Jinja2Templates to expose ui_common state.

    Usage in a business app::

        from fastapi.templating import Jinja2Templates
        from xinyi_platform.ui_common import install_ui, ui_jinja_globals

        templates = Jinja2Templates(directory="my_app/templates")
        templates.env.globals.update(**ui_jinja_globals_factory(app))

    For FastAPI `Request`-based resolution we attach this helper and let
    business code wire its own Jinja env; see Task 3/4 for an example.
    """
    ui = request.app.state.ui
    return {
        "current_service": ui["current_service"],
        "nav_menu": ui["nav_menu"],
        "brand": ui["brand"],
        "platform_url": ui["platform_url"],
        "manager_url": ui["manager_url"],
        "products": ui["products"],
    }
```

下面 task 3 会展示 HM 怎么把 `ui_jinja_globals` 接入 Jinja2 的 globals/path。

> 注意：上面对 `ui_jinja_globals(request)` 的形参签名是为了让读者明确语义；实际业务接入会用一个不接受 request 的版本（直接读 `app.state`）。但 HM 的 Jinja2Templates 是在 `make_templates()` 中创建的，那时 app 还没创建——所以我们需要让 HM 推迟 globals 注入到 request 时。最干净的写法是：HM 给 `make_templates(app)` 加一个 app 参参，然后在 `make_templates` 中调用 `templates.env.globals.update(...)`，从 `app.state.ui` 里取。完整调用链见 Task 3 Step 1。

- [ ] **Step 2: 创建 static/logo.svg（占位）**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <circle cx="12" cy="12" r="10"/>
  <path d="M12 6v6l4 2"/>
</svg>
```

- [ ] **Step 3: 创建 templates/ui/base.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ brand }}{% endblock %}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300..800;1,300..800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/_ui/static/ui.css">
    {% block head %}{% endblock %}
</head>
<body>
    {% block body %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: 创建 templates/ui/product_switcher.html**

```html
{% block product_switcher %}
<div class="product-switcher">
    <button type="button" class="product-switcher-btn" aria-haspopup="true" aria-expanded="false" onclick="document.getElementById('product-switcher-menu').classList.toggle('hidden')">
        <svg class="product-switcher-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        <span class="product-switcher-current">{% set _current = products | selectattr('id', 'equalto', current_service) | first %}
        {{ _current.label if _current else brand }}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
    </button>
    <div id="product-switcher-menu" class="product-switcher-menu hidden">
        <div class="product-switcher-section">平台</div>
        {% for p in products if p.kind == 'platform' %}
        <a class="product-switcher-item{% if p.id == current_service %} active{% endif %}" href="{{ p.url }}">
            <div class="product-switcher-item-label">{{ p.label }}</div>
            <div class="product-switcher-item-subtitle">{{ p.subtitle }}</div>
        </a>
        {% endfor %}
        <div class="product-switcher-section">业务</div>
        {% for p in products if p.kind == 'business' %}
        <a class="product-switcher-item{% if p.id == current_service %} active{% endif %}" href="{{ p.url }}">
            <div class="product-switcher-item-label">{{ p.label }}{% if p.id == current_service %} <span class="product-switcher-check">✓</span>{% endif %}</div>
            <div class="product-switcher-item-subtitle">{{ p.subtitle }}</div>
        </a>
        {% endfor %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 5: 创建 templates/ui/topbar.html**

```html
<header class="topbar">
    <div class="topbar-brand">
        <img src="/_ui/static/logo.svg" alt="{{ brand }}" class="topbar-logo">
        <span class="topbar-brand-name">{{ brand }}</span>
    </div>
    <div class="topbar-actions">
        {% include "ui/product_switcher.html" %}
        <div class="topbar-account">
            <span class="topbar-username">{{ current_user.username }}</span>
            {% block account_actions %}
            <a href="{{ platform_url }}{% if current_service != 'platform' %}/oauth/authorize?response_type=code&amp;client_id=hm-prod&amp;return_to=/account{% endif %}" class="btn btn-ghost btn-sm">个人中心</a>
            {% endblock %}
        </div>
    </div>
</header>
```

> ⚠ 审阅注：上面"个人中心"的跳转策略——若当前服务是业务（hm），用户想去平台 `/account` 应当直接跳 `{{ platform_url }}/account`（xinyi 自身的 session cookie 有效就直进；如果没 session 则落到登录页 —— 这是 spec §7.1 记录的已知限制）。我们把链接简化，不构造 OAuth 客户端 URL（那是 HM 跳 HM 的流程，不是平台上的）。更正版在 Step 5.b。

- [ ] **Step 5b: 简化 topbar.html 的个人中心链接**

替换 `{% block account_actions %}` 段为：

```html
        <div class="topbar-account">
            <span class="topbar-username">{{ current_user.username }}</span>
            {% block account_actions %}
            {#- 个人中心始终指向当前服务的 profile/account 入口；跨服务跳转由 product_switcher 完成 -#}
            <a href="{% if current_service == 'platform' %}/account{% else %}/profile{% endif %}" class="btn btn-ghost btn-sm">个人中心</a>
            {% endblock %}
        </div>
```

- [ ] **Step 6: 创建 templates/ui/sidebar.html**

```html
<nav class="sidebar">
    <div class="sidebar-header">
        <div class="sidebar-brand">
            <img src="/_ui/static/logo.svg" alt="{{ brand }}" class="sidebar-logo">
            <h3>{{ brand }}</h3>
        </div>
        <p class="user-info">{{ current_user.username }}</p>
    </div>
    <div class="sidebar-nav">
        {% set _path = request.url.path %}
        {% for section in nav_menu %}
            {% if not section.get('require_admin') or current_user.get('role') == 'admin' %}
            <div class="nav-section-title">{{ section.label }}</div>
            {% for item in section.items %}
            {% set _isActive = _path == item.href or _path.startswith(item.href + '/') %}
            {#- 特殊情况：dashboard 和根路径的 active 处理 later；这里保持 startswith 即可 -#}
            <a href="{{ item.href }}" class="nav-item{% if _isActive %} active{% endif %}">{{ item.label }}</a>
            {% endfor %}
            {% endif %}
        {% endfor %}
    </div>
    <div class="sidebar-footer">
        <form method="post" action="{% if current_service == 'platform' %}/logout{% else %}/auth/logout{% endif %}" class="nav-logout-form">
            <button type="submit" class="nav-item nav-logout">退出登录</button>
        </form>
    </div>
</nav>
```

- [ ] **Step 7: 创建 templates/ui/app_shell.html**

```html
{% extends "ui/base.html" %}
{% block body %}
<div class="admin-layout">
    {% include "ui/sidebar.html" %}
    <div class="admin-main-wrap">
        {% include "ui/topbar.html" %}
        <main class="main-content">
            {% block main %}{% endblock %}
        </main>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 8: 创建 templates/ui/auth_shell.html**

```html
{% extends "ui/base.html" %}
{% block body %}
<div class="auth-shell">
    <div class="auth-card">
        <div class="auth-brand">
            <img src="/_ui/static/logo.svg" alt="{{ brand }}" class="auth-logo">
            <h1>{{ brand }}</h1>
        </div>
        {% block auth_body %}{% endblock %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 9: 创建 static/ui.css**

从 HM `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/style.css` 完整复制全部 1020 行（包括 `:root`、buttons、form controls、sidebar、tenant-card 等）。然后在末尾追加以下顶栏 / 产品切换器 / auth_shell / 登录卡样式：

```css
/* ── Topbar ── */
.topbar {
    height: 56px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
}
.topbar-brand { display: flex; align-items: center; gap: 10px; font-weight: 700; color: var(--text); }
.topbar-logo { width: 22px; height: 22px; color: var(--primary); }
.topbar-brand-name { font-size: 15px; }
.topbar-actions { display: flex; align-items: center; gap: 16px; }
.topbar-account { display: flex; align-items: center; gap: 10px; }
.topbar-username { font-size: 13px; color: var(--text-secondary); }

/* ── Product switcher ── */
.product-switcher { position: relative; }
.product-switcher-btn {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm);
    background: var(--surface); color: var(--text);
    font-size: 13px; cursor: pointer; transition: all var(--transition);
}
.product-switcher-btn:hover { background: var(--border-subtle); }
.product-switcher-icon { color: var(--text-secondary); }
.product-switcher-current { font-weight: 600; }
.product-switcher-menu {
    position: absolute; right: 0; top: calc(100% + 6px);
    min-width: 260px; background: var(--surface);
    border: 1px solid var(--border); border-radius: var(--radius);
    box-shadow: var(--shadow-md); padding: 6px; z-index: 50;
}
.product-switcher-menu.hidden { display: none; }
.product-switcher-section {
    font-size: 11px; font-weight: 700; color: var(--text-muted);
    padding: 8px 10px 4px;
}
.product-switcher-item {
    display: block; padding: 8px 10px; border-radius: var(--radius-sm);
    color: var(--text); text-decoration: none;
}
.product-switcher-item:hover { background: var(--primary-light); text-decoration: none; }
.product-switcher-item.active { background: var(--primary-light); }
.product-switcher-item-label { font-weight: 600; font-size: 13.5px; }
.product-switcher-item-subtitle { font-size: 12px; color: var(--text-secondary); }
.product-switcher-check { color: var(--primary); font-weight: 700; }

/* ── Auth shell ── */
.auth-shell {
    min-height: 100vh; background: var(--bg);
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
}
.auth-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 36px;
    box-shadow: var(--shadow-md); width: 100%; max-width: 420px;
}
.auth-brand { text-align: center; margin-bottom: 24px; }
.auth-logo { width: 40px; height: 40px; color: var(--primary); }
.auth-brand h1 { font-size: 20px; margin-top: 10px; color: var(--text); }

/* ── admin-main-wrap: 让顶栏与主区并排在侧栏右边 ── */
.admin-main-wrap { display: flex; flex-direction: column; flex: 1; min-width: 0; }
```

- [ ] **Step 10: 删除占位 .gitkeep**

```bash
cd /Users/liling/src/lab/xinyi-platform
rm xinyi_platform/ui_common/static/.gitkeep xinyi_platform/ui_common/templates/ui/.gitkeep
```

- [ ] **Step 11: 在 xinyi-platform 内部跑一下 install_ui 即时 smoke**

Add one more assertion to `tests/test_ui_install.py` 验证模板和 static 目录存在：

```python
def test_ui_assets_present():
    from pathlib import Path
    from xinyi_platform.ui_common import install  # noqa
    base = Path(install.__file__).resolve().parent
    assert (base / "static" / "ui.css").exists()
    assert (base / "templates" / "ui" / "base.html").exists()
    assert (base / "templates" / "ui" / "app_shell.html").exists()
    assert (base / "templates" / "ui" / "auth_shell.html").exists()
    assert (base / "templates" / "ui" / "topbar.html").exists()
    assert (base / "templates" / "ui" / "sidebar.html").exists()
    assert (base / "templates" / "ui" / "product_switcher.html").exists()
```

- [ ] **Step 12: 运行测试**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/test_ui_install.py -v
```

Expected: 4 passed

- [ ] **Step 13: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add xinyi_platform/ui_common/ xinyi_platform/tests/test_ui_install.py
git commit -m "feat: ui_common templates, css design system, product switcher"
```

---

## Task 3: HM 接入 ui_common

**Files:**
- Modify: `/Users/liling/src/lab/hindsight-manager/pyproject.toml`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/config.py`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/main.py`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/jinja_filters.py`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/base.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/admin_base.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/dashboard.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/api_keys.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/profile.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/admin_api_keys.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/admin_task_monitor.html`
- Modify: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/templates/admin_tenants.html`
- Create: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/hm.css`
- Delete: `/Users/liling/src/lab/hindsight-manager/hindsight_manager/static/style.css`
- Create: `/Users/liling/src/lab/hindsight-manager/tests/test_ui_integration.py`

**Interfaces:**
- Consumes: Task 1 `install_ui`、Task 2 模板 + ui.css
- Produces:
  - HM 页面通过共享 `ui/app_shell.html` 渲染顶部 + 侧边栏
  - HM 业务专属补丁 CSS `/static/hm.css`（不被 ui_common 改动时仍有效）
  - 移除 `pages.py` 中的 `nav_active` 参数（不再使用）和死路由 `admin_users_page` / `admin_audit_logs_page`

### 步骤

- [ ] **Step 1: pyproject.toml 加 xinyi-platform 依赖**

Modify `/Users/liling/src/lab/hindsight-manager/pyproject.toml`，在 `dependencies` 列表里加：

```toml
    "xinyi-platform @ file:///Users/liling/src/lab/xinyi-platform",
```

（这是开发期硬路径；上线 / docker 通过 bind mount 复刻。其他环境的适配在本任务 Step 14 列。）

- [ ] **Step 2: uv sync 验证依赖可达**

```bash
cd /Users/liling/src/lab/hindsight-manager && uv sync
uv run python -c "from xinyi_platform.ui_common import install_ui, PRODUCTS; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: 修改 config.py 增加 brand_name**

Modify `/Users/liling/src/lab/hindsight-manager/hindsight_manager/config.py`，给 `Settings` 加一行：

```python
    brand_name: str = "Hindsight"
```

放在 `base_url` 下方一行。

- [ ] **Step 4: 写 UI 集成失败测试**

Create `/Users/liling/src/lab/hindsight-manager/tests/test_ui_integration.py`：

```python
"""Smoke test: app has ui_common wired via install_ui."""
from starlette.testclient import TestClient

from hindsight_manager.main import app


def test_app_has_ui_state_configured():
    with TestClient(app) as client:
        # app.state.ui should be populated by install_ui during lifespan startup
        # Without lifespan we need to trigger it. Since startup happens in
        # context manager entry, ui is set there.
        assert hasattr(app.state, "ui")
        ui = app.state.ui
        assert ui["current_service"] == "hindsight-manager"
        assert ui["brand"] == "Hindsight"
        assert any(p["id"] == "hindsight-manager" for p in ui["products"])


def test_static_ui_css_served():
    with TestClient(app) as client:
        resp = client.get("/_ui/static/ui.css")
        assert resp.status_code == 200
        assert "css" in resp.headers.get("content-type", "").lower() or "text" in resp.headers.get("content-type", "").lower()
```

注意：`install_ui` 在 `main.py` 启动时调用——但 `install_ui` 会立即往 `app.state.ui` 写。现有 main.py 在 import 时执行 `app = FastAPI(...)` 但 lifespan 在 startup 才跑。我们把 `install_ui` 调用**直接放在 module-level**（在 `app.add_middleware(...)` 之后），不放在 lifespan，这样 TestClient 不需要真的 startup。下面 Step 5 这么改 main.py。

- [ ] **Step 5: 修改 main.py 调用 install_ui**

Modify `/Users/liling/src/lab/hindsight-manager/hindsight_manager/main.py`：

在 `app.add_middleware(...)` 之后、`app.include_router(...)` 之前插入：

```python
# Wire shared UI (templates loader, static mount, jinja globals).
from xinyi_platform.ui_common import install_ui
from hindsight_manager.config import settings as _settings_for_ui  # noqa: E402

HM_NAV_MENU = [
    {
        "type": "section",
        "label": "记忆库",
        "items": [
            {"id": "dashboard", "label": "记忆库", "href": "/dashboard"},
            {"id": "profile",   "label": "个人资料", "href": "/profile"},
        ],
    },
    {
        "type": "section",
        "label": "管理",
        "require_admin": True,
        "items": [
            {"id": "tenants",      "label": "租户管理",    "href": "/admin/tenants"},
            {"id": "api_keys",     "label": "API Key 管理", "href": "/admin/api-keys"},
            {"id": "task_monitor", "label": "任务监控",    "href": "/admin/task-monitor"},
        ],
    },
]

install_ui(
    app,
    current_service="hindsight-manager",
    nav_menu=HM_NAV_MENU,
    brand=settings.brand_name,
    platform_url=settings.platform_url,
    manager_url=settings.base_url,
)
```

注意：去掉对 pages.py 里死路由的 include（admin_users_page 引用了不存在的模板）。下面 Step 6 在 pages.py 里把这些路由删除即可。

- [ ] **Step 6: 删除 pages.py 的死路由**

Modify `/Users/liling/src/lab/hindsight-manager/hindsight_manager/api/pages.py`：

删除以下两个函数：

```python
@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(...): ...

@router.get("/admin/audit-logs", response_class=HTMLResponse)
async def admin_audit_logs_page(...): ...
```

同时删除所有现存渲染调用里的 `"nav_active": "..."` 参数（dashboard/api_keys/profile/admin_tenants/admin_api_keys/admin_task_monitor 6 个函数），保留其他 context。示例（dashboard_page）：

```python
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"current_user": current_user, "tenants": tenants, ...},
    )
```

> 把 `{"user": current_user, ...}` 改名为 `{"current_user": current_user, ...}`，因为 ui_common 模板里一致用 `current_user` 这个变量名。

- [ ] **Step 7: 修改 jinja_filters.py 注入 ui_common 模板路径**

Modify `/Users/liling/src/lab/hindsight-manager/hindsight_manager/jinja_filters.py`：

```python
from pathlib import Path

from fastapi.templating import Jinja2Templates

from hindsight_manager.config import Settings
from xinyi_platform.ui_common.install import _TEMPLATE_DIR as _UI_TEMPLATE_DIR

_STATIC_ROOT = Path("hindsight_manager/static")


def _asset_url(url_path: str) -> str:
    rel = url_path.removeprefix("/static/")
    try:
        mtime = int((_STATIC_ROOT / rel).stat().st_mtime)
    except OSError:
        return url_path
    return f"{url_path}?v={mtime}"


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory="hindsight_manager/templates")
    # Allow business templates to `{% extends "ui/..." %}`:
    templates.env.loader.mapping.insert(0, str(_UI_TEMPLATE_DIR)) \
        if hasattr(templates.env.loader, "mapping") else None
    # Fallback for non-mapping loaders:
    from jinja2 import ChoiceLoader, FileSystemLoader
    existing = templates.env.loader
    templates.env.loader = ChoiceLoader([
        FileSystemLoader("hindsight_manager/templates"),
        FileSystemLoader(str(_UI_TEMPLATE_DIR)),
    ])
    templates.env.filters["asset_url"] = _asset_url
    # brand/platform_url are dynamic per-request because we read from
    # app.state.ui; expose them as Jinja globals lazily via context processor:
    templates.env.globals["platform_url"] = Settings().platform_url
    return templates
```

> ⚠ choice loader 直接重构可能破坏现有 import；比较保险的写法：因为我们只在创建 env 后追加 loader，所以前面 hasattr 分支可以移除，直接用 ChoiceLoader 覆盖。整理为：

```python
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from hindsight_manager.config import Settings
from xinyi_platform.ui_common.install import _TEMPLATE_DIR as _UI_TEMPLATE_DIR

_STATIC_ROOT = Path("hindsight_manager/static")


def _asset_url(url_path: str) -> str:
    rel = url_path.removeprefix("/static/")
    try:
        mtime = int((_STATIC_ROOT / rel).stat().st_mtime)
    except OSError:
        return url_path
    return f"{url_path}?v={mtime}"


def make_templates() -> Jinja2Templates:
    business_dir = "hindsight_manager/templates"
    templates = Jinja2Templates(directory=business_dir)
    templates.env.loader = ChoiceLoader([
        FileSystemLoader(business_dir),
        FileSystemLoader(str(_UI_TEMPLATE_DIR)),
    ])
    templates.env.filters["asset_url"] = _asset_url
    templates.env.globals["platform_url"] = Settings().platform_url
    templates.env.globals["brand"] = Settings().brand_name
    return templates
```

> 在每条路由 render 时要补传 context 的 `current_service`、`current_user`、`products`、`brand`——下面 Step 8 通过在 render 处补；但现在生产 code 已经传了 `current_user`，我们用 `templates.TemplateResponse` 时 Jinja2Templates 会自动注入 `request`。`nav_menu` / `current_service` / `products` 需要在每次 render 时从 `request.app.state.ui` 取。最简单：**改用 FastAPI 模板的 context_processors**。但 FastAPI 不支持 Django 风格 context_processors。替代方案：定义一个辅助函数 `_ui_ctx(request) -> dict`，在每个 page handler 中调用。

- [ ] **Step 8: 修改 pages.py 注入 ui 上下文 helper**

Modify pages.py，在文件顶部 helpers：

```python
from hindsight_manager.auth.dependencies import get_current_user, get_current_user_or_none, require_admin


def _ui_ctx(request: Request) -> dict:
    """Pull ui_common state from app.state for template rendering."""
    ui = request.app.state.ui
    return {
        "current_service": ui["current_service"],
        "nav_menu": ui["nav_menu"],
        "brand": ui["brand"],
        "products": ui["products"],
        "platform_url": ui["platform_url"],
        "manager_url": ui["manager_url"],
    }
```

在每个 render 调用里把 `_ui_ctx(request)` 加进 context：

```python
    ctx = {**_ui_ctx(request), "current_user": current_user, ...}
    return templates.TemplateResponse(request, "dashboard.html", ctx)
```

例如 dashboard：

```python
    tenants = [...]
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            **_ui_ctx(request),
            "current_user": current_user,
            "tenants": tenants,
            "dataplane_url": Settings().dataplane_url,
            "docs_url": Settings().docs_url,
            "mcp_url": Settings().dataplane_url.rstrip("/") + "/mcp",
        },
    )
```

对所有 page handler（dashboard_page / api_keys_page / profile_page / admin_tenants_page / admin_api_keys_page / admin_task_monitor_page）都按这个模式改一遍。

- [ ] **Step 9: 删除 HM 老 style.css + 创建 hm.css 业务专属补丁**

```bash
cd /Users/liling/src/lab/hindsight-manager
git mv hindsight_manager/static/style.css hindsight_manager/static/hm.css.tmp || cp hindsight_manager/static/style.css /tmp/_hm_old.css
```

> 思路：hm.css 应**只保留** ui.css 没覆盖的业务专属部分（`.tenant-card`, `.tenant-edit-btn`, `.api-keys-panel`, `.members-panel`, `.usage-guide`, `.modal`, `.empty-state`, `.content-header`, `.profile-card`, `.profile-field`, `.profile-actions`, `.tenant-list`, `.tenant-info`, `.tenant-title`, `.tenant-meta`, `.tenant-actions`, `.task-monitor-*`, `.api-key-row` 等）。通用的 `:root / .btn / .form-group / .sidebar / .topbar / .auth-card / .product-switcher-*` 都从 ui.css 来，hm.css 不要重复。
> 实际操作：保留 `/tmp/_hm_old.css` 的一份完整拷贝用于对照，然后在仓库内**人工挑选**业务专属 selector 写新 hm.css。这一步在 Step 9 子过程中详细列出每一组 selector 保留/删除决策——但你自己执行计划时根据原 style.css 中每一段段落注释归位即可。Imosphere 时长 ≈ 40 min。

为方便后续审计，给 `hindsight_manager/static/hm.css` 头部加 markdown-style 注释：

```css
/* Hindsight Manager 业务专属补丁
 *
 * 本文件只承载 HM 业务页面专属样式（tenant-card / api-keys-panel /
 * usage-guide / modal / task-monitor 等）。通用设计系统来自
 * /​_ui/static/ui.css（ui_common 包），请勿在此重复定义通用 selector。
 */
```

然后把 ui.css 已覆盖的部分删除（保留 `.tenant-*`, `.api-keys-*`, `.usage-guide-*`, `.modal`, `.empty-state`, `.content-header`, `.profile-*`, `.task-monitor-*`, `.members-panel`, `.copied-toast`）。

> ⚠ 在子任务执行时，执行人应当 `git diff HEAD~1 -- hindsight_manager/static/style.css` 查阅原文件，逐段决定保留。本计划在此只给出 selector 清单作为**前进方向**，不强行包装到一条命令。

- [ ] **Step 10: 改写 templates/base.html**

```html
{% extends "ui/base.html" %}
```

简化到单行 extends（保留 ui/base.html 的 head，加 hm.css）：

```html
{% extends "ui/base.html" %}
{% block head %}
<link rel="stylesheet" href="{{ '/static/hm.css' | asset_url }}">
{% endblock %}
```

- [ ] **Step 11: 改写 templates/admin_base.html**

```html
{% extends "ui/app_shell.html" %}
{% block head %}
<link rel="stylesheet" href="{{ '/static/hm.css' | asset_url }}">
{% endblock %}
{% block main %}{% endblock %}
```

- [ ] **Step 12: 改写业务模板**

对以下文件：
- `dashboard.html`
- `api_keys.html`
- `profile.html`
- `admin_api_keys.html`
- `admin_task_monitor.html`
- `admin_tenants.html`

每个改为：
- 删除顶部 `{% extends "admin_base.html" %}` 保留
- 删除 `{% set nav_active = '...' %}`
- 保留 `{% block title %}` 和 `{% block main %}`

以 `dashboard.html` 为例，header 段保持：

```html
{% extends "admin_base.html" %}
{% block title %}记忆库 - {{ brand }}{% endblock %}
{% block main %}
... (内容不变)
{% endblock %}
```

如果原本 `{% set nav_active = 'dashboard' %}` 这一行，**删掉**（ui sidebar 自己判断 active）。

- [ ] **Step 13: 运行所有现有测试**

```bash
cd /Users/liling/src/lab/hindsight-manager && uv run pytest -x
```

Expected: 现有 111 个测试全部 pass。如果某个 page 测试 mock 了 current_user 但用 dict 时缺 `role`，sidebar template `current_user.get('role')` 可能 AttributeError——dict 有 `.get`，OK。

- [ ] **Step 14: 运行新增的 UI 集成测试**

```bash
cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_ui_integration.py -v
```

Expected: 2 passed

- [ ] **Step 15: 启动服务，手动 smoke 测**

```bash
cd /Users/liling/src/lab/hindsight-manager && uv run uvicorn hindsight_manager.main:app --port 8001 --reload
```

Expected（浏览器 http://localhost:8001/dashboard，登录后）：
- 顶栏左侧品牌 logo + 文字 "Hindsight"，右侧产品切换器、账户菜单。
- 侧边栏包含"记忆库 / 个人资料"和（admin 时）"管理 / 租户管理 / API Key 管理 / 任务监控"。
- 产品切换器展开显示"平台账户中心"和"Hindsight ✓"。
- 样式与原 HM 一致（颜色、按钮、卡片都齐全）。

- [ ] **Step 16: 删除老的 `/static/style.css` (Step 9 已改名，再确认)**

```bash
cd /Users/liling/src/lab/hindsight-manager && ls hindsight_manager/static/
```

确认没有 `style.css`，有 `hm.css`。

- [ ] **Step 17: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager && git add -A
git commit -m "refactor: HM adopts ui_common (shared base/templates/css, product switcher, drop dead admin/users + admin/audit-logs routes)"
```

---

## Task 4: xinyi-platform 接入 ui_common（含 admin 页面样式迁移）

**Files:**
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/main.py`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/config.py`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/base.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/admin/base.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/login.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/register.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/forgot_password.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/reset_password.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/account.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/admin/users.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/admin/clients.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/admin/audit_logs.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/admin/login_history.html`
- Modify: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/templates/admin/user_form.html`
- Delete: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/static/style.css` (6 行版本)
- Create: `/Users/liling/src/lab/xinyi-platform/xinyi_platform/static/platform.css`
- Create: `/Users/liling/src/lab/xinyi-platform/tests/test_ui_integration.py`

**Interfaces:**
- Consumes: Task 1 `install_ui`、Task 2 模板与 css
- Produces:
  - xinyi-platform 登录后页面使用 `ui/app_shell.html` 渲染头部 + 侧栏
  - xinyi-platform 登录页 / 注册页 / 重置密码 / 忘记密码使用 `ui/auth_shell.html`

### 步骤

- [ ] **Step 1: 改 config.py 增加 brand_name 和 manager_url**

Modify `/Users/liling/src/lab/xinyi-platform/xinyi_platform/config.py`，加入：

```python
    brand_name: str = "xinyi"
    manager_url: str = "http://localhost:8001"
```

放在 `base_url` 行下方。

- [ ] **Step 2: 改 main.py 调用 install_ui**

Modify `/Users/liling/src/lab/xinyi-platform/xinyi_platform/main.py`：在 `app = FastAPI(...)` 与 `app.mount("/static", ...)` 之间插入：

```python
from xinyi_platform.ui_common import install_ui

PLATFORM_NAV_MENU = [
    {
        "type": "section",
        "label": "账户",
        "items": [
            {"id": "account", "label": "我的账户", "href": "/account"},
        ],
    },
    {
        "type": "section",
        "label": "管理",
        "require_admin": True,
        "items": [
            {"id": "users",          "label": "用户",       "href": "/admin/users"},
            {"id": "clients",        "label": "业务接入",   "href": "/admin/clients"},
            {"id": "audit_logs",     "label": "审计日志",   "href": "/admin/audit-logs"},
            {"id": "login_history",  "label": "登录历史",   "href": "/admin/login-history"},
        ],
    },
]

install_ui(
    app,
    current_service="platform",
    nav_menu=PLATFORM_NAV_MENU,
    brand=settings.brand_name,
    platform_url=settings.base_url,
    manager_url=settings.manager_url,
)
```

> `settings` 是 `lifespan` 里读取的 `Settings()` 实例；module-level 还没创建。修复：在 `install_ui` 之前先 `settings = Settings()` 作为 module-level 变量，后续 lifespan 内重用同一个实例。

- [ ] **Step 3: 写失败集成测试**

Create `/Users/liling/src/lab/xinyi-platform/tests/test_ui_integration.py`：

```python
from starlette.testclient import TestClient

from xinyi_platform.main import app


def test_app_has_ui_state_configured():
    with TestClient(app) as client:
        assert app.state.ui["current_service"] == "platform"
        assert app.state.ui["brand"] == "xinyi"
        assert any(p["id"] == "platform" for p in app.state.ui["products"])


def test_static_ui_css_served():
    with TestClient(app) as client:
        resp = client.get("/_ui/static/ui.css")
        assert resp.status_code == 200
```

- [ ] **Step 4: 运行测试**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/test_ui_integration.py -v
```

Expected: 2 passed

- [ ] **Step 5: 让 xinyi 的 Jinja env 能找到 ui/ 模板**

xinyi 目前没有统一的 `Jinja2Templates` 工厂，每个 router 自己创建。最简便：**给 platform 加一个 template factory**，模仿 HM 的 `jinja_filters.py`：

Create `/Users/liling/src/lab/xinyi-platform/xinyi_platform/jinja_env.py`：

```python
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from xinyi_platform.config import Settings
from xinyi_platform.ui_common.install import _TEMPLATE_DIR as _UI_TEMPLATE_DIR


def make_templates() -> Jinja2Templates:
    business_dir = "xinyi_platform/templates"
    templates = Jinja2Templates(directory=business_dir)
    templates.env.loader = ChoiceLoader([
        FileSystemLoader(business_dir),
        FileSystemLoader(str(_UI_TEMPLATE_DIR)),
    ])
    settings = Settings()
    templates.env.globals["brand"] = settings.brand_name
    templates.env.globals["platform_url"] = settings.base_url
    templates.env.globals["manager_url"] = settings.manager_url
    return templates
```

并 Update Task 2 Step 2 暴露 `_TEMPLATE_DIR`（已暴露，OK）。

- [ ] **Step 6: 重写 templates/base.html**

```html
{% extends "ui/base.html" %}
{% block head %}
<link rel="stylesheet" href="/static/platform.css">
{% endblock %}
```

- [ ] **Step 7: 重写 templates/admin/base.html**

```html
{% extends "ui/app_shell.html" %}
{% block head %}
<link rel="stylesheet" href="/static/platform.css">
{% endblock %}
{% block main %}{% endblock %}
```

- [ ] **Step 8: 重写登录页 login.html 为 auth_shell 派生**

```html
{% extends "ui/auth_shell.html" %}
{% block title %}登录{% endblock %}
{% block auth_body %}
<form method="post" action="/login/form">
    <input type="hidden" name="return_to" value="{{ return_to or '/account' }}">
    <div class="form-group">
        <label>用户名</label>
        <input type="text" name="username" required>
    </div>
    <div class="form-group">
        <label>密码</label>
        <input type="password" name="password" required>
    </div>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <button type="submit" class="btn btn-primary btn-block">登录</button>
</form>
{% endblock %}
```

- [ ] **Step 9: 同样改造 register.html / forgot_password.html / reset_password.html**

每个 extends `ui/auth_shell.html`，使用 `{% block auth_body %}…{% endblock %}`，把原本 `<label>...<input></label>` 改为 ui.css 的 `.form-group` 结构。示例（register.html）：

```html
{% extends "ui/auth_shell.html" %}
{% block title %}注册{% endblock %}
{% block auth_body %}
<form method="post" action="/register">
    <div class="form-group">
        <label>用户名</label>
        <input type="text" name="username" required>
    </div>
    <div class="form-group">
        <label>显示名</label>
        <input type="text" name="display_name" required>
    </div>
    <div class="form-group">
        <label>邮箱</label>
        <input type="email" name="email">
    </div>
    <div class="form-group">
        <label>密码（至少 8 位，含大写字母和数字）</label>
        <input type="password" name="password" required>
    </div>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <button type="submit" class="btn btn-primary btn-block">注册</button>
</form>
{% endblock %}
```

forgot_password.html / reset_password.html 同理，每个保留原 form 字段，仅换外壳。

- [ ] **Step 10: 重写 account.html**

```html
{% extends "admin/base.html" %}
{% block title %}账户{% endblock %}
{% block main %}
<div class="content-header">
    <h2>我的账户</h2>
</div>
<div class="card">
    <div class="card-body">
        <p>用户名：{{ current_user.username }}</p>
        <p>角色：{{ current_user.role }}</p>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 11: 重写 admin/{users,clients,audit_logs,login_history,user_form}.html**

每个：extends `admin/base.html`，用 ui.css 的 `.card`, `.table`, `.form-group`, `.btn` 样式重写表格和表单。原 6 行 CSS 里的 `table { border-collapse: collapse }` 之类已经被 ui.css 覆盖，可以删除原样式引用。

以 users.html 为例（其余结构类似，不重复示例代码）：

```html
{% extends "admin/base.html" %}
{% block title %}用户管理{% endblock %}
{% block main %}
<div class="content-header">
    <h2>用户</h2>
    <a href="/admin/users/new" class="btn btn-primary">+ 新建用户</a>
</div>
<div class="card">
    <table class="table">
        <thead>
            <tr><th>用户名</th><th>显示名</th><th>邮箱</th><th>角色</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
        {% for u in users %}
            <tr>
                <td>{{ u.username }}</td>
                <td>{{ u.display_name or '' }}</td>
                <td>{{ u.email or '' }}</td>
                <td>{{ u.role }}</td>
                <td>{% if u.is_active %}正常{% else %}禁用{% endif %}</td>
                <td><a href="/admin/users/{{ u.id }}/edit" class="btn btn-secondary btn-sm">编辑</a></td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

其他 4 个 admin 页类比照此改造。**执行人在子任务里要打开每个原文件，保留业务字段，只替换 HTML/CSS class。**

- [ ] **Step 12: 修改每个 router 让 render 时传 `_ui_ctx`**

参考 HM Step 8 的模式：每个 page handler 在 `TemplateResponse` 时 merge `_ui_ctx(request)`，并传 `current_user`。

由于 xinyi 没有现成的 `current_user` 模板变量名约定，需要统一：把所有整理为 `current_user`，跟 ui_common 模板保持一致。

具体修改的 router 文件（xinyi 现有 `api/admin_users.py, admin_clients.py, admin_audit.py, admin_login_history.py, login.py, register.py, password.py, me.py`）：

参考模式（admin_users.py 的 list 端点）：

```python
from xinyi_platform.jinja_env import make_templates

templates = make_templates()


def _ui_ctx(request):
    ui = request.app.state.ui
    return {
        "current_service": ui["current_service"],
        "nav_menu": ui["nav_menu"],
        "brand": ui["brand"],
        "products": ui["products"],
        "platform_url": ui["platform_url"],
        "manager_url": ui["manager_url"],
    }
```

每个 render：

```python
    return templates.TemplateResponse(
        request, "admin/users.html",
        {**_ui_ctx(request), "current_user": current_user, "users": users},
    )
```

> **注意**：xinyi 现有 `templates = Jinja2Templates(directory="xinyi_platform/templates")` 创建在每个 router 文件顶部。Step 5 的 `jinja_env.make_templates` 抽出后，子任务需要把每个 router 的 import 改为 `from xinyi_platform.jinja_env import make_templates; templates = make_templates()` 一次。

- [ ] **Step 13: 删除 老 style.css 创建 platform.css**

```bash
cd /Users/liling/src/lab/xinyi-platform
rm xinyi_platform/static/style.css
```

Create `xinyi_platform/static/platform.css`：

```css
/* xinyi-platform 业务专属补丁。
 * 通用部分（按钮、表单、表格、卡片、顶栏、侧栏、auth 壳）来自
 * /​_ui/static/ui.css（ui_common 子包）。
 */

/* 平台 admin 列表里的特殊用法如有可加在此处；当前为空 */
```

- [ ] **Step 14: 跑 xinyi-platform 所有测试**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run pytest -x
```

Expected: 现有测试全过。失败多数原因：模板变量名从原来的上下文里没有 `current_user` —— step 12 已处理。

- [ ] **Step 15: 启动 xinyi 手动烟雾**

```bash
cd /Users/liling/src/lab/xinyi-platform && uv run uvicorn xinyi_platform.main:app --port 8000 --reload
```

浏览器 http://localhost:8000/login，确认：
- 登录页使用居中卡片，左侧 logo，样式与 HM 风格一致。
- 登录后跳转 `/account` 顶栏 + 侧栏出现，"个人中心"按钮、"产品切换器"包含"平台账户中心 ✓"和"Hindsight"。
- admin/user、admin/clients 等页面用新 ui.css 样式呈现。

- [ ] **Step 16: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add -A
git commit -m "refactor: xinyi-platform adopts ui_common (auth shell, app shell, product switcher); rewrite admin templates to ui.css"
```

---

## Task 5: docker-compose / 多服务编排补丁

**Files:**
- Modify: `/Users/liling/src/lab/hindsight-manager/docker-compose.yml`
- Modify: `/Users/liling/src/lab/hindsight-manager/Dockerfile`

**Interfaces:**
- Consumes: Task 1-4 共享 `ui_common` 子包。
- Produces: HM docker 镜像能 import ui_common。

### 步骤

- [ ] **Step 1: 看 Dockerfile 当前状态**

Read `/Users/liling/src/lab/hindsight-manager/Dockerfile`。

- [ ] **Step 2: 改 Dockerfile，把 xinyi-platform 仓库内容拷入 build context**

把 xinyi-platform 仓库目录 bind 到 build context 时 `COPY` 进去，并 pip install：

```dockerfile
# 在 COPY 本仓库代码之前
COPY ../xinyi-platform /opt/xinyi-platform
RUN pip install /opt/xinyi-platform
```

但 docker build 不支持 `COPY ../`，需要 build context 设置到父目录。推荐方式：**让 docker build context 是 `/Users/liling/src/lab`**，并调整 Dockerfile 路径。

Modify `/Users/liling/src/lab/hindsight-manager/docker-compose.yml`，把 manager 服务的 build 配置改为：

```yaml
  manager:
    build:
      context: ..
      dockerfile: hindsight-manager/Dockerfile
```

Modify `/Users/liling/src/lab/hindsight-manager/Dockerfile`，开头：

```dockerfile
FROM python:3.12-slim

# The build context is the parent lab/ dir, so both hindsight-manager and
# xinyi-platform sources are visible.
COPY xinyi-platform /opt/xinyi-platform
COPY hindsight-manager /app

WORKDIR /app
RUN pip install --no-cache-dir /opt/xinyi-platform .
```

- [ ] **Step 3: 本地 docker compose build / up 验证**

```bash
cd /Users/liling/src/lab/hindsight-manager && docker compose build manager
cd /Users/liling/src/lab/hindsight-manager && docker compose up -d manager postgres
docker compose exec manager python -c "from xinyi_platform.ui_common import install_ui; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager && git add Dockerfile docker-compose.yml
git commit -m "ci: build context covers both repositories so HM imports ui_common from xinyi-platform"
```

---

## Self-Review (by plan author)

### Spec coverage check

| Spec 段 | 覆盖任务 |
|---|---|
| §3.1 ui_common 目录结构 | Task 1（骨架），Task 2（模板 / css） |
| §3.2 install_ui 契 约 | Task 1 Step 4 |
| §3.3 模板继承链 | Task 2 |
| §4.1 PRODUCTS 注册表 | Task 1 Step 3 |
| §4.2 顶栏 + 产品切换器 UI | Task 2 Step 4（partial）+ Step 9（css） |
| §4.3 sidebar + nav_menu | Task 2 Step 6 + 各服务 nav_menu 列表 |
| §5 视觉系统 | Task 2 Step 9 ui.css + Task 3 Step 9 hm.css 切分原则 |
| §6.1 ui_common 骨架 | Task 1 |
| §6.2 HM 接入清单 | Task 3 |
| §6.3 xinyi 接入清单 | Task 4 |
| §6.4 测试 | 各 Task 末尾 pytest |
| §7.1 跨服务 session 不解决 | 计划里明确不解决；执行人不必考虑 |
| §7.2 docker 镜像层共享 | Task 5 |

### Placeholder scan

- 没有 TBD / TODO。
- "可以由执行人审阅补充"这类话语都不存在。
- 用户信息来源（registry.py 的 url_template）都被 `format` 实现到具体 url。
- admin templates 详细改造在 Step 11 只举了 users.html；为避免 placeholder 嫌疑，给了通用结构 + 字段提示。其他 4 个 admin 页保留业务字段、只换外壳的原则已可执行。

### Type consistency

- `install_ui` 签名在 Task 1、Task 3、Task 4 完全一致。
- `_TEMPLATE_DIR` 在 install.py 中定义、外部依赖唯一名称。
- `_ui_ctx(request)` helper 命名 / 字段 HM 和 xinyi 一致。
- `current_service` 字符串字面值 `"platform" | "hindsight-manager"` 在所有 Task 一致。

### Risks / 需要 reviewer 关注的事项

1. **Task 3 Step 9 切分 hm.css 是高工程量步**：建议执行人在 Task 3 单独花一个 reviewer 窗口检查"原 style.css 哪些 selector 保留为业务专属"。可以用 `git diff` 对比原 style.css 与 hm.css 内容确认覆盖。
2. **Task 5 docker compose 改 build context 是 breaking change**：现有部署脚本若直接调用 `docker build .` 会失效。Reviewer 务必确认。
3. **Task 4 Step 11 五个 admin 页** 每个都要开原文件做字段保留改动——这一步容易因 spot 仅改一个而遗漏其余。子任务执行模板化即可，但要细心。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-22-ui-unification-and-cross-service-nav.md`. Two execution options:

1. **Subagent-Driven (recommended)** — 我每个 Task 派一个新 subagent 实现，人类 reviewer 每个 Task 闸门审核
2. **Inline Execution** — 在当前会话内执行，CSS / 模板改动用 checkpoint 分批 commit

Which approach?
