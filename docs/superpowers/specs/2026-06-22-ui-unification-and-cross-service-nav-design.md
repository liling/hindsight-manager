# UI 统一与跨业务导航重构 — 设计文档

- **日期**: 2026-06-22
- **状态**: 设计已对齐各节，待 spec 审阅
- **作者**: Ling Li (via brainstorming session)

## 1. 背景与动机

平台 / 业务两个层的代码刚刚完成分离：

- `xinyi-platform` (8000)：承担 IdP / OAuth provider / 用户管理 / 审计 / 登录历史等"平台层"职责。
- `hindsight-manager` (8001)：作为"业务层第一个服务"，承担 RAG 记忆库相关业务（租户、API Key、任务监控、对数据平面的代理）。

但 UI 层面遗留两个问题，且很快会随着新业务上线被放大：

1. **hindsight-manager 自身把"业务功能"和已经被迁走的"平台功能"混在一起**：
   - admin_base.html 里仍保留"用户管理 ↗、审计日志 ↗、登录历史 ↗"等链接，点击后用 `target="_blank"` 跳到 xinyi-platform，体验割裂。
2. **两个服务的视觉风格完全不统一、互相也无法顺畅通跳**：
   - HM 有自己的 `style.css`（1020 行）+ 一套设计 token。
   - xinyi-platform 的 `style.css` 只有 6 行裸 HTML 表单样式。
   - 跨跳没有回头路径。

后续还会加入其它业务（每个业务=独立服务）。在加新业务之前把样式与导航改好，避免出现"每加一个业务就抄一份样板"的扩散。

## 2. 范围与目标

### 目标

在加入新业务之前，把"前端风格 / 导航"改造成一个可持续演化、跨服务一致的体系。

具体产出：

- 一个共享的 UI 子包 `xinyi_platform/ui_common`，承载统一设计系统与页面骨架（顶栏 + 侧边栏 + 产品切换器 + auth 外壳）。
- 全局产品切换器：跨服务跳转的统一入口。
- HM 与 xinyi-platform 都接入 ui_common，移除各自的老 CSS / 老 base 模板。
- 平台层（xinyi-platform）admin 页面迁移到新样式（视觉重写、不动业务逻辑）。

### 明确不做

- 不引入 SPA / Build 工具链 / 前端框架（继续手写 CSS + Jinja2）。
- 不改 OAuth2 / IdP 的协议层，跨服务登录沿用现有方案（access token + refresh token）。
- 不做服务发现 / 动态菜单（全局产品列表硬编码在 `ui_common/registry.py`）。
- 不引入新的后端框架 / 中间件。
- HM 内部已有的业务功能（记忆库、租户、API Key、成员、任务监控）只迁移模板/CSS，不动业务逻辑。

### 记录但不在本期解决

- 跨子域 SSO（xinyi session cookie 升级到父域）—— 后续单独立项。
- 品牌名最终形态 —— 用 `brand_name` 配置字段占位，本次起一个默认值即可。
- 未来业务多了 PRODUCTS 列表怎么做版本同步 —— 暂时打包配置，后续视需要再做服务发现。

## 3. 总体架构

### 3.1 单一事实源：`xinyi_platform/ui_common` 子包

位置：放在 `xinyi-platform` 仓库内，路径 `xinyi_platform/ui_common/`。

理由：

- xinyi-platform 本就是平台层的服务，UI 公共件与之血缘最近。
- 避免新建独立仓库带来的发布流程开销（本期暂不做版本化发布）。
- HM 通过 `pyproject.toml` 依赖 xinyi-platform 包，加上 `path = "../xinyi-platform"` 在本地 / 通过 docker 多 stage copy 在镜像层共享。

目录结构：

```
xinyi_platform/ui_common/
├── __init__.py                  # 导出 install_ui / PRODUCTS / 相关 dataclass
├── install.py                   # install_ui(app, current_service, nav_menu, brand, ...) 实现
├── registry.py                  # PRODUCTS 常量 + resolve_products(urls)
├── static/
│   ├── ui.css                   # 通用设计系统（基于 HM 当前 1020 行 style.css 提炼）
│   └── logo.svg                 # 占位 logo
├── templates/
│   └── ui/
│       ├── base.html            # 页面骨架：html/head/body + {% block %} hooks
│       ├── app_shell.html       # 登录后 shell：顶栏 + 侧边栏 + 主区
│       ├── auth_shell.html      # 未登录外壳：居中卡片（登录 / 注册 / 重置密码 / 忘记密码）
│       ├── topbar.html          # 顶栏 partial（品牌 + 产品切换器 + 账户菜单）
│       ├── sidebar.html         # 侧边栏 partial（根据 nav_menu + current_service 渲染）
│       ├── product_switcher.html# 顶栏中的全局产品下拉
│       └── components/          # 通用可复用片段（按钮、表单组、卡片、modal 等，按需）
└── templatetags/
    └── __init__.py              # 必要时的 Jinja filter（如 is_active）
```

### 3.2 服务集成方式

每个服务（含 xinyi-platform 自己）在 `main.py` 启动时调用：

```python
from xinyi_platform.ui_common import install_ui

install_ui(
    app,
    current_service="hindsight-manager",   # 决定侧边栏 / 顶栏 active 状态
    nav_menu=HM_NAV_MENU,                   # 本服务的侧边栏菜单描述
    brand=settings.brand_name,
    platform_url=settings.platform_url,
    manager_url=settings.manager_url,       # 业务侧可空，平台侧必填
)
```

`install_ui` 做三件事：

1. 在 Jinja2 `FileSystemLoader` 链最前面加入 ui_common 的 `templates/` 目录（业务自身的 loader 在后，**允许业务 override** 任何 ui 模板）。
2. `app.mount("/_ui/static", StaticFiles(directory=ui_common_static))` —— 路径前缀 `/_ui`，避免与业务自己的 `/static` 冲突。
3. 注入 Jinja2 globals：`current_service`, `products`（解析后）, `brand`, `platform_url`。

所有服务都挂载同一路径 `/_ui/static`，因此 `<link href="/_ui/static/ui.css">` 在任一服务下都能解析到同一份资源。

### 3.3 模板继承链

```
ui/base.html                       # 骨架
├── ui/app_shell.html              # 登录后外壳（顶栏 + 侧边栏 + 主区）
│   └── hindsight_manager/templates/dashboard.html
│   └── hindsight_manager/templates/admin_*.html
│   └── xinyi_platform/templates/admin/{users,clients,...}.html
└── ui/auth_shell.html             # 未登录外壳（居中卡片）
    └── xinyi_platform/templates/login.html
    └── xinyi_platform/templates/register.html
    ...
```

业务模板仅需要 `{% extends "ui/app_shell.html" %}` + `{% block main %}...{% endblock %}`。

## 4. 全局产品切换器与导航数据

### 4.1 PRODUCTS 注册表

`ui_common/registry.py` 维护一个静态全局列表：

```python
PRODUCTS = [
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
    # 未来新业务就往这里加一项
]
```

`install_ui` 在注入 globals 前根据传入的 `platform_url` / `manager_url` 等字段，把 `url_template` 渲染成最终 URL。

### 4.2 UI 呈现

顶栏右侧放置一个紧凑按钮作为产品切换器：

```
[ ◆ Hindsight  ▾ ]      ← 显示当前服务名 + 箭头
```

点击展开下拉，按 `kind` 分两组渲染：

```
─────────────
平台
  • 平台账户中心          ← 点击跳 {platform_url}/account
─────────────
业务
  • Hindsight  ✓         ← 当前服务打勾（active）
  • （未来业务列表）
─────────────
```

跳转用普通 `<a href>` 即可，不触发额外协议流程（参见 §6.1 跨服务 session 语义）。

### 4.3 侧边栏

每个服务向 `install_ui` 传入自己的 `nav_menu`，list-of-sections 结构：

```python
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
```

侧边栏 partial：

- 基于 `current_service` + 用户 role + 当前请求路径自动计算 active（不再在页面里 `{% set nav_active = '...' %}`）。
- `{% if section.require_admin and not user.is_admin %}` 跳过整个 section。

## 5. 视觉设计系统

### 5.1 重构原则

**直接以 HM 现有 1020 行 `style.css` 为基底迁移**，不做激进重设计。已有的按钮、表单、卡片、modal、表格这套已经被产品验证，继续沿用。

基调：

- 主色 `#4f46e5`（现有 indigo）
- 暗色侧边栏 `#0f172a`
- 浅色主区背景 `#f8f9fb`
- 圆角 / 阴影等沿用现状

### 5.2 补齐项

1. **顶栏**：新增组件，高 56px，左侧品牌 + logo，右侧产品切换器 + 账户菜单（头像 / 登出）。
2. **auth_shell**：新增居中卡片布局，登录 / 注册 / 重置密码 / 忘记密码统一使用。
3. **product_switcher**：新增下拉样式。

### 5.3 拆分 ui.css 与业务补丁 CSS

- `ui_common/static/ui.css` 只承载**通用**部分：reset、tokens、按钮、表单、表格、卡片、modal、layout、顶栏、侧边栏、auth shell、产品切换器。
- HM 中**业务专属**样式（如 `.tenant-card`, `.api-keys-panel`, `.usage-guide`）保留在 `hindsight_manager/static/hm.css`，业务模板在 `{% block head %}` 里追加引用。
- xinyi-platform 的 admin 列表与表单业务专属样式按需保留在 `xinyi_platform/static/platform.css`。

### 5.4 不做

- 不引入图标库（沿用现有内联 SVG 风格）。
- 不做主题切换 / 暗色模式。
- 不引入 Tailwind / 设计系统库。

## 6. 实施变更清单

### 6.1 A. 在 xinyi-platform 仓库新建 ui_common

新增（详见 §3.1 目录结构）。

`install_ui` 的契约（与 §3.2 示例一致，关键字参数；新增服务 URL 一律按需加显式参数，不到 3 个之前不抽象成 dict）：

```python
def install_ui(
    app: FastAPI,
    *,
    current_service: str,           # "platform" | "hindsight-manager" | ...
    nav_menu: list[dict],            # 见 §4.3 结构
    brand: str,
    platform_url: str,
    manager_url: str | None = None,  # 平台侧渲染 HM 入口时使用；业务侧可空
) -> None: ...
```

### 6.2 B. Hindsight Manager 接入

| 文件 | 变更 |
|---|---|
| `pyproject.toml` | 增加 `xinyi-platform = { path = "../xinyi-platform" }`（本地开发），生产 docker 镜像通过多 stage copy 包入 |
| `main.py` | 启动时调用 `install_ui(app, current_service="hindsight-manager", ...)` |
| `config.py` | 新增 `brand_name: str = "Hindsight"`（默认值可在产品最终确定后调整，配置字段先落地）|
| `templates/base.html` | 缩减为 `{% extends "ui/base.html" %}` 兜底；删除原有 head 引用 |
| `templates/admin_base.html` | 改为 `{% extends "ui/app_shell.html" %}`，移除自定义侧边栏（交给 ui/sidebar），保留 `{% block main %}` |
| `templates/dashboard.html`, `api_keys.html`, `profile.html`, `admin_*.html` | 改为 extends 新 app_shell；删除 `{% set nav_active = ... %}`；业务专属 class 中的通用部分替换为 ui.css 等价 class |
| `static/style.css` | **删除**（被 ui.css 替代）|
| 新增 `static/hm.css` | 承接业务专属补丁（如 `.tenant-card` / `.api-keys-panel` / `.usage-guide`）|
| `static/admin.js` / `app.js` / `task_monitor.js` | 保留，路径不变 |
| admin 菜单项 | **删除**侧边栏中的"用户管理 ↗ / 审计日志 ↗ / 登录历史 ↗"（跨服务改由顶部产品切换器承载）|

### 6.3 C. xinyi-platform 接入

| 文件 | 变更 |
|---|---|
| `main.py` | 调用 `install_ui(app, current_service="platform", ...)` |
| `config.py` | 新增 `brand_name: str = "xinyi"`、`manager_url: str`（用于产品切换器渲染 HM 入口；默认值不含端口以避免硬编码）|
| `templates/base.html` | 改为兜底 `{% extends "ui/base.html" %}` |
| `templates/admin/base.html` | 改为 `{% extends "ui/app_shell.html" %}` |
| `templates/login.html` / `register.html` / `forgot_password.html` / `reset_password.html` | extends `ui/auth_shell.html`，表单使用 ui.css class |
| `templates/account.html` | extends app_shell 或共享 layout，使用 ui.css 样式 |
| `templates/admin/{users,clients,audit_logs,login_history,user_form}.html` | 迁移到 app_shell + ui.css table/form 样式 |
| `static/style.css` | **删除**（6 行版本被取代）|
| 新增 `static/platform.css` | 平台专属补丁（若有）|

### 6.4 D. 测试

- 现有 HM 测试依赖 mock，预计不需大改，只要 `install_ui` 契约对。
- xinyi-platform 同理。
- 新增少量模板渲染单元测试：给定 `current_service` + `nav_menu`，渲染 `sidebar.html` / `product_switcher.html`，断言 active 标记与产品列表。
- 新增集成测试（轻量）：访问 `/dashboard`，HTML 包含顶栏、侧边栏、当前服务 active 标记。

## 7. 边界、已知限制与风险

### 7.1 跨服务 session 的语义（最容易踩坑）

HM 用自己的 session cookie（`hindsight_session`），装的是从 xinyi OAuth 流程拿到的 access_token + refresh_token。xinyi 自己有独立的 session cookie（用户在 `/login/form` 登录时种下）。

| 情形 | 行为 |
|---|---|
| 用户先在 xinyi 登录 → 跳 HM 走 OAuth → 再跳回 xinyi | session 通常有效（24h 内）→ 直接进 |
| 用户直接从 HM 登录（从未访问 xinyi 首页）→ 点 xinyi 入口 | xinyi 这边之前无 session cookie，HM cookie 在 xinyi 域不可读 → **会落到 xinyi 登录页** |
| 反过来从 xinyi 点 HM 入口 | HM 用 `return_to` 走 OAuth 流程，HM 已持有 xinyi access token → 直接进 |

**第 2 种是本期范围之外**的体验差距。属于跨子域 SSO 应该解决的问题。**本期不实现反向种 session 的方案**，在 xinyi 登录页加一句引导文案即可。后续单独立项。

### 7.2 ui_common 版本与发布

本期：

- **本地开发**：`pyproject.toml` 里 `xinyi-platform = { path = "../xinyi-platform", develop = true }`。
- **镜像**：docker 镜像 build 时通过 bind mount 或多 stage copy 把 xinyi-platform 仓库的 `ui_common` 目录复制进 hm 容器。
- **CI**：git submodule 或两个仓库一起 build，确保 `ui_common` 始终与 hm 的 build 同步。

未来 tag 化发布（v0.1 / v0.2 等）暂不做。

### 7.3 风险

- **CSS class 名冲突**：HM 业务模板里大量用了 `.btn-primary` / `.sidebar` / `.tenant-card` 等通用名。迁移到 ui.css 后要做一遍 go-through，确保业务页里用的 class 含义与 ui.css 一致，不一致的留在业务补丁 CSS 里。
- **nav_menu 的 active 计算**：旧模板用 `{% set nav_active = 'dashboard' %}` 手动设置。新方案由 ui_common 通过 `request.url.path` + nav_menu.href 自动判断，**消除这个手动 set 步骤**。
- **HM 现有 1020 行 CSS 不是全部直接可拷贝**：业务专属部分需剥离到 `hm.css`。这个剥离工作是 jack 项里的实打实工作量，要在实施时做完整 diff 比对。

### 7.4 开放问题

1. 品牌名最终定什么 → 用 `brand_name` config 暂占。
2. 未来业务多了 PRODUCTS 列表怎么做版本同步 → 暂时打包配置。
3. xinyi session cookie 是否升级为跨子域 → 后续单独立项（见 §7.1）。

## 8. 验证标准（成功条件）

实施完成时，需要同时满足：

1. **视觉**：HM 与 xinyi-platform 在浏览器里看起来是同一个产品；登录后页面都有顶栏 + 侧边栏。
2. **导航**：在 HM 顶部点"平台账户中心"能跳到 xinyi；在 xinyi 顶部点"Hindsight"能跳回 HM；active 状态正确显示。
3. **登录态**：从 xinyi 已登录状态点 HM 入口，HM 直接进 dashboard 不要求重新登录（保留现有 OAuth + access token 流程）。
4. **无回归**：HM 现有全部 pytest 通过；dashboard / api_keys / tenants / profile / admin 页面功能与样式正常。
5. **未来接入**：未来加新业务时，只需 (a) 在 `PRODUCTS` 加一项；(b) 在新服务 main.py 调一次 `install_ui`、提供 `nav_menu`、extends `ui/app_shell.html`。**不需要写任何 CSS**。
