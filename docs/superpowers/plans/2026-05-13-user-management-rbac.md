# 用户管理与 RBAC 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Hindsight Manager 添加系统级 RBAC（admin/user 角色）和完整的管理后台（用户管理、租户管理、API Key 管理、审计日志）。

**Architecture:** 在 User 模型添加 `role` 枚举字段，通过 FastAPI 依赖 `require_admin` 统一校验。新增 `api/admin.py` 集中所有管理端点，新增 `models/audit_log.py` 记录审计日志。前端在现有 dashboard 基础上扩展管理页面。

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, Jinja2, SQLite-style vanilla JS

**Spec:** `docs/superpowers/specs/2026-05-13-user-management-rbac-design.md`

---

### Task 1: 添加 UserRole 枚举和 User.role 字段

**Files:**
- Modify: `hindsight_manager/models/user.py`
- Modify: `hindsight_manager/models/__init__.py`
- Test: `tests/test_user_role.py`

- [ ] **Step 1: 写测试**

创建 `tests/test_user_role.py`：

```python
from hindsight_manager.models.user import User, UserRole


def test_user_role_enum_values():
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.USER.value == "user"


def test_user_default_role():
    u = User(
        username="testuser",
        display_name="Test",
        auth_provider="local",
    )
    assert u.role == UserRole.USER
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_user_role.py -v`
Expected: FAIL — `UserRole` 不存在

- [ ] **Step 3: 修改 `models/user.py`，添加 `role` 字段**

在 `hindsight_manager/models/user.py` 中：

1. 在 `AuthProvider` 类之前添加 `UserRole` 枚举：

```python
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
```

2. 在 `User` 类中，`is_active` 字段之后、`memberships` 之前添加：

```python
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", schema="manager"),
        nullable=False,
        default=UserRole.USER,
        server_default="USER",
    )
```

3. 添加 `import enum` 已有则不需要。

- [ ] **Step 4: 更新 `models/__init__.py`**

在 `hindsight_manager/models/__init__.py` 中添加导出：

```python
from hindsight_manager.models.user import AuthProvider, User, UserRole
```

并在 `__all__` 中添加 `"UserRole"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_user_role.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add hindsight_manager/models/user.py hindsight_manager/models/__init__.py tests/test_user_role.py
git commit -m "feat: add UserRole enum and User.role field"
```

---

### Task 2: 数据库迁移 — 添加 role 列和 audit_logs 表

**Files:**
- Create: `hindsight_manager/migrations/versions/003_add_user_role_and_audit_logs.py`

- [ ] **Step 1: 编写迁移文件**

创建 `hindsight_manager/migrations/versions/003_add_user_role_and_audit_logs.py`：

```python
"""add user role and audit logs

Revision ID: 003
Revises: 002
Create Date: 2026-05-13
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    # 添加 user_role 枚举类型
    user_role = sa.Enum("ADMIN", "USER", name="user_role", schema=SCHEMA, create_type=True)
    user_role.create(op.get_bind(), checkfirst=True)

    # 添加 users.role 列
    op.add_column(
        "users",
        sa.Column("role", user_role, nullable=False, server_default="USER"),
        schema=SCHEMA,
    )

    # 数据迁移：将 username='admin' 的用户设为 ADMIN
    op.execute(f"UPDATE {SCHEMA}.users SET role = 'ADMIN' WHERE username = 'admin'")

    # 创建 audit_logs 表
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], schema=SCHEMA)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], schema=SCHEMA)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], schema=SCHEMA)
    op.create_index("ix_audit_logs_resource_type_id", "audit_logs", ["resource_type", "resource_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("audit_logs", schema=SCHEMA)
    op.drop_column("users", "role", schema=SCHEMA)
    sa.Enum(name="user_role", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 2: 提交**

```bash
git add hindsight_manager/migrations/versions/003_add_user_role_and_audit_logs.py
git commit -m "feat: add migration for user role and audit_logs table"
```

---

### Task 3: 添加 AuditLog 模型

**Files:**
- Create: `hindsight_manager/models/audit_log.py`
- Modify: `hindsight_manager/models/__init__.py`

- [ ] **Step 1: 创建 `models/audit_log.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from hindsight_manager.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 2: 更新 `models/__init__.py`**

添加导入和导出：

```python
from hindsight_manager.models.audit_log import AuditLog
```

在 `__all__` 中添加 `"AuditLog"`。

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/models/audit_log.py hindsight_manager/models/__init__.py
git commit -m "feat: add AuditLog model"
```

---

### Task 4: 添加 require_admin 依赖和 log_audit 辅助函数

**Files:**
- Modify: `hindsight_manager/auth/dependencies.py`
- Create: `hindsight_manager/auth/audit.py`
- Test: `tests/test_require_admin.py`

- [ ] **Step 1: 写测试**

创建 `tests/test_require_admin.py`：

```python
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret")

from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.models.user import User, UserRole


def _make_user(role: UserRole = UserRole.USER) -> User:
    u = User.__new__(User)
    u.id = uuid.uuid4()
    u.username = "testuser"
    u.display_name = "Test"
    u.role = role
    u.is_active = True
    return u


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    admin = _make_user(UserRole.ADMIN)
    result = await require_admin(admin)
    assert result.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_require_admin_rejects_user():
    user = _make_user(UserRole.USER)
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user)
    assert exc_info.value.status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_require_admin.py -v`
Expected: FAIL — `require_admin` 不存在

- [ ] **Step 3: 在 `auth/dependencies.py` 添加 `require_admin`**

在 `hindsight_manager/auth/dependencies.py` 末尾添加：

```python
from hindsight_manager.models.user import UserRole

async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user
```

注意：`User`、`Depends`、`HTTPException`、`status` 都已在文件中导入，只需额外导入 `UserRole`。

- [ ] **Step 4: 创建 `auth/audit.py`**

```python
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.models.audit_log import AuditLog


async def log_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        ip_address=ip_address,
    )
    session.add(entry)
```

注意：不单独 commit，由调用方的业务逻辑统一 commit。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_require_admin.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add hindsight_manager/auth/dependencies.py hindsight_manager/auth/audit.py tests/test_require_admin.py
git commit -m "feat: add require_admin dependency and log_audit helper"
```

---

### Task 5: 替换硬编码 admin 检查

**Files:**
- Modify: `hindsight_manager/api/auth.py`
- Modify: `hindsight_manager/main.py`
- Modify: `hindsight_manager/templates/admin_base.html`

- [ ] **Step 1: 修改 `api/auth.py` — 用 `require_admin` 替换硬编码**

将第 12 行的导入：
```python
from hindsight_manager.auth.dependencies import SESSION_COOKIE, get_current_user
```
改为：
```python
from hindsight_manager.auth.dependencies import SESSION_COOKIE, get_current_user, require_admin
```

删除 `from hindsight_manager.models.user import AuthProvider, User` 中对 User 的依赖（如果 create_user 端点不再直接用 User 做参数也可以保留）。

将 `create_user` 函数签名：
```python
async def create_user(
    req: CreateUserRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a new user (admin only)."""
    # Check if current user is admin
    if current_user.username != "admin":
        raise HTTPException(status_code=403, detail="Only admin can create users")
```

改为：
```python
async def create_user(
    req: CreateUserRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
```

删除函数体中的 `if current_user.username != "admin":` 两行。

- [ ] **Step 2: 修改 `main.py` — admin 用户创建时设置 role**

在 `_ensure_admin_user` 函数中，INSERT 语句添加 `role` 字段值 `'ADMIN'`：

将：
```python
"INSERT INTO manager.users (id, username, password_hash, display_name, auth_provider) "
"VALUES ('a0000000-0000-0000-0000-000000000001', 'admin', :ph, 'Admin', 'LOCAL')"
```

改为：
```python
"INSERT INTO manager.users (id, username, password_hash, display_name, auth_provider, role) "
"VALUES ('a0000000-0000-0000-0000-000000000001', 'admin', :ph, 'Admin', 'LOCAL', 'ADMIN')"
```

- [ ] **Step 3: 修改 `templates/admin_base.html` — 用 role 判断**

将第 28 行：
```html
{% if user.username == 'admin' %}
```

改为：
```html
{% if user.role.value == 'admin' %}
```

同时在侧边栏 nav 中添加其余管理入口（租户管理、API Key 管理、审计日志），替换现有的单一「用户管理」链接：

```html
{% if user.role.value == 'admin' %}
<div class="nav-section-title">管理</div>
<a href="/admin/users" class="nav-item{% if nav_active == 'users' %} active{% endif %}">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
    用户管理
</a>
<a href="/admin/tenants" class="nav-item{% if nav_active == 'tenants' %} active{% endif %}">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
    租户管理
</a>
<a href="/admin/api-keys" class="nav-item{% if nav_active == 'api_keys' %} active{% endif %}">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
    API Key 管理
</a>
<a href="/admin/audit-logs" class="nav-item{% if nav_active == 'audit_logs' %} active{% endif %}">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
    审计日志
</a>
{% endif %}
```

- [ ] **Step 4: 运行现有测试确保无回归**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add hindsight_manager/api/auth.py hindsight_manager/main.py hindsight_manager/templates/admin_base.html
git commit -m "refactor: replace hardcoded admin checks with role-based require_admin"
```

---

### Task 6: 创建 Admin API — 用户管理端点

**Files:**
- Create: `hindsight_manager/api/admin.py`
- Modify: `hindsight_manager/main.py` (注册路由)
- Test: `tests/test_admin_users.py`

- [ ] **Step 1: 写测试**

创建 `tests/test_admin_users.py`：

```python
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret")

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.models.user import User, UserRole


def _make_user(role=UserRole.USER, username="testuser"):
    u = User.__new__(User)
    u.id = uuid.uuid4()
    u.username = username
    u.display_name = "Test"
    u.role = role
    u.is_active = True
    u.email = "test@test.com"
    u.auth_provider = "local"
    return u


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def admin_client():
    admin_user = _make_user(UserRole.ADMIN, "admin")

    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    async def _override_current_user():
        return admin_user

    from hindsight_manager.auth.dependencies import get_current_user
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, mock_session
    app.dependency_overrides.clear()


@pytest.fixture
async def normal_client():
    normal_user = _make_user(UserRole.USER, "normal")

    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    async def _override_current_user():
        return normal_user

    from hindsight_manager.auth.dependencies import get_current_user
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_list_users_requires_admin(normal_client: AsyncClient):
    resp = await normal_client.get("/admin/users")
    assert resp.status_code == 403


async def test_list_users_admin_allowed(admin_client):
    client, mock_session = admin_client
    # mock 返回空列表
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    resp = await client.get("/admin/users")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_user_requires_admin(normal_client: AsyncClient):
    resp = await normal_client.post("/admin/users", json={
        "username": "newuser",
        "password": "StrongPass123!",
        "display_name": "New User",
    })
    assert resp.status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_admin_users.py -v`
Expected: FAIL — admin 路由不存在

- [ ] **Step 3: 创建 `api/admin.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.audit import log_audit
from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.auth.password import hash_password, validate_password_strength, PasswordStrengthError
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.audit_log import AuditLog
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import TenantMember
from hindsight_manager.models.user import AuthProvider, User, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Pydantic 模型 ───

class AdminUserResponse(BaseModel):
    id: str
    username: str
    email: str | None
    display_name: str
    role: str
    is_active: bool
    auth_provider: str
    created_at: str
    last_login_at: str | None


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    display_name: str
    role: UserRole = UserRole.USER


class AdminUpdateUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


# ─── 辅助函数 ───

def _admin_user_response(u: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=str(u.id),
        username=u.username,
        email=u.email,
        display_name=u.display_name,
        role=u.role.value,
        is_active=u.is_active,
        auth_provider=u.auth_provider.value,
        created_at=str(u.created_at),
        last_login_at=u.last_login_at.isoformat() if hasattr(u.last_login_at, "isoformat") else (str(u.last_login_at) if u.last_login_at else None),
    )


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─── 用户管理端点 ───

@router.get("/users")
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(User).order_by(User.created_at.desc())
    count_query = select(func.count()).select_from(User)

    if search:
        query = query.where(
            (User.username.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%"))
        )
        count_query = count_query.where(
            (User.username.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%"))
        )

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await session.execute(query)
    users = result.scalars().all()

    return PaginatedResponse(
        items=[_admin_user_response(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def admin_create_user(
    req: AdminCreateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    try:
        validate_password_strength(req.password)
    except PasswordStrengthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        email=req.email,
        display_name=req.display_name,
        auth_provider=AuthProvider.LOCAL,
        role=req.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    await log_audit(
        session, user_id=current_user.id, action="user.create",
        resource_type="user", resource_id=str(user.id),
        detail={"username": user.username, "role": user.role.value},
        ip_address=_get_client_ip(request),
    )
    await session.commit()

    return _admin_user_response(user)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def admin_update_user(
    user_id: uuid.UUID,
    req: AdminUpdateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    changes = {}
    for field, value in req.model_dump(exclude_none=True).items():
        old_val = getattr(user, field)
        if value != old_val:
            setattr(user, field, value)
            changes[field] = {"old": str(old_val), "new": str(value)}

    await session.commit()
    await session.refresh(user)

    if changes:
        await log_audit(
            session, user_id=current_user.id, action="user.update",
            resource_type="user", resource_id=str(user_id),
            detail=changes, ip_address=_get_client_ip(request),
        )
        await session.commit()

    return _admin_user_response(user)


@router.delete("/users/{user_id}")
async def admin_disable_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="不能禁用自己")

    user.is_active = not user.is_active
    await session.commit()

    action = "user.enable" if user.is_active else "user.disable"
    await log_audit(
        session, user_id=current_user.id, action=action,
        resource_type="user", resource_id=str(user_id),
        ip_address=_get_client_ip(request),
    )
    await session.commit()

    return {"ok": True, "is_active": user.is_active}


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: uuid.UUID,
    req: AdminResetPasswordRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        validate_password_strength(req.new_password)
    except PasswordStrengthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user.password_hash = hash_password(req.new_password)
    await session.commit()

    await log_audit(
        session, user_id=current_user.id, action="user.reset_password",
        resource_type="user", resource_id=str(user_id),
        ip_address=_get_client_ip(request),
    )
    await session.commit()

    return {"ok": True}
```

- [ ] **Step 4: 在 `main.py` 注册 admin 路由**

在 `hindsight_manager/main.py` 的 import 区添加：

```python
from hindsight_manager.api.admin import router as admin_router
```

在路由注册区添加（在其他 router 之后）：

```python
app.include_router(admin_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_admin_users.py -v`
Expected: PASS

同时运行全部测试确认无回归：

Run: `uv run pytest tests/ -v`

- [ ] **Step 6: 提交**

```bash
git add hindsight_manager/api/admin.py hindsight_manager/main.py tests/test_admin_users.py
git commit -m "feat: add admin user management endpoints"
```

---

### Task 7: Admin 管理页面路由

**Files:**
- Modify: `hindsight_manager/api/pages.py`

- [ ] **Step 1: 在 `pages.py` 添加管理员页面路由**

在 `hindsight_manager/api/pages.py` 末尾添加。需要先在导入区添加：

```python
from hindsight_manager.auth.dependencies import get_current_user, get_current_user_or_none, require_admin
from hindsight_manager.models.audit_log import AuditLog
from hindsight_manager.models.user import UserRole
```

注意：`get_current_user`、`get_current_user_or_none`、`User`、`AsyncSession`、`ApiKey`、`Tenant`、`TenantMember` 已有导入。

然后添加以下路由：

```python
@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_users.html", {"user": current_user, "nav_active": "users"})


@router.get("/admin/tenants", response_class=HTMLResponse)
async def admin_tenants_page(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_tenants.html", {"user": current_user, "nav_active": "tenants"})


@router.get("/admin/api-keys", response_class=HTMLResponse)
async def admin_api_keys_page(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_api_keys.html", {"user": current_user, "nav_active": "api_keys"})


@router.get("/admin/audit-logs", response_class=HTMLResponse)
async def admin_audit_logs_page(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(request, "admin_audit_logs.html", {"user": current_user, "nav_active": "audit_logs"})
```

- [ ] **Step 2: 提交**

```bash
git add hindsight_manager/api/pages.py
git commit -m "feat: add admin page routes (users, tenants, api-keys, audit-logs)"
```

---

### Task 8: Admin API — 租户管理端点

**Files:**
- Modify: `hindsight_manager/api/admin.py`

- [ ] **Step 1: 在 `admin.py` 中添加租户管理端点**

添加 Pydantic 模型：

```python
class AdminTenantResponse(BaseModel):
    id: str
    name: str
    schema_name: str
    status: str
    config: dict | None
    created_at: str
    member_count: int
    api_key_count: int


class AdminTenantCreateRequest(BaseModel):
    name: str
```

在 `admin.py` 末尾添加端点：

```python
# ─── 租户管理端点 ───

@router.get("/tenants")
async def list_tenants_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(Tenant).order_by(Tenant.created_at.desc())
    count_query = select(func.count()).select_from(Tenant)

    if search:
        query = query.where(Tenant.name.ilike(f"%{search}%"))
        count_query = count_query.where(Tenant.name.ilike(f"%{search}%"))

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    tenants = result.scalars().all()

    items = []
    for t in tenants:
        mc_result = await session.execute(
            select(func.count()).select_from(TenantMember).where(TenantMember.tenant_id == t.id)
        )
        member_count = mc_result.scalar() or 0

        kc_result = await session.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == t.id)
        )
        api_key_count = kc_result.scalar() or 0

        items.append(AdminTenantResponse(
            id=str(t.id), name=t.name, schema_name=t.schema_name,
            status=t.status.value, config=t.config, created_at=str(t.created_at),
            member_count=member_count, api_key_count=api_key_count,
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant_admin(
    tenant_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    tenant.status = TenantStatus.DELETING
    await log_audit(
        session, user_id=current_user.id, action="tenant.delete",
        resource_type="tenant", resource_id=str(tenant_id),
        detail={"name": tenant.name}, ip_address=_get_client_ip(request),
    )
    await session.commit()
    return {"ok": True}
```

需要在 admin.py 顶部添加 `TenantStatus` 的导入：

```python
from hindsight_manager.models.tenant import Tenant, TenantStatus
```

- [ ] **Step 2: 运行测试**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/api/admin.py
git commit -m "feat: add admin tenant management endpoints"
```

---

### Task 9: Admin API — API Key 管理端点

**Files:**
- Modify: `hindsight_manager/api/admin.py`

- [ ] **Step 1: 添加 API Key 管理端点**

添加 Pydantic 模型：

```python
class AdminApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_system: bool
    created_at: str
    last_used_at: str | None
    tenant_id: str
    tenant_name: str
```

在 `admin.py` 末尾添加：

```python
# ─── API Key 管理端点 ───

@router.get("/api-keys")
async def list_api_keys_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID | None = Query(None),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(ApiKey, Tenant)
        .join(Tenant, ApiKey.tenant_id == Tenant.id)
        .order_by(ApiKey.created_at.desc())
    )
    count_query = (
        select(func.count())
        .select_from(ApiKey)
        .join(Tenant, ApiKey.tenant_id == Tenant.id)
    )

    if tenant_id:
        query = query.where(ApiKey.tenant_id == tenant_id)
        count_query = count_query.where(ApiKey.tenant_id == tenant_id)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    rows = result.all()

    items = []
    for key, tenant in rows:
        def _fmt(v):
            return v.isoformat() if hasattr(v, "isoformat") else str(v) if v else None
        items.append(AdminApiKeyResponse(
            id=str(key.id), name=key.name, key_prefix=key.key_prefix,
            is_system=key.is_system, created_at=_fmt(key.created_at),
            last_used_at=_fmt(key.last_used_at),
            tenant_id=str(tenant.id), tenant_name=tenant.name,
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("/api-keys/{key_id}")
async def revoke_api_key_admin(
    key_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    await log_audit(
        session, user_id=current_user.id, action="api_key.revoke",
        resource_type="api_key", resource_id=str(key_id),
        detail={"name": api_key.name, "tenant_id": str(api_key.tenant_id)},
        ip_address=_get_client_ip(request),
    )
    await session.delete(api_key)
    await session.commit()
    return {"ok": True}
```

- [ ] **Step 2: 运行测试**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/api/admin.py
git commit -m "feat: add admin API key management endpoints"
```

---

### Task 10: Admin API — 审计日志端点

**Files:**
- Modify: `hindsight_manager/api/admin.py`

- [ ] **Step 1: 添加审计日志端点**

添加 Pydantic 模型：

```python
class AdminAuditLogResponse(BaseModel):
    id: str
    user_id: str | None
    username: str | None
    action: str
    resource_type: str
    resource_id: str
    detail: dict | None
    ip_address: str | None
    created_at: str
```

在 `admin.py` 末尾添加：

```python
# ─── 审计日志端点 ───

@router.get("/audit-logs")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(AuditLog, User).outerjoin(User, AuditLog.user_id == User.id).order_by(AuditLog.created_at.desc())
    count_query = select(func.count()).select_from(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
        count_query = count_query.where(AuditLog.resource_type == resource_type)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    rows = result.all()

    items = []
    for log, user in rows:
        def _fmt(v):
            return v.isoformat() if hasattr(v, "isoformat") else str(v) if v else None
        items.append(AdminAuditLogResponse(
            id=str(log.id), user_id=str(log.user_id) if log.user_id else None,
            username=user.username if user else None,
            action=log.action, resource_type=log.resource_type,
            resource_id=log.resource_id, detail=log.detail,
            ip_address=log.ip_address, created_at=_fmt(log.created_at),
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)
```

- [ ] **Step 2: 运行测试**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/api/admin.py
git commit -m "feat: add admin audit log endpoint"
```

---

### Task 11: 前端 — 用户管理页面

**Files:**
- Create: `hindsight_manager/templates/admin_users.html`
- Create: `hindsight_manager/static/admin.js`

- [ ] **Step 1: 创建用户管理页面模板**

创建 `hindsight_manager/templates/admin_users.html`，继承 `admin_base.html`：

```html
{% extends "admin_base.html" %}
{% block title %}用户管理 - Hindsight{% endblock %}
{% set nav_active = 'users' %}
{% block main %}
<div class="content-header">
    <h2>用户管理</h2>
    <div class="content-header-actions">
        <input type="text" id="user-search" placeholder="搜索用户名或邮箱..." class="search-input" oninput="searchUsers()">
        <button class="btn btn-primary" onclick="showCreateUserModal()">+ 创建用户</button>
    </div>
</div>

<div id="users-table-container">
    <table class="data-table">
        <thead>
            <tr>
                <th>用户名</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th>创建时间</th>
                <th>最后登录</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody id="users-tbody">
        </tbody>
    </table>
    <div id="users-pagination" class="pagination"></div>
</div>

<!-- 创建用户弹窗 -->
<div id="create-user-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideCreateUserModal()"></div>
    <div class="modal-content">
        <h3>创建用户</h3>
        <form id="create-user-form" onsubmit="createUser(event)">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" id="cu-username" required placeholder="输入用户名">
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" id="cu-password" required placeholder="输入密码（至少8位，含大小写和数字）">
            </div>
            <div class="form-group">
                <label>显示名</label>
                <input type="text" id="cu-display-name" required placeholder="输入显示名">
            </div>
            <div class="form-group">
                <label>邮箱（可选）</label>
                <input type="email" id="cu-email" placeholder="输入邮箱">
            </div>
            <div class="form-group">
                <label>角色</label>
                <select id="cu-role">
                    <option value="user">普通用户</option>
                    <option value="admin">管理员</option>
                </select>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="hideCreateUserModal()">取消</button>
                <button type="submit" class="btn btn-primary">创建</button>
            </div>
        </form>
    </div>
</div>

<!-- 编辑用户弹窗 -->
<div id="edit-user-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideEditUserModal()"></div>
    <div class="modal-content">
        <h3>编辑用户</h3>
        <form id="edit-user-form" onsubmit="updateUser(event)">
            <input type="hidden" id="eu-id">
            <div class="form-group">
                <label>显示名</label>
                <input type="text" id="eu-display-name" required>
            </div>
            <div class="form-group">
                <label>邮箱</label>
                <input type="email" id="eu-email">
            </div>
            <div class="form-group">
                <label>角色</label>
                <select id="eu-role">
                    <option value="user">普通用户</option>
                    <option value="admin">管理员</option>
                </select>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="hideEditUserModal()">取消</button>
                <button type="submit" class="btn btn-primary">保存</button>
            </div>
        </form>
    </div>
</div>

<!-- 重置密码弹窗 -->
<div id="reset-password-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideResetPasswordModal()"></div>
    <div class="modal-content">
        <h3>重置密码</h3>
        <form id="reset-password-form" onsubmit="resetPassword(event)">
            <input type="hidden" id="rp-id">
            <div class="form-group">
                <label>新密码</label>
                <input type="password" id="rp-password" required placeholder="输入新密码">
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="hideResetPasswordModal()">取消</button>
                <button type="submit" class="btn btn-primary">重置</button>
            </div>
        </form>
    </div>
</div>

<script src="/static/admin.js"></script>
<script>
document.addEventListener("DOMContentLoaded", () => loadUsers());
</script>
{% endblock %}
```

- [ ] **Step 2: 创建管理后台 JS**

创建 `hindsight_manager/static/admin.js`：

```javascript
// ─── 通用工具 ───

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(isoStr) {
  if (!isoStr) return "-";
  const d = new Date(isoStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, { credentials: "include", ...options });
  if (resp.status === 403) {
    alert("无权限访问");
    window.location.href = "/dashboard";
    return null;
  }
  return resp;
}

function renderPagination(containerId, total, page, pageSize, onPageChange) {
  const container = document.getElementById(containerId);
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) {
    container.innerHTML = "";
    return;
  }
  let html = '<div class="pagination-info">共 ' + total + ' 条</div><div class="pagination-btns">';
  if (page > 1) html += '<button class="btn btn-ghost btn-sm" onclick="' + onPageChange + '(' + (page - 1) + ')">上一页</button>';
  html += '<span class="pagination-current">' + page + ' / ' + totalPages + '</span>';
  if (page < totalPages) html += '<button class="btn btn-ghost btn-sm" onclick="' + onPageChange + '(' + (page + 1) + ')">下一页</button>';
  html += '</div>';
  container.innerHTML = html;
}

// ─── 用户管理 ───

let _userPage = 1;
let _userSearch = "";

async function loadUsers(page = 1) {
  _userPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  if (_userSearch) params.set("search", _userSearch);

  const resp = await apiFetch(`/admin/users?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("users-tbody");
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(u => `
      <tr>
        <td>${escapeHtml(u.username)}</td>
        <td>${escapeHtml(u.email || "-")}</td>
        <td><span class="badge ${u.role === 'admin' ? 'badge-system' : 'badge-default'}">${u.role === 'admin' ? '管理员' : '用户'}</span></td>
        <td><span class="badge ${u.is_active ? 'badge-success' : 'badge-danger'}">${u.is_active ? '启用' : '禁用'}</span></td>
        <td>${formatDate(u.created_at)}</td>
        <td>${formatDate(u.last_login_at)}</td>
        <td class="action-cell">
          <button class="btn btn-ghost btn-sm" onclick="showEditUserModal('${u.id}','${escapeHtml(u.display_name)}','${escapeHtml(u.email || '')}','${u.role}')">编辑</button>
          <button class="btn btn-ghost btn-sm" onclick="showResetPasswordModal('${u.id}')">重置密码</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleUserActive('${u.id}', ${u.is_active})">${u.is_active ? '禁用' : '启用'}</button>
        </td>
      </tr>
    `).join("");
  }

  renderPagination("users-pagination", data.total, data.page, data.page_size, "loadUsers");
}

function searchUsers() {
  _userSearch = document.getElementById("user-search").value.trim();
  loadUsers(1);
}

function showCreateUserModal() {
  document.getElementById("create-user-form").reset();
  document.getElementById("create-user-modal").classList.remove("hidden");
}

function hideCreateUserModal() {
  document.getElementById("create-user-modal").classList.add("hidden");
}

async function createUser(e) {
  e.preventDefault();
  const resp = await apiFetch("/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: document.getElementById("cu-username").value,
      password: document.getElementById("cu-password").value,
      display_name: document.getElementById("cu-display-name").value,
      email: document.getElementById("cu-email").value || null,
      role: document.getElementById("cu-role").value,
    }),
  });
  if (!resp) return;
  if (resp.ok) {
    hideCreateUserModal();
    loadUsers();
  } else {
    const err = await resp.json();
    alert(err.detail || "创建失败");
  }
}

function showEditUserModal(id, displayName, email, role) {
  document.getElementById("eu-id").value = id;
  document.getElementById("eu-display-name").value = displayName;
  document.getElementById("eu-email").value = email;
  document.getElementById("eu-role").value = role;
  document.getElementById("edit-user-modal").classList.remove("hidden");
}

function hideEditUserModal() {
  document.getElementById("edit-user-modal").classList.add("hidden");
}

async function updateUser(e) {
  e.preventDefault();
  const id = document.getElementById("eu-id").value;
  const resp = await apiFetch(`/admin/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      display_name: document.getElementById("eu-display-name").value,
      email: document.getElementById("eu-email").value || null,
      role: document.getElementById("eu-role").value,
    }),
  });
  if (!resp) return;
  if (resp.ok) {
    hideEditUserModal();
    loadUsers(_userPage);
  } else {
    const err = await resp.json();
    alert(err.detail || "更新失败");
  }
}

function showResetPasswordModal(id) {
  document.getElementById("rp-id").value = id;
  document.getElementById("rp-password").value = "";
  document.getElementById("reset-password-modal").classList.remove("hidden");
}

function hideResetPasswordModal() {
  document.getElementById("reset-password-modal").classList.add("hidden");
}

async function resetPassword(e) {
  e.preventDefault();
  const id = document.getElementById("rp-id").value;
  const resp = await apiFetch(`/admin/users/${id}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_password: document.getElementById("rp-password").value }),
  });
  if (!resp) return;
  if (resp.ok) {
    alert("密码重置成功");
    hideResetPasswordModal();
  } else {
    const err = await resp.json();
    alert(err.detail || "重置失败");
  }
}

async function toggleUserActive(id, isActive) {
  const action = isActive ? "禁用" : "启用";
  if (!confirm(`确定${action}该用户吗？`)) return;
  const resp = await apiFetch(`/admin/users/${id}`, { method: "DELETE" });
  if (!resp) return;
  if (resp.ok) {
    loadUsers(_userPage);
  } else {
    const err = await resp.json();
    alert(err.detail || "操作失败");
  }
}

// ─── 租户管理 ───

let _tenantPage = 1;
let _tenantSearch = "";

async function loadTenants(page = 1) {
  _tenantPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  if (_tenantSearch) params.set("search", _tenantSearch);

  const resp = await apiFetch(`/admin/tenants?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("tenants-tbody");
  if (!tbody) return;
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(t => `
      <tr>
        <td>${escapeHtml(t.name)}</td>
        <td><code>${escapeHtml(t.schema_name)}</code></td>
        <td><span class="badge ${t.status === 'active' ? 'badge-success' : 'badge-danger'}">${t.status}</span></td>
        <td>${t.member_count}</td>
        <td>${t.api_key_count}</td>
        <td>${formatDate(t.created_at)}</td>
        <td class="action-cell">
          <button class="btn btn-danger btn-sm" onclick="deleteTenantAdmin('${t.id}','${escapeHtml(t.name)}')">删除</button>
        </td>
      </tr>
    `).join("");
  }

  renderPagination("tenants-pagination", data.total, data.page, data.page_size, "loadTenants");
}

function searchTenants() {
  _tenantSearch = document.getElementById("tenant-search").value.trim();
  loadTenants(1);
}

async function deleteTenantAdmin(id, name) {
  if (!confirm(`确定删除租户 "${name}" 吗？此操作不可撤销。`)) return;
  const resp = await apiFetch(`/admin/tenants/${id}`, { method: "DELETE" });
  if (!resp) return;
  if (resp.ok) {
    loadTenants(_tenantPage);
  } else {
    alert("删除失败");
  }
}

// ─── API Key 管理 ───

let _apiKeyPage = 1;

async function loadApiKeys(page = 1) {
  _apiKeyPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  const tenantFilter = document.getElementById("ak-tenant-filter");
  if (tenantFilter && tenantFilter.value) params.set("tenant_id", tenantFilter.value);

  const resp = await apiFetch(`/admin/api-keys?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("apikeys-tbody");
  if (!tbody) return;
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(k => `
      <tr>
        <td>${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}</td>
        <td><code>${escapeHtml(k.key_prefix)}...</code></td>
        <td>${escapeHtml(k.tenant_name)}</td>
        <td>${formatDate(k.created_at)}</td>
        <td>${formatDate(k.last_used_at)}</td>
        <td class="action-cell">
          <button class="btn btn-danger btn-sm" onclick="revokeApiKeyAdmin('${k.id}')">撤销</button>
        </td>
      </tr>
    `).join("");
  }

  renderPagination("apikeys-pagination", data.total, data.page, data.page_size, "loadApiKeys");
}

async function revokeApiKeyAdmin(id) {
  if (!confirm("确定撤销此 API Key 吗？使用该 Key 的应用将无法访问。")) return;
  const resp = await apiFetch(`/admin/api-keys/${id}`, { method: "DELETE" });
  if (!resp) return;
  if (resp.ok) {
    loadApiKeys(_apiKeyPage);
  } else {
    alert("撤销失败");
  }
}

// ─── 审计日志 ───

let _auditPage = 1;

async function loadAuditLogs(page = 1) {
  _auditPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  const actionFilter = document.getElementById("al-action-filter");
  if (actionFilter && actionFilter.value) params.set("action", actionFilter.value);

  const resp = await apiFetch(`/admin/audit-logs?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("audit-tbody");
  if (!tbody) return;
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(l => `
      <tr>
        <td>${formatDate(l.created_at)}</td>
        <td>${escapeHtml(l.username || "-")}</td>
        <td><code>${escapeHtml(l.action)}</code></td>
        <td>${escapeHtml(l.resource_type)}</td>
        <td><code>${escapeHtml(l.resource_id).substring(0, 8)}...</code></td>
        <td>${escapeHtml(l.ip_address || "-")}</td>
        <td>${l.detail ? `<button class="btn btn-ghost btn-sm" onclick="alert(JSON.stringify(${JSON.stringify(l.detail)}, null, 2))">查看</button>` : "-"}</td>
      </tr>
    `).join("");
  }

  renderPagination("audit-pagination", data.total, data.page, data.page_size, "loadAuditLogs");
}
```

- [ ] **Step 3: 提交**

```bash
git add hindsight_manager/templates/admin_users.html hindsight_manager/static/admin.js
git commit -m "feat: add admin user management page and shared admin JS"
```

---

### Task 12: 前端 — 租户管理、API Key 管理、审计日志页面

**Files:**
- Create: `hindsight_manager/templates/admin_tenants.html`
- Create: `hindsight_manager/templates/admin_api_keys.html`
- Create: `hindsight_manager/templates/admin_audit_logs.html`

- [ ] **Step 1: 创建租户管理页面**

创建 `hindsight_manager/templates/admin_tenants.html`：

```html
{% extends "admin_base.html" %}
{% block title %}租户管理 - Hindsight{% endblock %}
{% set nav_active = 'tenants' %}
{% block main %}
<div class="content-header">
    <h2>租户管理</h2>
    <div class="content-header-actions">
        <input type="text" id="tenant-search" placeholder="搜索租户名..." class="search-input" oninput="searchTenants()">
    </div>
</div>

<div id="tenants-table-container">
    <table class="data-table">
        <thead>
            <tr>
                <th>名称</th>
                <th>Schema</th>
                <th>状态</th>
                <th>成员数</th>
                <th>API Key 数</th>
                <th>创建时间</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody id="tenants-tbody">
        </tbody>
    </table>
    <div id="tenants-pagination" class="pagination"></div>
</div>

<script src="/static/admin.js"></script>
<script>
document.addEventListener("DOMContentLoaded", () => loadTenants());
</script>
{% endblock %}
```

- [ ] **Step 2: 创建 API Key 管理页面**

创建 `hindsight_manager/templates/admin_api_keys.html`：

```html
{% extends "admin_base.html" %}
{% block title %}API Key 管理 - Hindsight{% endblock %}
{% set nav_active = 'api_keys' %}
{% block main %}
<div class="content-header">
    <h2>API Key 管理</h2>
</div>

<div class="filter-bar">
    <select id="ak-tenant-filter" onchange="loadApiKeys(1)">
        <option value="">全部租户</option>
    </select>
</div>

<div id="apikeys-table-container">
    <table class="data-table">
        <thead>
            <tr>
                <th>名称</th>
                <th>前缀</th>
                <th>所属租户</th>
                <th>创建时间</th>
                <th>最后使用</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody id="apikeys-tbody">
        </tbody>
    </table>
    <div id="apikeys-pagination" class="pagination"></div>
</div>

<script src="/static/admin.js"></script>
<script>
document.addEventListener("DOMContentLoaded", () => {
  loadApiKeys();
  // 加载租户列表填充筛选下拉框
  apiFetch("/admin/tenants?page_size=100").then(r => r && r.json()).then(data => {
    if (!data) return;
    const sel = document.getElementById("ak-tenant-filter");
    data.items.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.name;
      sel.appendChild(opt);
    });
  });
});
</script>
{% endblock %}
```

- [ ] **Step 3: 创建审计日志页面**

创建 `hindsight_manager/templates/admin_audit_logs.html`：

```html
{% extends "admin_base.html" %}
{% block title %}审计日志 - Hindsight{% endblock %}
{% set nav_active = 'audit_logs' %}
{% block main %}
<div class="content-header">
    <h2>审计日志</h2>
</div>

<div class="filter-bar">
    <select id="al-action-filter" onchange="loadAuditLogs(1)">
        <option value="">全部操作</option>
        <option value="user.create">创建用户</option>
        <option value="user.update">编辑用户</option>
        <option value="user.disable">禁用用户</option>
        <option value="user.enable">启用用户</option>
        <option value="user.reset_password">重置密码</option>
        <option value="tenant.delete">删除租户</option>
        <option value="api_key.revoke">撤销 API Key</option>
    </select>
</div>

<div id="audit-table-container">
    <table class="data-table">
        <thead>
            <tr>
                <th>时间</th>
                <th>操作者</th>
                <th>操作</th>
                <th>资源类型</th>
                <th>资源 ID</th>
                <th>IP</th>
                <th>详情</th>
            </tr>
        </thead>
        <tbody id="audit-tbody">
        </tbody>
    </table>
    <div id="audit-pagination" class="pagination"></div>
</div>

<script src="/static/admin.js"></script>
<script>
document.addEventListener("DOMContentLoaded", () => loadAuditLogs());
</script>
{% endblock %}
```

- [ ] **Step 4: 提交**

```bash
git add hindsight_manager/templates/admin_tenants.html hindsight_manager/templates/admin_api_keys.html hindsight_manager/templates/admin_audit_logs.html
git commit -m "feat: add admin tenants, api-keys, and audit-logs pages"
```

---

### Task 13: 添加管理页面样式

**Files:**
- Modify: `hindsight_manager/static/style.css`

- [ ] **Step 1: 添加管理页面所需 CSS 样式**

在 `hindsight_manager/static/style.css` 末尾追加：

```css
/* ─── 管理后台通用 ─── */

.content-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.content-header h2 {
    margin: 0;
    font-size: 20px;
}

.content-header-actions {
    display: flex;
    gap: 12px;
    align-items: center;
}

.search-input {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 14px;
    width: 240px;
}

.filter-bar {
    margin-bottom: 16px;
}

.filter-bar select {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 14px;
}

/* ─── 数据表格 ─── */

.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}

.data-table th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid var(--border);
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.data-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
}

.data-table tr:hover td {
    background: var(--bg-hover);
}

.data-table .empty-cell {
    text-align: center;
    color: var(--text-secondary);
    padding: 40px 12px;
}

.action-cell {
    white-space: nowrap;
}

/* ─── 徽章 ─── */

.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 500;
}

.badge-default {
    background: var(--bg-secondary);
    color: var(--text-secondary);
}

.badge-success {
    background: #dcfce7;
    color: #166534;
}

.badge-danger {
    background: #fee2e2;
    color: #991b1b;
}

/* ─── 分页 ─── */

.pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 16px;
    padding: 8px 0;
}

.pagination-info {
    color: var(--text-secondary);
    font-size: 13px;
}

.pagination-btns {
    display: flex;
    align-items: center;
    gap: 8px;
}

.pagination-current {
    font-size: 14px;
    color: var(--text-secondary);
}

/* ─── 导航分区标题 ─── */

.nav-section-title {
    padding: 16px 20px 6px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
}
```

- [ ] **Step 2: 提交**

```bash
git add hindsight_manager/static/style.css
git commit -m "style: add admin panel CSS styles (tables, badges, pagination)"
```

---

### Task 14: 运行完整测试并最终验证

**Files:** 无新文件

- [ ] **Step 1: 运行全部测试**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: 检查所有文件已提交**

Run: `git status`
Expected: 无未提交文件

- [ ] **Step 3: 检查完整提交历史**

Run: `git log --oneline -10`
Expected: 看到从 Task 1 到 Task 13 的所有提交
