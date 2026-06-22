# 平台抽取设计文档

**日期**: 2026-06-22
**状态**: 设计已确认,待用户审阅
**项目位置**: `~/src/lab/xinyi-platform/`(新建)

## 目标

把 hindsight-manager 中的**基础设施部分**(用户管理、认证登录、审计日志、邮件)抽取为独立的 `xinyi-platform`,使基础设施能在**运行态**被多个业务服务复用。

第一个业务是改造后的 hindsight-manager(纯业务);后续 docupipe-manager 等业务以 client 身份接入平台,不再各自实现认证。

## 非目标(v1)

- 不做独立 Postgres 实例(schema 隔离够了)
- 不做服务网格 / mTLS(docker 内网信任)
- 不做平台多副本(v1 单实例 + 业务侧短 TTL 抗抖动)
- 不做事件总线 / 用户变更推送(LRU + 显式批量拉够用)
- 不做平台 SDK 自动生成(业务端手写 client)
- 不做统一前端壳(每个业务保留自己的 base.html)
- 不做 OpenID Connect 完整实现(只取 OAuth2 + 自定义 `/me`)
- 不做 PKCE / scopes 精细化(v1 内网 client 可信,全 client 等权)
- 不做蓝绿部署 / canary / zero-downtime 迁移(短停服窗口可接受)
- 不做独立 docupipe-manager(等平台稳定后再启动,按新平台契约重写其 spec)

## 关键决策

| # | 决策 | 选定 |
|---|---|---|
| 1 | 整体形态 | 独立 `xinyi-platform` 进程,hindsight-manager 改造为纯业务,通过 HTTP 调平台 |
| 2 | 数据归属 | 平台、业务各自独占 schema(`xinyi`、`manager`),共享同一 Postgres 实例 |
| 3 | Tenant 概念 | 业务专属(留在 manager schema),不下沉为平台概念 |
| 4 | 共享范围 | 服务器端的用户管理 / 认证 / 审计 / 邮件归平台;数据平面 / tenant / api_key 留业务 |
| 5 | 平台 API 边界 | 宽档:登录 / OAuth2 / 用户 CRUD / 角色 / 审计 / 邮件 |
| 6 | 认证模式 | JWT 自包含 + 短 TTL(15min access)+ 显式刷新(7d refresh);业务本地验签零网络 |
| 7 | 跨服务登录 | OAuth2 授权码式(标准、解耦、可扩展) |
| 8 | 业务访问用户数据 | 进程内 LRU 缓存(5min TTL)+ 平台 `POST /internal/users/batch-get` 兜底 |
| 9 | 审计 / 邮件推送 | `asyncio.create_task` fire-and-forget + 本地 `audit_outbox` 表,平台抖动不阻塞业务 |
| 10 | UI 拆分 | 严格按归属:登录 / 用户管理 / 审计查看 → 平台;tenant / api_key / 数据平面 → 业务 |
| 11 | 平台部署 | 独立 docker-compose service(端口 8000),加入现有 `hindsight_default` 网络 |
| 12 | 业务接入契约 | 平台维护 `business_clients` 表:client_id + client_secret(SM4 加密)+ redirect_uris + status |
| 13 | 数据迁移策略 | 停服一次性迁移(规模小、可控),不做双写期 |
| 14 | `crypto.py` 复用 | 两边都用 SM4,**复制**到 xinyi-platform,不发布共享包(v1) |
| 15 | 现有 docupipe-manager spec | 暂缓,待平台稳定后按新契约重写 §1.3 和 §8 |

## §1 架构

### 1.1 部署拓扑

现有 4 个 docker-compose 服务演进为 5 个:

```
┌─────────────────────────────────────────────────────────────┐
│ docker-compose (hindsight_default 网络)                     │
│                                                              │
│   ┌────────────┐    ┌────────────────┐    ┌──────────────┐ │
│   │ postgres   │◄───┤ xinyi-platform │    │ hindsight-api│ │
│   │            │    │   :8000 (新)   │    │  :8888       │ │
│   │            │    └────────┬───────┘    │ (数据平面)   │ │
│   │            │             │            └──────┬───────┘ │
│   │            │             └────────┬───────────┘         │
│   │            │                      │                     │
│   │            │             ┌────────┴───────┐             │
│   │            │             │ manager :8001  │             │
│   │            │             │ (纯业务)       │             │
│   │            │             └────────────────┘             │
│   │            │                                            │
│   │            │             ┌────────────────┐             │
│   │            │             │ control-plane  │             │
│   │            │             │  :9999         │             │
│   │            │             └────────────────┘             │
│   └────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

`xinyi-platform` 加入现有 `hindsight_default` 网络,不另起网络。

### 1.2 Schema 布局(同一 Postgres 实例)

| Schema | 归属 | 关键表 |
|---|---|---|
| `xinyi` (新) | 平台独占 | `users`, `business_clients`, `oauth_codes`, `refresh_tokens`, `token_revocations`, `audit_logs`, `login_history`, `email_verifications` |
| `manager` (瘦身) | 业务独占 | `tenants`, `tenant_members`, `api_keys`, `audit_outbox` |
| `tenant_<slug>` | hindsight-api | tenant 数据(不变) |

### 1.3 组件迁移清单

**从 hindsight-manager 迁移到 xinyi-platform**:

```
auth/
  local.py          ✗ → xinyi-platform
  cas.py            ✗ → xinyi-platform
  captcha.py        ✗ → xinyi-platform
  password.py       ✗ → xinyi-platform
  session.py        ✗ → xinyi-platform (签发/刷新/撤销)
  audit.py          ✗ → xinyi-platform (审计写入逻辑)
  dependencies.py   保留,改实现(本地验签 + 调平台)

models/
  user.py               ✗ → xinyi-platform
  audit_log.py          ✗ → xinyi-platform
  login_history.py      ✗ → xinyi-platform
  email_verification.py ✗ → xinyi-platform
  tenant.py             保留(业务)
  tenant_member.py      保留(业务,改 FK → 逻辑引用)
  api_key.py            保留(业务)

services/
  email.py          ✗ → xinyi-platform
  (其他业务 service)保留

api/
  auth.py           ✗ → xinyi-platform (/login、/logout、/cas/*)
  password.py       ✗ → xinyi-platform
  captcha.py        ✗ → xinyi-platform
  admin.py          拆分:用户管理 → xinyi-platform,任务监控 → 保留
  pages.py          拆分:登录/注册页 → xinyi-platform,dashboard → 保留
  tenants/members/api_keys/proxy/task_monitor  全保留

crypto.py           复制一份到 xinyi-platform(两边都用 SM4)
db.py / config.py   各自独立一份
extensions/         全保留(业务专属,跑在 hindsight-api 进程)
templates/          按页面拆分:登录/用户管理 → xinyi-platform,业务页面 → 保留
```

### 1.4 跨服务调用图

**登录流程**(用户首次访问 hindsight-manager):

```
Browser → GET hm:8001/admin/tenants (无 cookie)
hm 返回 302 → xinyi-platform:8000/login?return_to=https://hm/admin/tenants
Browser → xinyi-platform:8000/login
用户输入凭证 → 平台验证 → 平台设 xinyi_session cookie
平台返回 302 → hm:8001/auth/callback?code=<一次性 code>
Browser → hm:8001/auth/callback?code=xxx
hm 后端 POST xinyi-platform:8000/oauth/token {code, client_secret}
  → 平台返回 {access_jwt: 15min, refresh_jwt: 7d}
hm 设 hm_session cookie (含 access_jwt),重定向到 /admin/tenants
```

**业务请求流程**(已登录用户访问 `/admin/tenants`):

```
Browser → hm:8001/admin/tenants (Cookie: hm_session)
hm auth dependencies:
  1. 本地验签 access_jwt (共享 jwt_secret,零网络)
  2. 若 access 过期 → POST xinyi-platform:8000/oauth/token (grant_type=refresh_token)
  3. 若 user_id 在撤销列表 → 401
hm 业务逻辑:
  - select tenants from manager.tenants
  - select tenant_members → 收集 user_ids
  - POST xinyi-platform:8000/internal/users/batch-get {ids: [...]}
  - 平台返回 {id: {username, email, role}}
  - LRU 缓存 5min
  - 渲染页面
hm fire-and-forget:
  - asyncio.create_task(POST xinyi-platform:8000/internal/audit {event})
```

**数据平面代理(已有,不变)**:`hm → hindsight-api:8888`,通过 `extensions/manager_tenant.py` 验证 API key,跟平台无关。

### 1.5 配置项变化

**xinyi-platform 新增**:

```
XINYI_PLATFORM_DATABASE_URL
XINYI_PLATFORM_JWT_SECRET                # 跟 HM 共享
XINYI_PLATFORM_ADMIN_PASSWORD            # 自启动建 admin
XINYI_PLATFORM_AUTH_PROVIDER             # local | cas
XINYI_PLATFORM_CAS_*                     # CAS 配置(若启用)
XINYI_PLATFORM_SMTP_*                    # 邮件配置
XINYI_PLATFORM_SESSION_EXPIRE_HOURS=24
XINYI_PLATFORM_ACCESS_TOKEN_TTL_SECONDS=900
XINYI_PLATFORM_REFRESH_TOKEN_TTL_DAYS=7
XINYI_PLATFORM_HOST=0.0.0.0
XINYI_PLATFORM_PORT=8000
XINYI_PLATFORM_BASE_URL=http://localhost:8000
XINYI_PLATFORM_ENCRYPTION_KEY            # SM4(跟 HM 共享,用于 client_secret 加密)
```

**hindsight-manager 调整**:

```
# 移除
HINDSIGHT_MANAGER_AUTH_PROVIDER        # 平台接管
HINDSIGHT_MANAGER_ADMIN_PASSWORD       # 平台接管
HINDSIGHT_MANAGER_SMTP_*               # 平台接管
HINDSIGHT_MANAGER_CAS_*                # 平台接管

# 新增
HINDSIGHT_MANAGER_PLATFORM_URL=http://xinyi-platform:8000
HINDSIGHT_MANAGER_OAUTH_CLIENT_ID=hm-prod
HINDSIGHT_MANAGER_OAUTH_CLIENT_SECRET=<SM4 加密的 secret>
HINDSIGHT_MANAGER_OAUTH_REDIRECT_URI=http://hm:8001/auth/callback

# 保留(共享)
HINDSIGHT_MANAGER_JWT_SECRET           # 本地验签用
HINDSIGHT_MANAGER_DATABASE_URL         # 仍连同一 Postgres,只用 manager schema
HINDSIGHT_MANAGER_ENCRYPTION_KEY       # SM4 仍要用
```

### 1.6 共享 vs 独立 清单

| 资源 | 共享/独立 | 说明 |
|---|---|---|
| Postgres 实例 | 共享 | 不同 schema 隔离 |
| `jwt_secret` | 共享 | 业务本地验签 |
| `encryption_key` (SM4) | 共享 | 业务要解 api_key,平台要解 oauth_client_secret |
| Cookie | 独立 | `xinyi_session` vs `hm_session` |
| 用户表 | 独立 | 只在 xinyi schema |
| 业务表 | 独立 | 只在 manager schema |
| 邮件发送代码 | 独立 | 平台独占 |
| `crypto.py` 实现 | **复制** | 两边都用 SM4,不发布共享包(v1) |

### 1.7 v1 不做

见"非目标"列表。

## §2 数据模型

### 2.1 总览

| Schema | 表数 | 变化 |
|---|---|---|
| `xinyi` (新) | 8 | 4 张从 `manager` 迁入 + 4 张平台新增 |
| `manager` (瘦身) | 4 | 从 8 张减到 4 张(3 张原有业务 + 1 张新增 audit_outbox) |

### 2.2 Platform schema 表

#### 表 1: `xinyi.users`(从 `manager.users` 迁入)

字段全部保留,修正一个 legacy bug(`created_at` 类型不一致):

| 字段 | 类型 | 备注 |
|---|---|---|
| `id` | UUID PK | |
| `username` | VARCHAR(255) UNIQUE | |
| `email` | VARCHAR(255) NULL | |
| `password_hash` | VARCHAR(255) NULL | CAS 用户为 NULL |
| `display_name` | VARCHAR(255) | |
| `auth_provider` | ENUM `auth_provider` | `local` / `cas` |
| `role` | ENUM `user_role` | `admin` / `user` |
| `is_active` | BOOLEAN | |
| `last_login_at` | TIMESTAMPTZ NULL | |
| `created_at` | **TIMESTAMPTZ** | 修正:原 `String` 改为 DateTime |
| `updated_at` | TIMESTAMPTZ | |

ENUM 重命名(schema 限定):
- `xinyi.auth_provider`、`xinyi.user_role`(原来在 `manager.`)

#### 表 2: `xinyi.business_clients`(新增)

注册到平台的业务服务。

| 字段 | 类型 | 备注 |
|---|---|---|
| `id` | UUID PK | |
| `client_id` | VARCHAR(64) UNIQUE | 业务标识,如 `hm-prod`、`docupipe-prod` |
| `name` | VARCHAR(255) | 显示名,如 "Hindsight Manager" |
| `client_secret_hash` | VARCHAR(255) | bcrypt(secret 明文不存) |
| `redirect_uris` | JSON | 允许的回调 URL 列表 |
| `status` | ENUM `client_status` | `active` / `disabled` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

索引:`client_id` 唯一。

#### 表 3: `xinyi.oauth_codes`(新增)

OAuth2 授权码,一次性、短 TTL(60s)。

| 字段 | 类型 | 备注 |
|---|---|---|
| `code` | VARCHAR(64) PK | 随机串 |
| `client_id` | VARCHAR(64) | 逻辑引用 `business_clients.client_id` |
| `user_id` | UUID | 逻辑引用 `users.id` |
| `redirect_uri` | VARCHAR(512) | 回调地址(必须 ∈ client.redirect_uris) |
| `scope` | VARCHAR(255) NULL | v1 固定 `openid profile email` |
| `expires_at` | TIMESTAMPTZ | 60s |
| `used_at` | TIMESTAMPTZ NULL | 兑换后写入,防止重放 |
| `created_at` | TIMESTAMPTZ | |

索引:`expires_at` 用于清理。

#### 表 4: `xinyi.refresh_tokens`(新增)

刷新令牌,可逐个撤销。

| 字段 | 类型 | 备注 |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID | FK `users.id` |
| `client_id` | VARCHAR(64) | 哪个业务签发 |
| `token_hash` | VARCHAR(64) UNIQUE | sha256(token),明文不存 |
| `expires_at` | TIMESTAMPTZ | 默认 +7d |
| `revoked_at` | TIMESTAMPTZ NULL | 撤销时写入 |
| `last_used_at` | TIMESTAMPTZ NULL | |
| `created_at` | TIMESTAMPTZ | |

索引:`token_hash` 唯一;`(user_id, client_id)` 列表查询。

#### 表 5: `xinyi.token_revocations`(新增)

access JWT 的撤销列表。短 TTL(15min)天然兜底,这里只记"必须立即失效"的。

| 字段 | 类型 | 备注 |
|---|---|---|
| `jti` | VARCHAR(64) PK | JWT ID |
| `user_id` | UUID | 冗余,便于"该用户所有 token 失效" |
| `reason` | VARCHAR(100) | `password_change` / `admin_revoke` / `logout` |
| `expires_at` | TIMESTAMPTZ | 跟 JWT 一致,过期可清理 |
| `created_at` | TIMESTAMPTZ | |

索引:`user_id` 用于"封禁用户"场景批量检查;`expires_at` 用于清理。

注:access JWT 自身不做数据库校验(性能),只在 `/auth/refresh` 时检查 `user_id` 是否在表里。

**清理机制**:平台启动时 + 每小时后台 task:`DELETE FROM token_revocations WHERE expires_at < now()`。`oauth_codes` 同款清理逻辑。

#### 表 6: `xinyi.audit_logs`(从 `manager.audit_logs` 迁入 + 字段扩展)

业务通过 HTTP 推送,平台落库。原表基础上增加 `client_id`。

| 字段 | 类型 | 备注 |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID NULL | FK `users.id` SET NULL |
| `client_id` | VARCHAR(64) NULL | 哪个业务产生的(null = 平台自身事件) |
| `action` | VARCHAR(100) | 见下方命名规范 |
| `resource_type` | VARCHAR(50) | |
| `resource_id` | VARCHAR(255) | |
| `detail` | JSON NULL | |
| `ip_address` | VARCHAR(45) NULL | |
| `created_at` | TIMESTAMPTZ | |

索引:`(client_id, created_at DESC)`、`(user_id, created_at DESC)`。

**action 命名规范**:
- 平台自身事件:`<domain>.<verb>`,如 `user.login`、`user.create`、`client.disable`
- 业务推送事件:`<business_prefix>.<domain>.<verb>`,如 `hm.tenant.create`、`hm.api_key.rotate`、`docupipe.project.trigger`
- 业务前缀(`hm`、`docupipe`)在平台注册 client 时约定,避免冲突

#### 表 7: `xinyi.login_history`(从 `manager.login_history` 迁入)

字段不变。索引:`user_id` + `login_time DESC`。

#### 表 8: `xinyi.email_verifications`(从 `manager.email_verifications` 迁入)

字段不变。

### 2.3 Manager schema 剩余表

#### 表 1: `manager.tenants`(保留,字段不变)

#### 表 3: `manager.tenant_members`(改 FK → 逻辑引用)

```diff
- user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
+ user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
```

`user_id` 改为**逻辑引用**(不做 FK constraint),指向 `xinyi.users.id`。原因:跨 schema + 跨服务所有权,FK 难以维护。

#### 表 4: `manager.audit_outbox`(新增)

业务侧的审计推送重试队列。平台抖动时,审计事件落此表,后台 task 重试。

| 字段 | 类型 | 备注 |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID NULL | |
| `action` | VARCHAR(100) | |
| `resource_type` | VARCHAR(50) | |
| `resource_id` | VARCHAR(255) | |
| `detail` | JSON NULL | |
| `ip_address` | VARCHAR(45) NULL | |
| `occurred_at` | TIMESTAMPTZ | 业务侧事件实际发生时间 |
| `idempotency_key` | VARCHAR(64) NULL UNIQUE | UUID,平台去重用 |
| `status` | ENUM `outbox_status` | `pending` / `delivered` / `failed` |
| `attempts` | INTEGER DEFAULT 0 | |
| `last_error` | TEXT NULL | 最后一次失败原因 |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

索引:`(status, occurred_at)` 用于后台扫描 pending;`idempotency_key` 唯一。

```sql
CREATE TYPE manager.outbox_status AS ENUM ('pending', 'delivered', 'failed');
```

后台 task 每 10s 扫描 `status=pending AND attempts < 5` 的记录,调平台 `POST /internal/audit`,成功标 `delivered`,失败 `attempts++` 并填 `last_error`。`attempts >= 5` 标 `failed`(人工介入)。

#### 表 5: `manager.api_keys`(保留,字段不变)

`tenant_id` 仍是 FK 到 `manager.tenants`(同 schema 内,无变化)。

### 2.4 ENUM 汇总

```sql
-- xinyi schema
CREATE TYPE xinyi.auth_provider   AS ENUM ('local', 'cas');
CREATE TYPE xinyi.user_role       AS ENUM ('admin', 'user');
CREATE TYPE xinyi.client_status   AS ENUM ('active', 'disabled');

-- manager schema(原有,不变)
CREATE TYPE manager.tenant_status    AS ENUM ('active', 'deleting', 'deleted');
CREATE TYPE manager.member_role      AS ENUM ('owner', 'member');
```

### 2.5 Alembic 迁移策略

**平台 service 的 Alembic**:
- `script_location = xinyi_platform/migrations`
- `version_table_schema = xinyi`(版本表隔离)
- 初始迁移:创建 schema + 8 张表 + 3 个 ENUM
- 数据迁移脚本(一次性):从 `manager.users/audit_logs/login_history/email_verifications` 复制到 `xinyi.*`,完成之后**不立即删除** `manager` 侧旧表(过渡期保留,等业务切换完成再清理)

**hindsight-manager 的 Alembic**:
- 新增迁移(Phase 3 时):创建 `manager.audit_outbox` 表 + `outbox_status` ENUM
- 新增迁移(Phase 5 时):删除 `manager.users/audit_logs/login_history/email_verifications` 表 + 对应 ENUM
- 新增迁移(Phase 5 时):`tenant_members.user_id` 的 FK constraint drop
- 业务表 schema 版本号递增

### 2.6 数据迁移路径

迁移分三步,每步可独立回滚:

1. **平台初版部署 + 数据双写期**:平台 service 部署,数据从 `manager` 复制一份到 `xinyi` schema。此时 `hindsight-manager` 仍读写 `manager.users`(过渡期)。两边数据可能出现 drift,通过一次性脚本对齐。
2. **业务切换**:hindsight-manager 改为读写 `xinyi`(通过 HTTP),`manager.users` 冻结写入。
3. **清理**:确认稳定后,hindsight-manager 的迁移删除 `manager.users` 等旧表。

**v1 建议直接跳过双写期**(规模小、可控):停服几分钟,跑迁移脚本,起平台 + 改造后的 hindsight-manager。

### 2.7 不做

- 不做表分区(audit_logs 量大时再考虑)
- 不做跨 schema FK
- 不做软删除(`is_active` + `status` 已经够)
- 不做用户头像 / OAuth 第三方登录(v1)

## §3 API 契约

### 3.1 鉴权方式(两类)

| 类型 | 用途 | 凭证 |
|---|---|---|
| **用户 session** | 浏览器访问平台/业务 UI | Cookie `xinyi_session`(平台签发) |
| **业务 client** | 业务服务调平台内网端点 | Header `X-Client-Id` + `X-Client-Secret` |

业务→平台内网调用走第二种;浏览器直接访问平台 UI 走第一种。

### 3.2 用户面 API(浏览器入口,平台独占)

| Method | Path | 说明 |
|---|---|---|
| GET | `/login` | 登录页,支持 `?return_to=` query |
| POST | `/login/form` | 表单提交,设 xinyi_session,跳 return_to |
| POST | `/login` | JSON API 登录(供 SPA 调用) |
| GET | `/cas/login` | CAS 跳转 |
| GET | `/cas/callback` | CAS 回调,设 cookie |
| GET | `/register` | 注册页(若开启) |
| POST | `/register` | 提交注册 |
| GET | `/password/forgot` | 找回密码页 |
| POST | `/password/forgot` | 发送重置邮件 |
| GET | `/password/reset` | 重置密码页(`?token=`) |
| POST | `/password/reset` | 提交新密码 |
| POST | `/logout` | 清 xinyi_session + revoke 所有相关 refresh_token(全局登出,所有业务下次访问都会跳登录) |
| GET | `/me` | 当前用户信息(JSON) |
| GET | `/account` | 用户中心页(改密码、看登录历史) |

return_to 处理:登录成功后 302 到 return_to(必须 host 在白名单)。若 return_to 指向业务域名,平台再走一次 OAuth2 流程(业务用静默授权)。

**登出语义**:三层 cookie 的失效关系——
- 业务登出(用户在 hm 点登出):hm 清 `hm_session` + 调平台 `/oauth/revoke` 撤销该 client 的 refresh_token;**但 `xinyi_session` 仍存活**,用户下次访问 hm 会通过 SSO 静默签发新 code。这是"单业务登出"。
- 平台登出(用户在平台点登出):清 `xinyi_session` + revoke 所有 client 的 refresh_token;**所有业务最终登出**。这是"全局登出"。
- v1 只在平台 UI 提供全局登出;业务 UI 的登出按钮可选实现"跳转到平台 `/logout`"做全局登出。

**全局登出的滞后说明(v1)**:由于 access JWT 本地验签(不查 DB),revoke refresh_token 后,**已签发的 access JWT 在 ≤ 15min TTL 内仍可用**。其他业务最多 15min 后才会因 access 过期 + refresh 失败而跳登录。严格"同时退出所有业务"做不到(跨域 cookie 限制 + JWT 本地验签)。

**v2 演进方向**(超出 v1 范围):
- 选项 A:缩短 access TTL(如 1-2min),以更高 refresh 频率换更快失效
- 选项 B:OIDC front-channel SLO——平台登出页用隐藏 iframe 调每个业务的 `frontchannel_logout_uri`,业务清自己的 cookie
- 选项 C:OIDC back-channel SLO——平台异步 POST 业务的 `backchannel_logout_uri`

v1 不做,留作 v2 单点登出(SLO)专题。

### 3.3 OAuth2 端点(业务接入用)

| Method | Path | 说明 |
|---|---|---|
| GET | `/oauth/authorize` | 授权端点:已登录则直接 302 重定向带 `code`;未登录跳 `/login?return_to=/oauth/authorize?...` |
| POST | `/oauth/token` | 兑换端点:`grant_type=authorization_code` / `refresh_token` / `client_credentials` |
| POST | `/oauth/revoke` | 撤销 refresh_token |

#### GET /oauth/authorize 请求

```
GET /oauth/authorize?response_type=code
                    &client_id=hm-prod
                    &redirect_uri=http://hm.example.com/auth/callback
                    &state=<csrf>
                    &return_to=/admin/tenants
```

平台检查:
- `client_id` 存在且 status=active
- `redirect_uri` ∈ business_client.redirect_uris
- 用户已登录(xinyi_session 有效)→ **静默签发**(SSO 行为:用户在平台登录后,访问任何已授权业务都免再次登录)
- 用户未登录 → 302 到 `/login?return_to=<编码后的原始 /oauth/authorize URL>`,登录后回到此流程

满足则生成 60s 一次性 code,302 到:

```
<redirect_uri>?code=<code>&state=<state>
```

未登录则 302 到 `/login?return_to=<编码后的原始 /oauth/authorize URL>`。

#### POST /oauth/token 响应

```json
{
  "access_token": "<jwt, 15min>",
  "refresh_token": "<opaque, 7d>",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "username": "...",
    "display_name": "...",
    "email": "...",
    "role": "admin"
  }
}
```

业务拿到后:
- access_token 业务本地用共享 `jwt_secret` 验签,**零网络**
- refresh_token 业务存 HttpOnly cookie,过期前调 `/oauth/token` 续
- user info 业务可直接用(短期信任,过期重新刷新)

#### JWT claims 结构

```json
{
  "iss": "xinyi-platform",
  "sub": "<user_id>",
  "aud": "<client_id>",
  "username": "...",
  "role": "admin",
  "jti": "<uuid>",
  "type": "access",
  "exp": <unix>,
  "iat": <unix>
}
```

业务 `auth/dependencies.py` 验签逻辑:
1. `jwt.decode(token, shared_secret, audience=own_client_id)`
2. 检查 `type == "access"`
3. 取 `sub` 作为 user_id(不再查 DB,信任 JWT 内容)
4. 若 access 过期,返回 401 → 前端走 refresh 流程

### 3.4 业务内网端点(client_secret 鉴权)

业务服务到平台的 server-to-server 调用,**只接受 docker 内网 IP**(Network ACL)。

| Method | Path | 说明 |
|---|---|---|
| POST | `/internal/users/batch-get` | body `{ids: [uuid, ...]}`(≤100),返回 `{users: [{id, username, ...}]}` |
| GET | `/internal/users/{id}` | 单用户查询(缓存 miss 兜底) |
| GET | `/internal/users/by-username/{username}` | 按用户名查 |
| POST | `/internal/audit` | 推送审计事件 |
| POST | `/internal/notifications/email` | 发送邮件 |
| POST | `/internal/auth/check-revocation` | 检查 user_id 是否在撤销列表 |

#### POST /internal/users/batch-get

请求:

```json
{
  "ids": ["uuid1", "uuid2"],
  "fields": ["username", "display_name", "email", "role"]
}
```

响应:

```json
{
  "users": {
    "uuid1": {"id": "uuid1", "username": "alice"},
    "uuid2": null
  }
}
```

`null` 表示用户不存在或已停用——业务侧渲染"已删除用户"。

#### POST /internal/audit

请求:

```json
{
  "user_id": "uuid or null",
  "action": "tenant.create",
  "resource_type": "tenant",
  "resource_id": "uuid",
  "detail": {"name": "..."},
  "ip_address": "127.0.0.1",
  "occurred_at": "2026-06-22T...",
  "idempotency_key": "uuid (optional)"
}
```

响应:`202 Accepted`(异步落库)。平台保证至少一次送达(at-least-once),业务可带幂等键去重。

#### POST /internal/notifications/email

请求:

```json
{
  "to": ["user@example.com"],
  "subject": "...",
  "body": "...",
  "html": "... (optional)"
}
```

响应:`202 Accepted`。

### 3.5 管理端(平台 UI)

| Method | Path | 说明 |
|---|---|---|
| GET | `/admin/users` | 用户列表页 |
| POST | `/admin/users` | 创建用户(沿用现有 CreateUserRequest) |
| PUT | `/admin/users/{id}` | 修改(改密、改 role、停用) |
| DELETE | `/admin/users/{id}` | 软删除(`is_active=false`) |
| GET | `/admin/clients` | 业务 client 列表 |
| POST | `/admin/clients` | 注册新业务 client |
| PUT | `/admin/clients/{id}` | 改 redirect_uris / status |
| GET | `/admin/audit-logs` | 审计日志查询(按 client_id / user_id / 时间) |
| GET | `/admin/login-history` | 登录历史 |

### 3.6 hindsight-manager 改造后的 API

#### 新增

| Method | Path | 说明 |
|---|---|---|
| GET | `/auth/callback` | OAuth2 回调,接收 `?code=`,POST 平台 `/oauth/token`,设 hm_session cookie,跳业务首页 |
| POST | `/auth/refresh` | 调平台 `/oauth/token`(grant_type=refresh_token),刷新后更新 cookie |
| POST | `/auth/logout` | 清 hm_session cookie + 调平台 `/oauth/revoke` |
| GET | `/auth/login-redirect` | 业务收到未认证请求时的 302 端点 → 平台 `/oauth/authorize` |

#### 保留(业务专属)

| Method | Path | 说明 |
|---|---|---|
| POST | `/auth/access-token` | 数据平面代理用 access token(15min,tenant-bound) |
| POST | `/auth/otp` | control plane SSO 用 OTP(60s,tenant-bound) |
| GET | `/auth/otp/redirect` | OTP 自动提交表单 |
| POST | `/auth/exchange-otp` | control plane 兑换 |
| 全部 | `/api/proxy/{path}` | 数据平面代理 |

#### 移除(迁到平台)

- `POST /auth/login`、`POST /auth/login/form`、`GET /cas/login`、`GET /cas/callback`
- `POST /auth/users`(用户管理)
- 所有 password / captcha 相关端点

#### 改造 dependencies

`hindsight_manager/auth/dependencies.py` 的 `get_current_user`:

```python
async def get_current_user(
    request: Request,
    token: str | None = Cookie(default=None, alias="hm_session"),
    authorization: str | None = Header(default=None),
    settings = Depends(get_settings),
) -> dict:  # 不再是 User ORM 对象,而是 dict(从 JWT 解出)
    auth_token = token or _extract_bearer(authorization)
    if not auth_token:
        raise HTTPException(401, headers={"Location": "/auth/login-redirect"})
    try:
        payload = jwt.decode(
            auth_token, settings.jwt_secret,
            audience=settings.oauth_client_id, algorithms=["HS256"]
        )
    except JWTError:
        raise HTTPException(401, headers={"Location": "/auth/login-redirect"})
    if payload.get("type") != "access":
        raise HTTPException(401)
    return {
        "id": payload["sub"],
        "username": payload["username"],
        "role": payload["role"],
    }
```

业务代码中所有 `current_user.id` / `current_user.username` / `current_user.role` 保持兼容(返回 dict 后访问字段名一致)。

`require_admin` 不变,只检查 `current_user["role"] == "admin"`。

#### 数据平面 access-token 的微妙之处

现有 `POST /auth/access-token` 是 hindsight-manager 签发的 tenant-bound JWT,跟平台无关。**保留不变**。这是业务层概念,数据平面用,跟用户 session 是两条独立的 token 体系。

### 3.7 错误响应规范

所有平台 API 错误响应统一格式:

```json
{
  "detail": "human readable",
  "code": "INVALID_GRANT",
  "fields": {"username": "required"}
}
```

错误码命名空间:
- `INVALID_GRANT` / `INVALID_CLIENT` / `INVALID_TOKEN`(OAuth2 标准)
- `USER_NOT_FOUND` / `USER_INACTIVE`
- `RATE_LIMITED`(429)
- `FORBIDDEN`(403)
- `INTERNAL_ERROR`(500)

### 3.8 安全约束

- 内网端点(`/internal/*`):只接受 `X-Client-Id` + `X-Client-Secret` 鉴权,且来源 IP 在 docker 网段内
- OAuth2 端点(`POST /oauth/token`):要求 `client_secret`(请求体或 Basic Auth)
- 用户面登录:rate limit 5次/分钟/IP
- 注册 / 找回密码:rate limit 3次/分钟/IP
- 所有 cookie:`HttpOnly`、`Secure`(prod)、`SameSite=Lax`
- CSRF:用户面 POST 端点要求 `X-CSRF-Token` header(从 cookie 双提交)

### 3.9 不做

见"非目标"列表。

## §4 迁移路径

### 4.1 总体策略

**停服一次性迁移**(规模小,不做双写期)。预计停服窗口 5–15 分钟,覆盖:数据迁移 + 服务替换 + 烟囱测试。

**关键约束**:
- 现有用户 session cookie 失效 → 所有用户重新登录(告知用户)
- 现有数据完整保留(不丢、不重置)
- 任一步骤失败可回滚到上一阶段

### 4.2 实施阶段

#### Phase 0:创建 xinyi-platform 项目(0 风险)

不影响现有 hindsight-manager 运行。

- 新建目录 `~/src/lab/xinyi-platform/`(与 `hindsight-manager` 并列)
- `pyproject.toml`、`alembic.ini`、目录结构
- 配置 + 入口 + 空 router + 测试骨架
- docker-compose 加 `xinyi-platform` service(端口 8000),不接入现有流量

**验证**:`xinyi-platform /health` 返回 200;`alembic upgrade head` 创建空 schema。

#### Phase 1:平台核心功能(0 风险)

平台 service 自我完善,数据迁移之前完全独立。

按顺序:
1. 数据模型(§2 那 8 张表)+ Alembic 初始迁移
2. 配置 + DB + crypto + jinja_filters(从 hm 复制)
3. `auth/`:password、local、cas、captcha、session(JWT 签发 + 刷新)
4. `models/`:user、audit_log、login_history、email_verification、business_client、oauth_code、refresh_token、token_revocation
5. `api/`:login、register、password、cas、me(用户面)
6. `api/`:oauth/authorize、oauth/token、oauth/revoke
7. `api/`:internal/(batch-get、audit、email、check-revocation)
8. `api/`:admin(users、clients、audit-logs、login-history)
9. 模板:登录、注册、找回密码、用户中心、admin 页面
10. 启动时建 admin 用户(沿用 hm 的 `ADMIN_PASSWORD` 机制):若 `xinyi.users` 无 admin 用户则创建;若已有(数据迁移后),跳过

**验证**:平台独立运行,本地能完成完整登录流程,签发 JWT,提供所有 API。

#### Phase 2:数据迁移准备(0 风险)

不修改现有数据,只准备脚本。

迁移 SQL:`migrations/xinyi_platform/data_import.sql`

```sql
-- 创建 xinyi schema + ENUM
CREATE SCHEMA IF NOT EXISTS xinyi;
CREATE TYPE xinyi.auth_provider AS ENUM ('local', 'cas');
CREATE TYPE xinyi.user_role AS ENUM ('admin', 'user');
CREATE TYPE xinyi.client_status AS ENUM ('active', 'disabled');

-- 复制 users(同时修正 created_at 类型)
INSERT INTO xinyi.users (id, username, email, password_hash, display_name,
                             auth_provider, role, is_active, last_login_at,
                             created_at, updated_at)
SELECT id, username, email, password_hash, display_name,
       auth_provider::text::xinyi.auth_provider,
       role::text::xinyi.user_role,
       is_active, last_login_at,
       created_at::timestamptz, updated_at
FROM manager.users
ON CONFLICT (id) DO NOTHING;

-- 类似地复制 audit_logs、login_history、email_verifications
```

注册 hindsight-manager 业务 client 的脚本:

```sql
INSERT INTO xinyi.business_clients (id, client_id, name, client_secret_hash,
                                        redirect_uris, status)
VALUES (gen_random_uuid(), 'hm-prod', 'Hindsight Manager',
        '<bcrypt hash of generated secret>',
        '["http://hm:8001/auth/callback", "http://localhost:8001/auth/callback"]',
        'active')
ON CONFLICT (client_id) DO NOTHING;
```

**验证**:在 staging/dev 环境 dry-run,对比 row count + 抽样字段。

#### Phase 3:改造 hindsight-manager(中风险,但隔离)

新分支开发,在 feature flag 后,不影响 master。

**3a. 删除迁走的代码**:

```
hindsight_manager/
  auth/
    local.py        ✗ 删
    cas.py          ✗ 删
    captcha.py      ✗ 删
    password.py     ✗ 删
    session.py      改为薄壳:只保留 create_access_token / verify_access_token(数据平面用)
    audit.py        改为 HTTP 客户端(调平台 /internal/audit)
    dependencies.py 改:本地验签 JWT + 不再查 DB
  models/
    user.py             ✗ 删
    audit_log.py        ✗ 删
    login_history.py    ✗ 删
    email_verification.py ✗ 删
  services/
    email.py        ✗ 删(改为调平台)
  api/
    auth.py         重写:只保留 access-token、otp、exchange-otp、callback、logout
    password.py     ✗ 删
    captcha.py     ✗ 删
    admin.py        拆:用户管理部分删,任务监控保留
    pages.py        拆:登录/注册页删,dashboard 保留
  templates/
    login.html          ✗ 删(平台提供)
    register.html       ✗ 删
    forgot_password.html ✗ 删
    ...                  按归属删减
```

**3b. 新增 xinyi-platform client**:

```
hindsight_manager/
  xinyi_platform/       新模块
    __init__.py
    client.py            PlatformClient(async httpx):batch_get_users、audit、email、refresh、revoke
    cache.py             UserLRUCache(进程内,TTL 5min)
    config.py            XinyiPlatformSettings(client_id、client_secret、platform_url)
```

**3c. 改 dependencies**:见 §3.6。

**3d. 改业务代码兼容 dict**:

`current_user.id` → `current_user["id"]`(所有调用处)。`User` 类型注解改为 `dict | UserData`(TypedDict 或 Pydantic)。

`tenant_members.user_id` 不再是 FK,relationship `user` 删除。需要 user info 时走 `xinyi_client.batch_get_users([m.user_id for m in members])`。

**3e. 新增 OAuth2 callback 端点**:

```python
@router.get("/auth/callback")
async def oauth_callback(
    code: str,
    state: str,
    request: Request,
):
    # 验 state(csrf)
    # 调平台 POST /oauth/token {code, client_id, client_secret, redirect_uri}
    # 设 hm_session cookie(access_token)
    # 设 hm_refresh cookie(refresh_token,HttpOnly,不同的 cookie 名)
    # 跳转 state 里编码的 return_to
```

**3f. 改 OTP / access-token 流程**:

- `/auth/access-token`(数据平面用):逻辑不变,仍是 hm 自签 JWT。`current_user` 改 dict 后,代码相应调整。
- `/auth/otp`:`current_user.id` → `current_user["id"]`。
- `/auth/exchange-otp`:不变。

**验证**:新分支本地跑通完整流程(登录走平台 → callback → hm_session → 业务请求)。

#### Phase 4:停服迁移 + 上线(高风险,但有回滚)

时间窗口(假设周六 02:00):

```
T+0:00  停服(docker-compose stop hindsight-manager control-plane)
T+0:01  跑数据迁移 SQL(Phase 2 的脚本)
T+0:03  验证数据一致性(row count + admin 用户存在)
T+0:04  启动 xinyi-platform service
T+0:05  烟囱测试:curl /login、登录 admin、签发 token
T+0:06  启动改造后的 hindsight-manager(新分支代码)
T+0:07  烟囱测试:浏览器走 OAuth2 流程,登录,访问 /admin/tenants
T+0:10  启动 control-plane
T+0:11  烟囱测试:OTP → control plane SSO
T+0:15  全量放开
```

**关键验证点**:
1. 平台 `/login` 能加载,admin 能登录
2. 浏览器从 hm 入口能跳到平台登录,回调成功
3. 业务页面(tenant/api_key)能正常显示
4. `tenant_members` 列表能正确显示用户名(走 batch-get)
5. 审计日志在平台 admin 能看到业务事件
6. 数据平面代理(`/api/proxy`)仍工作
7. control plane OTP 流程仍工作

#### Phase 5:清理(低风险,延后)

确认稳定 1-2 周后:
- hindsight-manager 的 Alembic 新增迁移:DROP `manager.users`、`manager.audit_logs`、`manager.login_history`、`manager.email_verifications` + 对应 ENUM
- DROP `tenant_members.user_id` 的 FK constraint(若还存在)

### 4.3 数据一致性保证

迁移 SQL 特点:
- **单向复制**:从 `manager.*` 复制到 `xinyi.*`,**不删源表**(过渡期保留,Phase 5 才删)
- **idempotent**:重跑不会重复(用 `ON CONFLICT DO NOTHING`)
- **不修改源数据**:旧 schema 数据保持原样,方便回滚

数据 drift 风险:
- Phase 3 改造期间,旧 hm 仍在写 `manager.users`(若仍跑老代码)
- Phase 4 停服后到新 hm 上线之间,无写入
- 上线后,只 `xinyi.users` 被写,`manager.users` 冻结

### 4.4 回滚策略

| 阶段 | 回滚动作 |
|---|---|
| Phase 1 | 删除 xinyi-platform 目录,无影响 |
| Phase 2 | 不执行迁移 SQL 即可 |
| Phase 3 | 新分支不合并,旧代码无影响 |
| Phase 4 | 关键回滚点:停服窗口内若发现新架构问题,<br>① 停新 hm + xinyi-platform<br>② 回退 hm 镜像到 master 版本<br>③ 起 hm(数据在 manager.users 没动)<br>④ 通知用户重新登录(旧 cookie 也失效) |
| Phase 5 | 不执行 drop 即可 |

### 4.5 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 数据迁移 SQL 失败 | 停服延长 | Phase 2 在 staging 充分 dry-run |
| 新 hm 有未知 bug | 业务不可用 | Phase 3 充分单元测试 + 集成测试;Phase 4 准备回退镜像 |
| 平台抖动导致业务受影响 | 用户体验降级 | LRU 缓存 5min 兜底;access JWT 15min 内本地验签不需要平台 |
| 业务代码 dict 改造遗漏 | 运行时 500 | 类型检查 + 全量 grep `current_user\.` |
| tenant_member 关系丢失导致 N+1 | 性能下降 | batch_get_users 必须用批量接口 |
| cookie 域名问题 | 跨服务登录失败 | 平台和业务同父域 + cookie 设父域;若不同域,完全走 OAuth2 重定向 |
| 旧 cookie 失效用户抱怨 | 用户感知差 | 提前通知 + 登录页说明 |

### 4.6 工程产出清单

实施前必须准备:

- [ ] xinyi-platform 完整代码 + 测试
- [ ] 数据迁移 SQL + dry-run 验证
- [ ] 注册 hm-prod business_client 的 SQL
- [ ] 改造后的 hindsight-manager(新分支)
- [ ] 集成测试覆盖:OAuth2 完整流程 + 业务页面 + 审计推送
- [ ] docker-compose 更新(新增 xinyi-platform service)
- [ ] 回退镜像(master 分支的 hm 镜像)
- [ ] 停服通知(用户告知)
- [ ] 烟囱测试 checklist

### 4.7 不做

见"非目标"列表。

## §5 测试策略

### 5.1 总体原则

沿用 hindsight-manager 惯例:`pytest-asyncio` + `asyncio_mode = "auto"`,mock DB 不打真 Postgres。新增跨服务集成测试层。

### 5.2 测试分层

| 层 | 平台 service | 改造后的 hindsight-manager |
|---|---|---|
| **单元测试** | Settings 校验、密码 hash、JWT 签发/验签、SM4、CSRF、rate limit、business_client 注册校验 | JWT 本地验签、xinyi-platform client 重试、LRU 缓存命中/过期、OAuth2 state 校验 |
| **Service 层测试** | UserService、AuditService、EmailService、OAuthService、TokenService | PlatformClient(httpx mock)、UserCache |
| **API 层测试** | 所有 router 端点鉴权/校验/响应(`dependency_overrides`) | 业务 router + `/auth/callback` + `/auth/refresh` |
| **跨服务集成测试** | 平台 + hm 同时启动(真 httpx 调用),覆盖完整 OAuth2 流程 | 同左 |
| **数据迁移测试** | SQL 脚本在 staging 上验证 row count + 字段抽样 | — |

### 5.3 平台 service 测试用例清单

#### 单元测试(`tests/unit/`)

```
test_password_hashing.py
  - hash_password_creates_bcrypt_hash
  - verify_password_correct
  - verify_password_wrong
  - validate_password_strength_rejects_short
  - validate_password_strength_rejects_common

test_jwt.py
  - create_access_token_has_correct_claims
  - create_refresh_token_format
  - decode_access_token_audience_check
  - decode_access_token_expired
  - decode_access_token_wrong_secret
  - decode_access_token_wrong_type

test_sm4.py
  - encrypt_decrypt_roundtrip
  - decrypt_with_wrong_key_fails

test_csrf.py
  - double_submit_cookie_validates
  - missing_csrf_header_rejected
  - mismatched_csrf_rejected

test_oauth_state.py
  - generate_state_uniqueness
  - verify_state_csrf_protection
```

#### Service 层测试(`tests/services/`)

```
test_user_service.py
  - create_user_success
  - create_user_duplicate_username_fails
  - create_user_weak_password_fails
  - authenticate_local_user_success
  - authenticate_local_user_wrong_password
  - authenticate_local_user_inactive
  - authenticate_cas_user_creates_if_missing
  - change_password_invalidate_existing_sessions
  - soft_delete_user_keeps_row

test_oauth_service.py
  - generate_authorization_code_one_time_use
  - exchange_code_invalid_client_secret
  - exchange_code_expired
  - exchange_code_already_used
  - refresh_token_issues_new_pair
  - refresh_token_revoked_fails
  - revoke_token_clears_refresh
  - refresh_token_user_in_revocation_list_fails

test_audit_service.py
  - push_event_persists
  - push_event_with_idempotency_key_dedup
  - push_event_user_null_anonymous_ok
  - query_by_client_id
  - query_by_user_id_and_time_range

test_email_service.py
  - send_email_smtp_success
  - send_email_smtp_failure_retries
  - send_email_invalid_address_rejected

test_business_client_service.py
  - register_client_generates_id_and_secret
  - verify_client_secret_bcrypt
  - redirect_uri_must_be_in_whitelist
  - disable_client_blocks_oauth
```

#### API 层测试(`tests/api/`)

所有 router 端点 happy path + 主要错误分支:

```
test_login_api.py
  - login_form_success_sets_cookie
  - login_form_wrong_password_returns_401
  - login_form_inactive_user_returns_401
  - login_json_api_success
  - login_rate_limited_after_5_attempts

test_register_api.py
  - register_success
  - register_duplicate_username
  - register_weak_password
  - register_captcha_required

test_password_api.py
  - forgot_password_sends_email
  - reset_password_with_valid_token
  - reset_password_with_expired_token
  - reset_password_with_used_token

test_cas_api.py
  - cas_login_redirects_to_cas_server
  - cas_callback_valid_ticket_creates_user
  - cas_callback_invalid_ticket_returns_401

test_oauth_authorize.py
  - authorize_unauthenticated_redirects_to_login
  - authorize_authenticated_redirects_with_code
  - authorize_invalid_client_id_400
  - authorize_redirect_uri_not_in_whitelist_400
  - authorize_state_preserved_in_redirect

test_oauth_token.py
  - token_grant_authorization_code_success
  - token_grant_authorization_code_invalid_secret
  - token_grant_refresh_token_success
  - token_grant_refresh_token_revoked
  - token_grant_invalid_request_body

test_oauth_revoke.py
  - revoke_clears_refresh_token
  - revoke_already_revoked_idempotent

test_internal_users_api.py
  - batch_get_returns_users_dict
  - batch_get_with_null_for_missing
  - batch_get_over_limit_400
  - batch_get_unauthenticated_401
  - batch_get_wrong_client_secret_401
  - batch_get_from_external_ip_403

test_internal_audit_api.py
  - push_event_accepted
  - push_event_with_idempotency_key
  - push_event_unauthenticated_401

test_internal_email_api.py
  - send_email_accepted
  - send_email_unauthenticated_401

test_admin_users_api.py
  - list_users_paginated
  - create_user_as_admin
  - create_user_as_non_admin_403
  - update_user_role
  - soft_delete_user

test_admin_clients_api.py
  - register_new_client
  - list_clients
  - update_client_redirect_uris
  - disable_client

test_admin_audit_logs_api.py
  - filter_by_client_id
  - filter_by_user_id
  - filter_by_time_range
  - pagination

test_admin_login_history.py
  - filter_by_user_id
  - pagination
```

### 5.4 改造后 hindsight-manager 的测试调整

#### 删除(迁到平台)

```
tests/
  test_admin_users.py       ✗ 删(用户管理在平台)
  test_auth_html.py         ✗ 删(登录页在平台)
  test_captcha.py           ✗ 删
  test_cas_auth.py          ✗ 删
  test_email_service.py     ✗ 删
  test_local_auth.py        ✗ 删
  test_password_api.py      ✗ 删
  test_password_service.py  ✗ 删
  test_user_role.py         ✗ 删(平台管)
```

#### 改写

```
test_session.py
  ✗ 删:create_token / decode_token(session JWT 部分)
  保留:数据平面 access token 的 create_access_token / verify_access_token

test_require_admin.py
  改:`current_user` 从 User 对象改为 dict,role 字段访问方式变

test_access_token.py
  改:current_user.id → current_user["id"]
```

#### 保留不变

```
test_api_keys_api.py
test_crypto.py
test_integration.py
test_manager_tenant.py
test_members_api.py
test_otp_redirect.py
test_proxy.py
test_task_monitor.py
test_tenant_purge.py
test_tenants_api.py
```

#### 改写

```
test_pages.py
  保留:dashboard / tenant 列表 / api_key 列表 / member 列表 相关
  删除:login / register / forgot_password / reset_password 页面测试
```

#### 新增

```
test_auth_callback.py
  - callback_valid_code_exchanges_and_sets_cookie
  - callback_invalid_state_returns_400
  - callback_invalid_code_returns_401
  - callback_redirect_to_return_to

test_auth_refresh.py
  - refresh_success_updates_cookies
  - refresh_with_expired_refresh_token_redirects_to_login
  - refresh_with_revoked_token_401

test_auth_login_redirect.py
  - unauthenticated_request_redirects_to_xinyi_platform
  - redirect_url_includes_return_to
  - redirect_url_includes_state_csrf

test_xinyi_platform_client.py
  - batch_get_users_caches_results
  - batch_get_users_cache_miss_calls_api
  - batch_get_users_cache_expired_refetches
  - batch_get_users_partial_null_for_missing
  - batch_get_users_network_error_raises
  - push_audit_fire_and_forget
  - push_audit_failure_does_not_block_caller
  - refresh_token_success
  - refresh_token_failure_propagates

test_user_cache.py
  - lru_get_hit
  - lru_get_miss
  - lru_eviction_when_full
  - lru_expiry_after_ttl

test_logout.py
  - logout_clears_hm_cookies
  - logout_calls_platform_revoke
```

### 5.5 跨服务集成测试

新建 `tests/integration/test_oauth_flow.py`:

```python
@pytest.mark.integration
async def test_full_oauth2_login_flow():
    """启动 xinyi-platform + hm 两个 service,真 httpx 跑完整登录。"""
    # 1. 浏览器 GET /admin/tenants → 302 to /auth/login-redirect
    # 2. → 302 to xinyi-platform /oauth/authorize
    # 3. → 302 to xinyi-platform /login(未登录)
    # 4. POST xinyi-platform /login/form(admin) → 设 xinyi_session
    # 5. → 302 to xinyi-platform /oauth/authorize(已登录)
    # 6. → 302 to hm /auth/callback?code=xxx
    # 7. hm POST xinyi-platform /oauth/token → 获取 access+refresh
    # 8. 设 hm_session cookie,302 to /admin/tenants
    # 9. GET /admin/tenants with hm_session → 200
    # 10. 页面里能正确显示 tenant_members 用户名(走 xinyi-platform batch-get)
    # 11. 审计事件已推送到平台

@pytest.mark.integration
async def test_token_refresh_flow():
    """access 过期,refresh 自动续。"""

@pytest.mark.integration
async def test_admin_revokes_user():
    """admin 在平台封禁用户,该用户 hm 内的 access 过期后无法 refresh。"""

@pytest.mark.integration
async def test_platform_outage_degrades_gracefully():
    """平台挂时:LRU 内的 user info 仍能服务列表页;
    新登录失败(明确报错);
    审计推送进 outbox 表,平台恢复后重试。"""

@pytest.mark.integration
async def test_audit_eventually_consistent():
    """业务推送审计 → 平台落库 → admin 在 /admin/audit-logs 能查到。"""
```

集成测试用真 Postgres(testcontainers 或 staging)。

### 5.6 数据迁移测试

```
tests/migration/
  test_data_import.py
    - import_users_count_matches_source
    - import_users_preserves_all_fields
    - import_users_created_at_cast_to_timestamptz
    - import_audit_logs_count_matches
    - import_login_history_count_matches
    - import_email_verifications_count_matches
    - import_idempotent_run_twice_no_dup
    - register_business_client_inserted
```

执行环境:staging 数据库的 dump(每周同步),非生产。

### 5.7 烟囱测试 checklist(Phase 4 上线用)

人工执行(15 分钟内完成):

```
□ 平台 /login 能加载
□ admin 能登录平台
□ 平台 /admin/users 显示所有用户
□ 浏览器从 hm 入口能跳到平台登录
□ 登录成功回调到 hm,设 hm_session cookie
□ hm /admin/tenants 列表正常
□ 创建 tenant,member 列表显示用户名
□ 创建 api_key,数据平面代理调用成功
□ OTP → control plane SSO 流程正常
□ hm 产生业务事件(如 tenant.create)
□ 平台 /admin/audit-logs 能看到该事件
□ 平台 /admin/login-history 显示 admin 登录记录
□ hm 登出,清 hm_session cookie
□ 再次访问 hm 业务页面,跳转平台登录
□ 平台挂掉(docker stop xinyi-platform),验证:
   - 已登录用户仍能访问 hm 业务页面 15min(access JWT 本地验签)
   - 列表页 user info 从 LRU 缓存读取(5min 内)
   - 审计推送失败进 outbox,不阻塞业务
   - 15min 后 access 过期,refresh 失败 → 401 → 跳登录(此时平台恢复即可)
```

### 5.8 性能验证(轻量)

v1 不做严格压测,但需观察:

- **业务请求延迟**:验证 `get_current_user` 本地验签 < 1ms(无网络调用)
- **batch_get_users 延迟**:50 个 user_id 批量查询 < 100ms
- **审计推送延迟**:`asyncio.create_task` 不阻塞主请求,主请求延迟 < 5ms
- **LRU 命中率**:观察生产 1 周,目标 > 95%

通过平台 `/admin/audit-logs` 的 `created_at` 跟 `occurred_at` 差值监控推送延迟。

### 5.9 覆盖率目标(v1 不强制阈值,核心模块建议)

| 模块 | 目标 |
|---|---|
| 平台 OAuthService | ≥ 95%(安全关键) |
| 平台 UserService | ≥ 90% |
| 平台 audit/email service | ≥ 80% |
| 平台 API 层 | ≥ 75% |
| hm PlatformClient | ≥ 85% |
| hm auth/dependencies | ≥ 90% |
| hm 业务 API 层 | ≥ 70%(基本不变) |
| 数据迁移脚本 | 行为验证为主 |

### 5.10 持续集成

- 平台 service 独立 CI:GitHub Actions / 同等
- 单元 + service 层测试:每次 PR
- API 层测试:每次 PR
- 集成测试:nightly + release 前
- 数据迁移测试:release 前
- hm CI:删除迁走的测试后,覆盖率不应下降(以"保留测试数"为基线)

### 5.11 不做

- 不做性能压测脚本(只观察)
- 不做 chaos engineering(规模不够)
- 不做 fuzzing(v1)
- 不做 mutation testing
- 不做 e2e 浏览器自动化(烟囱测试人工)
- 不做契约测试(平台 client 手写,Schema 固定后不常变)

## 实现顺序建议

供后续 writing-plans 参考:

1. **Phase 0 项目骨架**:`xinyi-platform` pyproject、目录、Settings、main.py + lifespan、Alembic 初始空 schema、Dockerfile、docker-compose
2. **Phase 1 平台核心(按依赖顺序)**:
   - 数据模型(8 张表 + 3 个 ENUM)+ 初始迁移
   - 配置 / DB / crypto / jinja_filters(从 hm 复制)
   - `auth/`(password、local、cas、captcha、session)+ 单元测试
   - `models/` + 单元测试
   - 用户面 API(login、register、password、cas、me)+ API 测试
   - OAuth2 API(authorize、token、revoke)+ API 测试
   - Internal API(batch-get、audit、email)+ API 测试
   - Admin API(users、clients、audit-logs、login-history)+ API 测试
   - 模板 + 启动建 admin
3. **Phase 2 数据迁移脚本 + dry-run**
4. **Phase 3 改造 hindsight-manager(独立分支)**:
   - 新增 xinyi-platform client + LRU cache + 测试
   - 改 dependencies(dict)+ 全量业务代码兼容 + 测试调整
   - 新增 OAuth2 callback / refresh / logout / login-redirect 端点 + 测试
   - 删除迁走的代码 + 模板 + 测试
5. **Phase 4 停服迁移 + 上线**:执行 SQL、启动顺序、烟囱测试 checklist
6. **Phase 5 清理**:稳定 1-2 周后执行 DROP 迁移

## 已知后续工作(超出 v1)

- docupipe-manager spec 重写:基于本平台契约,删除"import hindsight_manager"路线,改为 OAuth2 client 接入
- 平台 SDK 抽取:若第 3 个业务接入,考虑把 `xinyi-platform client + LRU cache` 抽成独立 pip 包
- 独立 Postgres 实例:平台流量增长后考虑物理隔离
- 平台多副本 + 高可用:支持 HA 部署
- 事件总线:替代 LRU + 批量拉,推送用户变更
