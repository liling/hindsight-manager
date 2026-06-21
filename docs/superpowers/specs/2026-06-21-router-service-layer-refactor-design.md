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
