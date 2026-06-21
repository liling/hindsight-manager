# Router → Service 层抽离（tenant / api_key / member 三块）

**日期**：2026-06-21
**驱动力**：纯代码整洁（无近期功能压力），渐进式、低风险整理
**范围**：`api/tenants.py`、`api/api_keys.py`、`api/members.py` 三个 router 的业务逻辑下沉到 `services/`

---

## 背景

当前 `api/` 下的 router 直接承担业务逻辑（参数解析 → ORM → 加密 → 校验 → 返回），`services/` 目录除 `email.py` 外为空。具体痛点（实测）：

1. **权限校验重复 3 份**：`_require_owner` / `_require_membership` 在 `api_keys.py`、`members.py`、`tenants.py` 内复制粘贴，逻辑相同、细节微差。
2. **业务逻辑内嵌 router**：典型如 `tenants.py:create_tenant` 一个函数做 4 件事（建 tenant、加 owner member、生成 system key、SM4 加密），与 HTTP 层耦合。
3. **常量重复**：`KEY_PREFIX = "hsm_"` 在 `tenants.py` 与 `api_keys.py` 各定义一份。
4. **本地 helper 重复**：`api_keys.py` 内 `_fmt` / `_fmt_dt` 日期格式化函数重复 2 次。

未在本次范围内、但同样值得后续关注的文件：`admin.py`（568 行，独立管理视角）、`auth.py`（369 行）、`password.py`（328 行）。

## 目标

- router 只负责 HTTP 边界（参数解析、调 service、调 dependency、构造 Pydantic 响应）
- 业务逻辑（ORM、加密、跨表写、状态变更）下沉到 `services/`，以纯函数形式存在，可直接单测
- 治权限校验重复，三个 router 共享一份 dependency

## 非目标

- 不抽 `repositories/` 层（ORM 调用直接在 service 内）
- 不引入 `schemas/` 目录（Pydantic 保留在 router 文件，它们是 API 边界契约）
- 不动 `admin.py` / `auth.py` / `password.py` / `task_monitor.py` / `pages.py` / `proxy.py` / `captcha.py`
- 不重写测试框架（沿用 pytest-asyncio + 现有 conftest）
- 不抽公共 `utils/datetime.py`（`_fmt` 仅在 `api_keys.py` 内合并一份）

## 架构

新增 4 个文件：

```
hindsight_manager/
├── api/
│   ├── tenants.py        ← 改造：只做 HTTP 层
│   ├── api_keys.py       ← 改造：只做 HTTP 层
│   └── members.py        ← 改造：只做 HTTP 层
└── services/
    ├── email.py          ← 不动
    ├── membership.py        ← 新增：共享权限 dependency
    ├── tenant_service.py    ← 新增
    ├── api_key_service.py   ← 新增
    └── member_service.py    ← 新增
```

**分层规则**：

| 层 | 职责 | 不允许做的事 |
|---|---|---|
| router | 参数解析、调 service、调 dependency、构造 Pydantic 响应 | ORM、加密、业务校验逻辑 |
| service | 业务逻辑（ORM、加密、跨表写、状态变更），纯函数 `(session, ...)` | HTTP 概念（Request、status_code） |
| membership | FastAPI 权限 dependency | 业务逻辑 |

**风格选择**：service 用**函数式**（一组 async 函数），与现有 `_require_membership` 一致，不引入 `EmailService` 那种类 + Protocol 形态——tenant/key/member 没有可替换实现的需求。

## 组件

### `services/membership.py`（共享权限 dependency）

```python
async def require_membership(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
    require_owner: bool = False,
) -> tuple[TenantMember, Tenant]:
    """404 if not a member; 403 if require_owner=True and role != OWNER."""

async def require_owner(
    session: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
) -> Tenant:
    """Wrapper: require_membership(require_owner=True), return tenant only."""
```

**调用约定**：作为普通 async 函数在 endpoint 顶部直接调用，**不**封装为 `Depends(...)` 工厂——因为 `tenant_id` 来自 path param、`current_user` 来自另一个 dependency，组合成 dependency 工厂反而增加复杂度。

**router 内统一用法**：
```python
_, tenant = await require_owner(session, current_user, tenant_id)           # api_keys.py, members.py
_, tenant = await require_membership(session, current_user, tenant_id)      # tenants.py (list/get)
_, tenant = await require_membership(session, current_user, tenant_id, require_owner=True)  # tenants.py (update/delete)
```

### `services/tenant_service.py`

承接 `api/tenants.py` 5 个 endpoint 的业务：

```python
async def list_tenants_for_user(session, user_id) -> list[Tenant]
async def create_tenant(session, owner: User, name: str) -> Tenant
async def get_tenant(session, tenant_id) -> Tenant
async def update_tenant_config(session, tenant: Tenant, name: str | None, config_patch: dict) -> Tenant
async def mark_tenant_deleting(session, tenant: Tenant) -> None
```

**关键内聚**：`create_tenant` 把现在散落在 `tenants.py:97-131` 的 4 件事（建 tenant、加 owner member、生成 system key、SM4 加密）全部内聚。`Settings()`、`encrypt_sm4`、`KEY_PREFIX`、`SYSTEM_KEY_NAME` 全部由 service 持有，router 不再 import `crypto` / `config`。

**传实例而非 ID**：`update_tenant_config` 与 `mark_tenant_deleting` 接收 `Tenant` 实例（router 已通过 `require_membership` 拿到），避免重复查询。

### `services/api_key_service.py`

承接 `api/api_keys.py` 4 个 endpoint 的业务：

```python
KEY_PREFIX = "hsm_"  # 统一放在这里；tenants.py 与 api_keys.py 原有的同名常量删除

async def create_api_key(session, tenant_id, name) -> tuple[ApiKey, str]
    # 返回 (record, raw_key_only_once)
async def list_api_keys(session, tenant_id) -> list[ApiKey]
    # system key 在前，然后按 created_at desc
async def revoke_api_key(session, tenant_id, key_id) -> None
    # 404 if not found 或 属于其他 tenant
async def update_api_key_name(session, tenant_id, key_id, name) -> ApiKey
    # 404 if missing; 403 if is_system; 422 if name length 不在 1..255
```

### `services/member_service.py`

承接 `api/members.py` 5 个 endpoint 的业务：

```python
async def list_members(session, tenant_id) -> list[TenantMember]
async def lookup_user(session, tenant_id, username) -> tuple[User, bool]
    # 返回 (user, is_already_member)；404 if user 不存在
async def add_member(session, tenant_id, username, role) -> TenantMember
    # 404 if user 不存在；409 if 已是成员
async def remove_member(session, tenant_id, user_id) -> None
async def update_member_role(session, tenant_id, user_id, role) -> TenantMember
```

## 数据流

以 `POST /tenants` 为例（重构后）：

```
Request → router.create_tenant
  └─ 参数解析 (TenantCreateRequest)
  └─ get_current_user → User
  └─ get_session → AsyncSession
  └─ tenant_service.create_tenant(session, owner, name)
       ├─ 生成 schema_name
       ├─ ORM: Tenant.insert + flush
       ├─ ORM: TenantMember.insert (OWNER)
       ├─ 生成 raw_key, sha256 hash, prefix
       ├─ encrypt_sm4(raw_key, key)  ← Settings().encryption_key
       └─ ORM: ApiKey.insert (is_system=True)
       └─ commit + refresh
  └─ _tenant_response(tenant) → TenantResponse
```

## 错误处理

- HTTP 状态码（404/403/409/422）由 **service 层 raise `HTTPException`** 维持现状——FastAPI 的 `HTTPException` 不算 HTTP 概念污染，把它当业务异常用是项目既有约定（`_require_membership` 就是这么做的），不强求引入自定义异常体系。
- 校验消息保持现状（如 "名称长度需在 1-255 之间"），不在本次范围内国际化或重写。

## 测试

**重构前**：
```bash
uv run pytest tests/ -v   # 记录绿灯基线
```

**重构后**：

| 层 | 测试方式 |
|---|---|
| service 层（新） | 直接 `await xxx_service.fn(session, ...)`，mock `session.execute` 等。**重构最大收益**：业务逻辑可直接单测，无需走 FastAPI。 |
| router 层 | 现有 `tests/test_tenants*.py`、`tests/test_api_keys*.py`、`tests/test_members*.py`（如存在）保持端到端调用方式不变，mock 行为不变，业务路径从 router 内部走到 service 再回。 |

**回归保证**：重构后必须全绿，否则回滚那一块。不绿先修，不绕过。

## 改造前后对比

以 `POST /tenants/{tenant_id}/api-keys` 为例（最简单的 router 之一）：

**改造前**（`api/api_keys.py:63-89`，27 行）：
```python
@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(tenant_id, req, current_user=Depends(...), session=Depends(...)):
    await _require_owner(session, current_user, tenant_id)
    raw_key, key_hash = _generate_api_key()
    api_key = ApiKey(tenant_id=tenant_id, key_hash=key_hash, ...)
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    def _fmt(v): ...
    return ApiKeyCreatedResponse(...)
```

**改造后**：
```python
@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(tenant_id, req, current_user=Depends(...), session=Depends(...)):
    await require_owner(session, current_user, tenant_id)
    api_key, raw_key = await api_key_service.create_api_key(session, tenant_id, req.name)
    return _api_key_created_response(api_key, raw_key)
```

router 从 27 行降到 5 行，业务逻辑可在 `test_api_key_service.py` 直接单测。

---

## 审查决议与发现（plan-eng-review, 2026-06-21）

### 范围与原则（经用户确认）

- **D1** `list_members` 保持任意成员可见（非 OWNER-only）。现有测试 `test_list_members_as_member` 显式断言 200。`services/membership.py` 提供 `require_membership(session, user, tenant_id)`，`list_members` 路由调用它，**不传** `require_owner=True`。
- **D2** `list_tenants_for_user` 由 service 自己做 user→tenant join，不试图合并进 `require_membership`（语义不同：后者需 `tenant_id`，前者无）。
- **D3** `delete_tenant` 保持软删：`mark_tenant_deleting(session, tenant)` 仅改 `status=DELETING`，真实删除仍由 `task_monitor.py` 异步执行。
- **D4** 三个 router 改造按顺序逐个提交，每个改造前先跑 `uv run pytest tests/ -v` 记基线，改造后再跑，失败立即回滚。
- **D5** `Settings()` 每次请求实例化的现状不治。重构只移动位置，不动 config。
- **D6** 在本 PR 内补齐缺失的 `api_keys` 测试：`POST /api-keys`、`GET /api-keys`、`DELETE /api-keys/{id}` 三个 endpoint 无专项测试，重构必动这些路径，补齐是重构的同步职责（见 T3）。
- **D7** service 返回 ORM 实例（`Tenant` / `ApiKey` / `TenantMember`），由 router 转 Pydantic。
- **D8** 本 PR 不新增 service 层独立单测文件，沿用现有 router 端到端测试覆盖行为不变。

### 关键修正（高置信度发现）

#### Issue 1 [P1] (confidence: 9/10) `list_members` 权限边界
**位置**：原 `api/members.py:55-65`（改造前）
**问题**：设计文档第 13 行说"三个 router 复制 `_require_owner`/`_require_membership`"，但 `list_members` 走的是 inline 的"任意成员可看"分支，与 `lookup_member` / `add_member` 的 OWNER-only 不同。
**修正**：在 `services/membership.py` 提供 `require_membership(session, user, tenant_id)`（无 OWNER 校验），供 `list_members` 调用；`lookup_member` / `add_member` / `remove_member` / `update_member_role` 仍调 `require_owner`。

#### Issue 2 [P2] (confidence: 9/10) `KEY_PREFIX` 唯一性
**位置**：`api_keys.py:19`、`tenants.py:19`
**问题**：已确认两份 `KEY_PREFIX = "hsm_"`。但 `tenants.py:113` 用 `secrets.token_hex(32)` 生成 raw key，`api_keys.py:23` 用 `secrets.token_urlsafe(32)` —— **生成方式不同**。设计只提到统一常量，没提到统一生成方式。
**修正**：`api_key_service.py` 暴露统一函数 `_generate_raw_key()`（采用 `token_urlsafe`，与 `api_keys` 端点现状一致；`tenants.py` 的 `token_hex` 路径视为可替换）。注：`tenants.py:113` 的 system key 改用统一函数后，生成的 key 会从 hex 变为 url-safe base64，但 `key_prefix` 仍是前 16 字符，前缀空间足够区分。

#### Issue 3 [P2] (confidence: 8/10) `Settings()` 重复实例化
**位置**：`tenants.py:112`、`tenants.py:116`
**说明**：每次 `create_tenant` 都会 `settings = Settings()` + `bytes.fromhex(settings.encryption_key)`，重构后这些调用搬到 `tenant_service.create_tenant` 内部。**D5 决议不动**，但 service 内应把这两行集中到一个 helper：`_get_encryption_key()`，避免分散。

#### Issue 4 [P3] (confidence: 7/10) `_fmt` 重复 2 次
**位置**：`api_keys.py:78`、`api_keys.py:163`（改造前）
**说明**：设计承诺"`_fmt` 仅在 `api_keys.py` 内合并一份"，正确。改造后这两个 `_fmt` 应合并为 router 文件内的模块级 `_fmt_dt(v)`，且保留 `None` 处理（原 `list_api_keys` 的 `_fmt_dt` 处理 None，原 `create_api_key` 的 `_fmt` 不处理 —— 以更严格的版本为准）。

#### Issue 2.5 [P2] (resolved 2026-06-21, user-approved) 404 detail 统一
**位置**：原 `api/api_keys.py:35`、`api/members.py:48`（改造前）使用 `detail="Not found"`；原 `api/tenants.py:77` 使用 `detail="Tenant not found or you are not a member"`。
**说明**：共享 `services/membership.py` 后，三个 router 的 404 detail 被统一为更准确的 `"Tenant not found or you are not a member"`（沿用 tenants.py 原版本）。前端不依赖此 detail 文本（已验证 templates/ 与 static/ 无引用）。**用户审批为统一化的合理一部分。**

### NOT in scope

- 不抽 `repositories/` 层（已声明，确认）
- 不引入 `schemas/` 目录（已声明，确认）
- 不动 `admin.py` 的 `_fmt`（已知遗留债务，与本次重构同构但范围爆炸）
- 不动 `auth.py` / `password.py` / `task_monitor.py` / `pages.py` / `proxy.py` / `captcha.py`（已声明，确认）
- 不动 `Settings()` 实例化策略（D5）
- 不写 service 层独立单测文件（D8）
- 不抽公共 `utils/datetime.py` —— `_fmt` 仅在 `api_keys.py` 内合并（已声明）
- 不重写测试框架（已声明）
- 不修 `member_service.add_member` 并发竞态（已知现状，独立 PR）

### What already exists

- **`_require_membership`**（`tenants.py:64`）、**`_require_owner`**（`api_keys.py:27`, `members.py:40`）已存在，本次下沉到 `services/membership.py`。
- **`_generate_api_key`**（`api_keys.py:22`）已存在，搬到 `api_key_service.py` 并对外暴露给 `tenant_service.create_tenant` 使用（取代 `tenants.py` 内部那段 raw key 生成代码）。
- **`Settings()` + `encrypt_sm4`** 已在 `tenants.py:111-117` 使用，本次下沉到 `tenant_service`。
- **`_fmt` / `_fmt_dt`** 在 `api_keys.py` 重复 2 次，本次合并为单份 `_fmt_dt`。

### 改造前后对比（补充）

**`GET /tenants/{tenant_id}/members`** 改造后：

```python
@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await require_membership(session, current_user, tenant_id)  # 任意成员可看，非 require_owner
    members = await member_service.list_members(session, tenant_id)
    return [_member_response(m, u) for m, u in members]
```

### 测试覆盖图（改造后应满足）

```
CODE PATHS                                            USER FLOWS
[+] api/tenants.py                                     [+] Create tenant
  ├── POST /tenants                                      ├── [★★ TESTED] owner creates — test_tenants_api.py
  ├── GET /tenants                                       ├── [GAP] list_tenants: by_user
  ├── GET /tenants/{id}                                  └── [GAP] update name + config: edge empty/long
  ├── PATCH /tenants/{id}                              [+] Members management
  └── DELETE /tenants/{id}                                ├── [★★ TESTED] list as owner/member/non-member
[+] api/api_keys.py                                       ├── [★★ TESTED] add as owner / forbidden / 404 / 409
  ├── POST /api-keys                                      ├── [★★ TESTED] lookup success/already/404/forbidden
  ├── GET /api-keys                                       ├── [★★ TESTED] remove as owner/forbidden
  ├── DELETE /api-keys/{id}                               └── [★★ TESTED] change role as owner/forbidden
  └── PATCH /api-keys/{id}                              [+] API keys
[+] api/members.py                                        ├── [★★ TESTED] update name success/empty/long/system/forbidden/not_found/wrong_tenant
  ├── GET /members                                        ├── [GAP] [→T3] POST /api-keys
  ├── GET /members/lookup                                 ├── [GAP] [→T3] GET /api-keys
  ├── POST /members                                       └── [GAP] [→T3] DELETE /api-keys/{id}
  ├── DELETE /members/{user_id}
  └── PATCH /members/{user_id}

COVERAGE: 现有 ~85% paths covered | GAPS: 3 api_keys endpoints (T3 待补)
```

### Implementation Tasks

- [ ] **T1 (P1, human: ~1h / CC: ~10min)** — `services/membership.py` — 提取 `require_membership` / `require_owner`，处理 list_members 的任意成员可见边界
  - 文件：新建 `hindsight_manager/services/membership.py`
  - 验证：`uv run pytest tests/test_members_api.py tests/test_tenants_api.py -v`
- [ ] **T2 (P1, human: ~2h / CC: ~20min)** — `services/tenant_service.py` + 改造 `api/tenants.py` — 下沉 5 个 endpoint 的业务逻辑，统一 `KEY_PREFIX` 与 `_generate_api_key`
  - 文件：新建 service、改造 `api/tenants.py`
  - 验证：`uv run pytest tests/ -v` 全绿
- [ ] **T3 (P1, human: ~1h / CC: ~15min)** — 补齐 `api_keys` 三个 endpoint 测试（`POST /api-keys`、`GET /api-keys`、`DELETE /api-keys/{id}`）—— 现有测试缺口，重构前补
  - 文件：新建 `tests/test_api_keys_api.py` 或扩展 `tests/test_tenants_api.py`
  - 验证：三个新测试绿
- [ ] **T4 (P1, human: ~1.5h / CC: ~15min)** — `services/api_key_service.py` + 改造 `api/api_keys.py` — 下沉 4 个 endpoint，合并 `_fmt` → `_fmt_dt`
  - 文件：新建 service、改造 `api/api_keys.py`
  - 验证：`uv run pytest tests/ -v` 全绿
- [ ] **T5 (P1, human: ~1.5h / CC: ~15min)** — `services/member_service.py` + 改造 `api/members.py` — 下沉 5 个 endpoint，注意 list_members 不走 require_owner
  - 文件：新建 service、改造 `api/members.py`
  - 验证：`uv run pytest tests/ -v` 全绿

### 改造顺序（per D4 决议）

T3 → T1 → T2 → T4 → T5。每个 T 提交后立即 `uv run pytest tests/ -v`，失败立刻回滚。T3 必须在 T1 之前，因为 `api_keys.py` 改造会删除原 `_require_owner`，依赖 `require_membership` 服务模块存在。

### 失败模式与防护

| codepath | 失败模式 | 测试 | 错误处理 |
|---|---|---|---|
| `tenant_service.create_tenant` SM4 加密 | `settings.encryption_key` 长度错误 | 缺 | `bytes.fromhex` 抛 `ValueError`，500 |
| `api_key_service.create_api_key` 唯一性 | `key_hash` 碰撞（理论 2^256） | 缺 | DB unique constraint → 500 |
| `member_service.add_member` 并发 | 两个并发 add 同一 user | 缺 | 缺 —— 第二个成功（无 unique constraint），状态不一致 |
| `mark_tenant_deleting` 二次调用 | 同一 tenant 重复软删 | 缺 | 第二次 200（status 已为 DELETING） |

注：`member_service.add_member` 并发竞态是**已知现状**，不在本次重构范围。如要修，需加 `(tenant_id, user_id)` unique constraint + 409 处理，单独 PR。

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open | 4 issues, 0 critical gaps, D1-D8 resolved with user |

- **UNRESOLVED：** 0
- **VERDICT：** ENG CLEARED — ready to implement (T1-T5 tasks pending)
