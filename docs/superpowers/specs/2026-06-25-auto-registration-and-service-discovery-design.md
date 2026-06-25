# 自动注册与服务发现设计文档

**日期**: 2026-06-25
**状态**: 设计已确认
**涉及仓库**: xinyi-platform, hindsight-manager, docupipe-manager

## 背景与动机

当前 hindsight-manager (HM) 和 docupipe-manager (DM) 作为业务服务接入 xinyi-platform 时，存在三个手工痛点：

1. **注册是手动的**：管理员需要在平台 `/admin/clients` 页面或通过 SQL 脚本 (`005_register_hm_prod_client.sql`) 手动注册每个业务 client，手动生成和分发 client_secret。
2. **服务间 URL 硬编码**：`ui_common/registry.py` 中 `PRODUCTS` 列表硬编码了所有服务的 URL 模板。新增一个服务需要修改代码并重新部署所有已有服务。
3. **product switcher 不动态**：`install_ui()` 在启动时接收 `manager_url`、`docupipe_url` 参数，无法在运行时发现新注册的服务。

**目标**：让业务服务的注册和发现完全自动化——服务启动时自注册，product switcher 从数据库动态拉取，新增服务零代码改动。

## 非目标

- 不做服务健康检查 / 心跳探活（`last_seen_at` 仅记录，不参与活性判断）
- 不做服务网格 / mTLS（docker 内网信任）
- 不做自动密钥轮换（REGISTRATION_TOKEN 轮换是手动运维操作）
- 不做 product switcher 的权限过滤（所有已认证用户看到所有 active 服务）

## 关键决策

| # | 决策 | 选定 |
|---|---|---|
| 1 | 信任模型 | 独立 REGISTRATION_TOKEN（各自 env 配置同一个 token） |
| 2 | secret 派生方式 | `HMAC-SHA256(registration_token, client_id)`，两边各自计算，结果一致 |
| 3 | 注册时机 | 服务启动时（lifespan），幂等 upsert，每次刷新元数据 |
| 4 | 发现刷新策略 | 启动时拉取 + 后台 task 每 5 分钟刷新 |
| 5 | 数据归属 | `business_clients` 表同时管 OAuth2 凭证 + 导航元数据（不拆表） |
| 6 | 共享代码位置 | `xinyi_platform.ui_common.service_discovery`，HM 和 DM 都 import |
| 7 | install_ui 时序 | 模块级调用设空 products，lifespan 中异步填充 |

## §1 数据模型变更

`xinyi.business_clients` 表新增字段：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `base_url` | VARCHAR(512) NULL | NULL | 服务根 URL，如 `http://hm:8001/hindsight` |
| `home_path` | VARCHAR(255) NULL | NULL | 产品首页路径，如 `/dashboard` |
| `description` | VARCHAR(255) NULL | NULL | product switcher 副标题，如 "RAG 记忆库" |
| `logo_url` | VARCHAR(512) NULL | NULL | 图标 URL（v1 可留空） |
| `last_seen_at` | TIMESTAMPTZ NULL | NULL | 最后一次注册时间 |

现有字段不变：`client_id`、`name`、`client_secret_hash`、`redirect_uris`、`logout_url`、`status`。

`status = active` 且 `base_url IS NOT NULL` 的记录才会出现在发现端点的返回中。

### Alembic 迁移

新增 `xinyi_platform/migrations/versions/xxx_add_client_navigation_fields.py`：

```python
def upgrade():
    op.add_column("business_clients", sa.Column("base_url", sa.String(512), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("home_path", sa.String(255), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("description", sa.String(255), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("logo_url", sa.String(512), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True), schema="xinyi")

def downgrade():
    op.drop_column("business_clients", "last_seen_at", schema="xinyi")
    op.drop_column("business_clients", "logo_url", schema="xinyi")
    op.drop_column("business_clients", "description", schema="xinyi")
    op.drop_column("business_clients", "home_path", schema="xinyi")
    op.drop_column("business_clients", "base_url", schema="xinyi")
```

## §2 自动注册机制

### 配置（各自 env）

```
# xinyi-platform .env
XINYI_PLATFORM_REGISTRATION_TOKEN=<random 32+ char string>

# hindsight-manager .env
HINDSIGHT_MANAGER_REGISTRATION_TOKEN=<同一个 token>

# docupipe-manager .env
DOCUPIPE_MANAGER_REGISTRATION_TOKEN=<同一个 token>
```

三个服务各自独立配置，值必须相同。token 生成方式：`python -c "import secrets; print(secrets.token_urlsafe(32))"`。

### secret 派生公式

```python
import hmac, hashlib, base64

def derive_client_secret(registration_token: str, client_id: str) -> str:
    """从注册令牌和 client_id 确定性派生 client_secret。

    平台和业务服务各自用相同公式计算，结果一致。
    平台存 bcrypt(secret)，业务服务直接用 secret。
    """
    raw = hmac.new(
        registration_token.encode(),
        client_id.encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
```

特性：
- **确定性**：相同 token + client_id 永远产生相同 secret
- **幂等**：服务重启后派生出同样的 secret，无需持久化
- **隔离性**：不同 client_id 产生不同 secret（即使 token 相同）
- **不可逆**：HMAC 单向，token 泄露才能伪造，client_id 泄露不能反推

### 注册端点

```
POST /internal/clients/register
Header: X-Registration-Token: <token>
Body (JSON):
{
    "client_id": "hm-prod",
    "name": "Hindsight Manager",
    "redirect_uris": ["http://hm:8001/hindsight/auth/callback"],
    "logout_url": "http://hm:8001/hindsight/auth/logout",
    "base_url": "http://hm:8001/hindsight",
    "home_path": "/dashboard",
    "description": "RAG 记忆库"
}
```

平台处理逻辑：

1. 验 `X-Registration-Token` header == 自身 `settings.registration_token`
2. 派生 `secret = derive_client_secret(token, body.client_id)`
3. `bcrypt(secret)` → upsert 到 `business_clients`
   - `ON CONFLICT (client_id) DO UPDATE SET` 只更新元数据字段：name、redirect_uris、logout_url、base_url、home_path、description、last_seen_at
   - `client_secret_hash` 不在 SET 列表中（派生值不变，无需覆盖；首次 INSERT 时写入）
4. 返回 `200 {"status": "registered", "client_id": "hm-prod"}`
   - 不返回 secret（两边各自派生）

### 各服务启动时的注册流程

```python
# HM / DM lifespan
async def lifespan(app):
    # ... engine setup ...

    # 1. 如果配置了 registration_token，派生 secret 覆盖空默认值
    if settings.registration_token:
        settings.oauth_client_secret = derive_client_secret(
            settings.registration_token,
            settings.oauth_client_id,
        )

    # 2. 上报元数据到平台(共享代码)
    await register_self(settings)

    # 3. 拉取服务发现列表(共享代码)
    app.state.ui["products"] = await fetch_active_clients(
        settings.platform_url,
        settings.oauth_client_id,
        settings.oauth_client_secret,
    )

    # 4. 后台定时刷新
    scheduler.add_job(_refresh_products, "interval", minutes=5)
```

## §3 服务发现端点

```
GET /internal/clients/active
Header: X-Client-Id + X-Client-Secret (常规 client 鉴权)
```

返回所有 `status = active` 且 `base_url IS NOT NULL` 的业务 client：

```json
{
    "clients": [
        {
            "client_id": "hm-prod",
            "name": "Hindsight Manager",
            "base_url": "http://hm:8001/hindsight",
            "home_path": "/dashboard",
            "description": "RAG 记忆库",
            "kind": "business"
        },
        {
            "client_id": "docupipe-prod",
            "name": "DocuPipe",
            "base_url": "http://dm:8002/docupipe",
            "home_path": "/projects",
            "description": "文档管道调度",
            "kind": "business"
        }
    ]
}
```

`kind = business` 标识业务服务。平台自身（账户中心、管理后台）由各服务在 product 列表里本地追加一条，不查 DB。

## §4 共享注册 + 发现模块

位置：`xinyi_platform/ui_common/service_discovery.py`

HM 和 DM 都依赖 `xinyi_platform`，通过 `ui_common` 共享代码，避免两份实现。

### 模块接口

```python
# xinyi_platform/ui_common/service_discovery.py

def derive_client_secret(registration_token: str, client_id: str) -> str:
    """HMAC-SHA256 派生 client_secret。"""

async def register_self(
    platform_url: str,
    registration_token: str,
    client_metadata: dict,
) -> bool:
    """POST /internal/clients/register 上报元数据。
    失败时 log warning 并返回 False，不阻塞启动。
    """

async def fetch_active_clients(
    platform_url: str,
    client_id: str,
    client_secret: str,
) -> list[dict]:
    """GET /internal/clients/active 拉取服务列表。
    失败时返回空列表，不阻塞启动。
    """

def build_product_list(
    active_clients: list[dict],
    *,
    platform_url: str,
    self_client_id: str,
    self_name: str,
    self_home_path: str,
) -> list[dict]:
    """组装最终 product switcher 列表。
    在 active_clients 基础上追加平台自身 + 标记当前服务。
    """
```

### install_ui 签名变化

```python
# 之前
install_ui(
    app,
    current_service="hindsight-manager",
    nav_menu=...,
    brand="Hindsight",
    platform_url=...,
    manager_url=...,     # ← 删除
    docupipe_url=...,    # ← 删除
    service_prefix="/hindsight",
)

# 之后
install_ui(
    app,
    current_service="hindsight-manager",
    nav_menu=...,
    brand="Hindsight",
    platform_url=...,
    service_prefix="/hindsight",
)
# app.state.ui["products"] 初始为空列表，lifespan 中填充
```

### 时序

```
模块加载阶段:
  install_ui()
    → 设置模板 / static mount / nav_menu / brand
    → app.state.ui["products"] = []  (初始空)

lifespan 阶段 (app 启动后):
  1. 派生 secret (如果配了 registration_token)
  2. register_self()  → 上报元数据到平台
  3. fetch_active_clients() → 拉取所有 active 服务
  4. build_product_list() → 组装含平台 + 自身的完整列表
  5. 写入 app.state.ui["products"]
  6. 后台 task 每 5 分钟重复步骤 3-5

模板渲染阶段 (每个请求):
  从 request.app.state.ui["products"] 读取
  → 总是拿到最新缓存值
```

### 删除 registry.py

`xinyi_platform/ui_common/registry.py` 中的 `PRODUCTS` 硬编码列表完全删除。`_resolve_products()` 函数删除。product 列表改由 `build_product_list()` 在运行时动态生成。

## §5 跨服务跳转 SSO

用户在 product switcher 点击另一个服务时，SSO 内建于现有 OAuth2 流程，无需额外设计：

```
用户在 HM 已登录 (hindsight_session cookie 有效)
  → product switcher 点 DocuPipe
  → 浏览器跳 http://dm:8002/docupipe/projects
  → DM 发现无 docupipe_session cookie
  → 302 到 /docupipe/auth/login-redirect
  → 302 到 {platform}/oauth/authorize?client_id=docupipe-prod
  → 用户在平台已有 xinyi_session → 静默签发 code（无需再输密码）
  → 302 回 DM /docupipe/auth/callback
  → 设 docupipe_session cookie
  → 落在 /docupipe/projects，全程无感
```

平台是 SSO 中枢：用户在任一服务登录后，`xinyi_session` 存活期间跳转其他已注册服务均为静默授权。product switcher 的 URL 就是各服务注册时的 `base_url + home_path`。

## §6 HM 和 DM 改造（完全对称）

两个服务做完全一样的事：

### config.py 新增

```python
# hindsight-manager
registration_token: str = ""

# docupipe-manager
registration_token: str = ""
```

### main.py lifespan 改造

```python
async def lifespan(app):
    # ... engine setup ...

    # 派生 secret
    if settings.registration_token:
        settings.oauth_client_secret = derive_client_secret(
            settings.registration_token,
            settings.oauth_client_id,
        )

    # 注册 + 发现（ui_common 共享代码）
    if settings.registration_token:
        await register_self(
            platform_url=settings.platform_url,
            registration_token=settings.registration_token,
            client_metadata={
                "client_id": settings.oauth_client_id,
                "name": "Hindsight Manager",
                "redirect_uris": [settings.oauth_redirect_uri],
                "logout_url": f"{settings.base_url}/auth/logout",
                "base_url": settings.base_url,
                "home_path": "/dashboard",
                "description": "RAG 记忆库",
            },
        )

    active = await fetch_active_clients(
        settings.platform_url,
        settings.oauth_client_id,
        settings.oauth_client_secret,
    )
    app.state.ui["products"] = build_product_list(
        active,
        platform_url=settings.platform_url,
        self_client_id=settings.oauth_client_id,
        self_name="Hindsight Manager",
        self_home_path="/dashboard",
    )

    # 后台刷新
    scheduler.add_job(_refresh_products, "interval", minutes=5)
```

### 删除的硬编码

- `registry.py` 的 `PRODUCTS` 列表 → 删除整个文件
- `install_ui()` 的 `manager_url` / `docupipe_url` 参数 → 删除
- `_resolve_products()` 函数 → 删除

### build_product_list 的行为

```python
def build_product_list(active_clients, *, platform_url, self_client_id, self_name, self_home_path):
    products = []

    # 1. 平台自身（始终第一条）
    products.append({
        "id": "platform",
        "label": "平台账户中心",
        "subtitle": "用户 · 审计 · 登录历史",
        "url": f"{platform_url}/account",
        "kind": "platform",
        "is_current": False,
    })

    # 2. 各业务服务（从 DB 拉取）
    for c in active_clients:
        products.append({
            "id": c["client_id"],
            "label": c["name"],
            "subtitle": c.get("description", ""),
            "url": f"{c['base_url']}{c.get('home_path', '')}",
            "kind": "business",
            "is_current": c["client_id"] == self_client_id,
        })

    return products
```

## §7 环境变量变更总结

### xinyi-platform 新增

```
XINYI_PLATFORM_REGISTRATION_TOKEN=<random 32+ char string>
```

### HM 新增

```
HINDSIGHT_MANAGER_REGISTRATION_TOKEN=<同一个 token>
```

### DM 新增

```
DOCUPIPE_MANAGER_REGISTRATION_TOKEN=<同一个 token>
```

### HM / DM 保留不变

```
*_OAUTH_CLIENT_ID=hm-prod          # 或 docupipe-prod
*_OAUTH_CLIENT_SECRET=             # 留空，启动时由 derive_client_secret 填充
*_PLATFORM_URL=http://xinyi-platform:8000/xinyi
*_JWT_SECRET=<与平台共享>
*_ENCRYPTION_KEY=<与平台共享>
```

## §8 优雅降级

| 场景 | 行为 |
|---|---|
| 平台尚未启动，业务服务先起 | `register_self()` 失败 → log warning → secret 仍可派生（纯本地计算） → OAuth2 调用平台时会失败，但 access JWT 本地验签不受影响 → product switcher 为空 → 后台 task 重试填充 |
| 运行中平台短暂挂掉 | product switcher 保留上次缓存 → 业务请求不受影响（access JWT 本地验签 15min TTL）→ 审计进 outbox 表 → 平台恢复后后台 task 刷新 product 列表 |
| 新服务注册后 | 最多 5 分钟出现在所有已运行服务的 product switcher 中（下次后台刷新周期） |
| REGISTRATION_TOKEN 未配置 | secret 从 `OAUTH_CLIENT_SECRET` env 读取（现有行为），product switcher 为空。`registry.py` 已删除，无硬编码 fallback。 |
| REGISTRATION_TOKEN 轮换 | 三个服务同时更新 env 并重启 → 派生出新的 secret → 平台 upsert 新的 bcrypt hash → 旧 refresh token 仍有效到自然过期 |

## §9 改动范围汇总

### xinyi-platform

| 文件 | 改动 |
|---|---|
| `models/business_client.py` | 加 5 个字段 |
| `migrations/versions/xxx_add_client_navigation_fields.py` | 新增迁移 |
| `api/admin_clients.py` | 注册/编辑页面加 base_url、home_path、description 字段 |
| `api/internal_clients.py`（或新建） | 加 `POST /internal/clients/register` + `GET /internal/clients/active` |
| `auth/internal_auth.py` | 加 registration token 验证（用于 register 端点） |
| `services/business_client_service.py` | 加 `register_or_update()` 方法 |
| `config.py` | 加 `registration_token` 字段 |
| `ui_common/service_discovery.py` | 新建：`derive_client_secret`、`register_self`、`fetch_active_clients`、`build_product_list` |
| `ui_common/install.py` | `install_ui()` 删除 `manager_url`/`docupipe_url` 参数，products 初始为空 |
| `ui_common/registry.py` | 删除整个文件 |

### hindsight-manager

| 文件 | 改动 |
|---|---|
| `config.py` | 加 `registration_token` 字段 |
| `main.py` | lifespan 加派生 secret + 注册 + 发现 + 后台刷新 |
| `api/pages.py` | 无改动（已从 `app.state.ui` 读 products） |

### docupipe-manager

| 文件 | 改动 |
|---|---|
| `config.py` | 加 `registration_token` 字段 |
| `main.py` | lifespan 加派生 secret + 注册 + 发现 + 后台刷新 |
| `api/pages.py` | 无改动（已从 `app.state.ui` 读 products） |

## §10 安全考量

- **REGISTRATION_TOKEN 等同于 client_secret 的种子**：泄露后攻击者可派生任意 client 的 secret。但它不直接是任何 client 的 secret，且仅用于注册端点（内网可达），影响面可控。
- **注册端点仅内网可达**：`/internal/clients/register` 只接受 docker 内网 IP（已有 Network ACL 约束，与 `/internal/*` 其他端点一致）。
- **client_secret_hash 不被注册覆盖**：upsert 时 `ON CONFLICT DO UPDATE` 只更新元数据字段，不覆盖 `client_secret_hash`（派生值不变，但防止意外）。
- **派生 secret 足够长**：HMAC-SHA256 输出 32 字节，base64 编码后 43 字符，满足 OAuth2 client_secret 强度要求。

## §11 测试策略

### xinyi-platform 测试

| 测试 | 覆盖点 |
|---|---|
| `test_derive_client_secret_deterministic` | 相同输入两次调用结果一致 |
| `test_derive_client_secret_different_client_ids` | 不同 client_id 产生不同 secret |
| `test_register_endpoint_valid_token` | 正确 token → 200 + upsert |
| `test_register_endpoint_invalid_token` | 错误 token → 401 |
| `test_register_endpoint_upsert` | 二次调用更新元数据，不报错 |
| `test_register_endpoint_bcrypt_matches_derived` | 存入的 hash 能验证派生的 secret |
| `test_active_clients_excludes_disabled` | status=disabled 不返回 |
| `test_active_clients_excludes_no_base_url` | base_url=NULL 不返回 |
| `test_active_clients_requires_client_auth` | 无 X-Client-Id/Secret → 401 |

### service_discovery 共享模块测试

| 测试 | 覆盖点 |
|---|---|
| `test_register_self_success` | mock 平台返回 200 |
| `test_register_self_platform_down` | mock 连接失败 → 返回 False，不抛异常 |
| `test_fetch_active_clients_success` | mock 返回服务列表 |
| `test_fetch_active_clients_platform_down` | mock 连接失败 → 返回空列表 |
| `test_build_product_list_includes_platform` | 列表首条是平台 |
| `test_build_product_list_marks_current` | is_current 标记正确 |

### HM / DM 集成测试

| 测试 | 覆盖点 |
|---|---|
| `test_lifespan_derives_secret` | 配了 registration_token → oauth_client_secret 被覆盖 |
| `test_lifespan_no_token_keeps_env_secret` | 没配 token → 用 env 里的 secret |
| `test_products_populated_after_lifespan` | lifespan 完成后 app.state.ui["products"] 非空 |
