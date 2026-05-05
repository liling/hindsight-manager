# Hindsight Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone tenant management service (hindsight-manager) with CAS/local auth, tenant CRUD, API key management, and a corresponding TenantExtension for hindsight-api.

**Architecture:** Two components — (1) a FastAPI service at `../hindsight-manager` storing metadata in a `manager` PostgreSQL schema, (2) a `ManagerTenantExtension` in hindsight-api-slim that reads that metadata to authenticate API keys and resolve per-tenant config. Schema provisioning happens lazily in hindsight-api on first access.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async + asyncpg, Alembic, Typer (CLI), passlib[bcrypt], python-jose (JWT), python-cas, uv

---

## Phase 1: Project Scaffolding & Database

### Task 1: Scaffold the project

**Files:**
- Create: `../hindsight-manager/pyproject.toml`
- Create: `../hindsight-manager/hindsight_manager/__init__.py`
- Create: `../hindsight-manager/hindsight_manager/config.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "hindsight-manager"
version = "0.1.0"
description = "Tenant management service for Hindsight"
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]>=0.120.3",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "typer>=0.15.0",
    "passlib[bcrypt]>=1.7.4",
    "python-jose[cryptography]>=3.3.0",
    "python-cas>=1.6.0",
    "httpx>=0.27.0",
    "pydantic-settings>=2.7.0",
]

[project.scripts]
hindsight-manager = "hindsight_manager.cli.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["hindsight_manager"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "manager"
    auth_provider: str = "local"
    cas_server_url: str | None = None
    cas_service_url: str | None = None
    jwt_secret: str
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {"env_prefix": "HINDSIGHT_MANAGER_"}
```

- [ ] **Step 3: Create __init__.py**

```python
```

- [ ] **Step 4: Initialize the project**

```bash
cd ../hindsight-manager && uv sync
```

- [ ] **Step 5: Commit**

```bash
git init && git add -A && git commit -m "chore: scaffold hindsight-manager project"
```

### Task 2: Database setup and ORM models

**Files:**
- Create: `../hindsight-manager/hindsight_manager/db.py`
- Create: `../hindsight-manager/hindsight_manager/models/__init__.py`
- Create: `../hindsight-manager/hindsight_manager/models/user.py`
- Create: `../hindsight-manager/hindsight_manager/models/tenant.py`
- Create: `../hindsight-manager/hindsight_manager/models/tenant_member.py`
- Create: `../hindsight-manager/hindsight_manager/models/api_key.py`
- Create: `../hindsight-manager/hindsight_manager/models/base.py`

- [ ] **Step 1: Create db.py — async engine and session**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hindsight_manager.config import Settings

_engine = None
_session_factory = None


def init_db(settings: Settings) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def get_engine():
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        yield session
```

- [ ] **Step 2: Create models/base.py — declarative base with schema support**

```python
import uuid

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="manager")


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(server_default="now()")
```

Note: the `manager` schema here is a default; we'll make it configurable via an Alembic env.py that reads `Settings.manager_schema`. The ORM models themselves use a fixed `schema="manager"` for clarity — the actual schema name is overridden in Alembic migrations.

- [ ] **Step 3: Create models/user.py**

```python
import enum
import uuid

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class AuthProvider(str, enum.Enum):
    LOCAL = "local"
    CAS = "cas"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, name="auth_provider"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(server_default="now()")

    memberships: Mapped[list["TenantMember"]] = relationship(back_populates="user")
```

- [ ] **Step 4: Create models/tenant.py**

```python
import enum
import uuid

from sqlalchemy import Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETING = "deleting"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status"), nullable=False, default=TenantStatus.ACTIVE
    )
    created_at: Mapped[str] = mapped_column(server_default="now()")

    members: Mapped[list["TenantMember"]] = relationship(back_populates="tenant")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="tenant")
```

- [ ] **Step 5: Create models/tenant_member.py**

```python
import enum
import uuid

from sqlalchemy import Enum, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class MemberRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class TenantMember(Base):
    __tablename__ = "tenant_members"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "tenant_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role"), nullable=False, default=MemberRole.MEMBER
    )
    created_at: Mapped[str] = mapped_column(server_default="now()")

    user: Mapped["User"] = relationship(back_populates="memberships")
    tenant: Mapped["Tenant"] = relationship(back_populates="members")
```

- [ ] **Step 6: Create models/api_key.py**

```python
import uuid

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[str] = mapped_column(server_default="now()")
    last_used_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")
```

- [ ] **Step 7: Create models/__init__.py — re-export all models**

```python
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import AuthProvider, User

__all__ = [
    "ApiKey",
    "AuthProvider",
    "MemberRole",
    "Tenant",
    "TenantMember",
    "TenantStatus",
    "User",
]
```

- [ ] **Step 8: Verify imports work**

```bash
cd ../hindsight-manager && uv run python -c "from hindsight_manager.models import User, Tenant; print('OK')"
```

Expected: `OK`

- [ ] **Step 9: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add ORM models for users, tenants, members, api_keys"
```

### Task 3: Alembic migrations for metadata tables

**Files:**
- Create: `../hindsight-manager/hindsight_manager/migrations/env.py`
- Create: `../hindsight-manager/hindsight_manager/migrations/script.py.mako`
- Create: `../hindsight-manager/hindsight_manager/migrations/versions/001_initial_schema.py`
- Create: `../hindsight-manager/alembic.ini`

- [ ] **Step 1: Create alembic.ini**

```ini
[alembic]
script_location = hindsight_manager/migrations
sqlalchemy.url = postgresql+asyncpg://localhost/hindsight_dev
```

Note: the actual URL is overridden by `env.py` at runtime via `DATABASE_URL`.

- [ ] **Step 2: Create migrations/env.py**

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from hindsight_manager.config import Settings
from hindsight_manager.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = settings.database_url.replace("+asyncpg", "+psycopg2")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": settings.database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create migrations/script.py.mako**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create initial migration**

```python
"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-06
"""
import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

# Schema name for all tables
SCHEMA = "manager"


def _schema(table: str) -> str:
    return f"{SCHEMA}.{table}"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        _schema("users"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "auth_provider",
            sa.Enum("local", "cas", name="auth_provider", create_type=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_table(
        _schema("tenants"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), unique=True, nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "deleting", name="tenant_status", create_type=True),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_table(
        _schema("tenant_members"),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id"), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "member", name="member_role", create_type=True),
            nullable=False,
            server_default="member",
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
        schema=SCHEMA,
    )

    op.create_table(
        _schema("api_keys"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id"), nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table(_schema("api_keys"), schema=SCHEMA)
    op.drop_table(_schema("tenant_members"), schema=SCHEMA)
    op.drop_table(_schema("tenants"), schema=SCHEMA)
    op.drop_table(_schema("users"), schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
```

- [ ] **Step 5: Verify migration runs**

```bash
cd ../hindsight-manager && HINDSIGHT_MANAGER_DATABASE_URL="postgresql+asyncpg://..." uv run alembic -c alembic.ini upgrade head
```

Expected: tables created in `manager` schema.

- [ ] **Step 6: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add Alembic migration for manager metadata schema"
```

---

## Phase 2: Authentication

### Task 4: Session management (JWT)

**Files:**
- Create: `../hindsight-manager/hindsight_manager/auth/__init__.py`
- Create: `../hindsight-manager/hindsight_manager/auth/session.py`
- Create: `../hindsight-manager/tests/conftest.py`
- Create: `../hindsight-manager/tests/test_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session.py
from hindsight_manager.auth.session import create_token, decode_token


def test_create_and_decode_token():
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    username = "alice"
    token = create_token(user_id, username, secret="test-secret")
    payload = decode_token(token, secret="test-secret")
    assert payload["sub"] == user_id
    assert payload["username"] == username


def test_decode_invalid_token():
    from datetime import timedelta

    token = create_token("u1", "alice", secret="test-secret", expires_delta=timedelta(seconds=-1))
    assert decode_token(token, secret="test-secret") is None


def test_decode_wrong_secret():
    token = create_token("u1", "alice", secret="secret-a")
    assert decode_token(token, secret="secret-b") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ../hindsight-manager && uv run pytest tests/test_session.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: Write auth/session.py**

```python
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

TOKEN_EXPIRE_HOURS = 24


def create_token(
    user_id: str,
    username: str,
    secret: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=TOKEN_EXPIRE_HOURS))
    return jwt.encode(
        {"sub": user_id, "username": username, "exp": expire},
        secret,
        algorithm="HS256",
    )


def decode_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../hindsight-manager && uv run pytest tests/test_session.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add JWT session token creation and validation"
```

### Task 5: Local authentication

**Files:**
- Create: `../hindsight-manager/hindsight_manager/auth/local.py`
- Create: `../hindsight-manager/tests/test_local_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_local_auth.py
from hindsight_manager.auth.local import hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed) is True
    assert verify_password("wrong", hashed) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ../hindsight-manager && uv run pytest tests/test_local_auth.py -v
```

Expected: FAIL

- [ ] **Step 3: Write auth/local.py**

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../hindsight-manager && uv run pytest tests/test_local_auth.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add local password hashing and verification"
```

### Task 6: CAS authentication

**Files:**
- Create: `../hindsight-manager/hindsight_manager/auth/cas.py`
- Create: `../hindsight-manager/tests/test_cas_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cas_auth.py
from unittest.mock import AsyncMock, patch

from hindsight_manager.auth.cas import CASAuth, CASClient


def test_get_login_url():
    client = CASClient(server_url="https://cas.example.com", service_url="https://manager.example.com/auth/cas/callback")
    url = client.get_login_url()
    assert "cas.example.com" in url
    assert "service=" in url


async def test_validate_ticket_success():
    client = CASClient(server_url="https://cas.example.com", service_url="https://manager.example.com/auth/cas/callback")
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = """<cas:serviceResponse xmlns:cas='http://www.yale.edu/tp/cas'>
        <cas:authenticationSuccess>
            <cas:user>alice</cas:user>
        </cas:authenticationSuccess>
    </cas:serviceResponse>"""

    with patch("hindsight_manager.auth.cas.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client
        username = await client.validate_ticket("ST-12345")
        assert username == "alice"


async def test_validate_ticket_failure():
    client = CASClient(server_url="https://cas.example.com", service_url="https://manager.example.com/auth/cas/callback")
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = """<cas:serviceResponse xmlns:cas='http://www.yale.edu/tp/cas'>
        <cas:authenticationFailure code='INVALID_TICKET'>
            Ticket not recognized
        </cas:authenticationFailure>
    </cas:serviceResponse>"""

    with patch("hindsight_manager.auth.cas.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client
        username = await client.validate_ticket("ST-bad")
        assert username is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ../hindsight-manager && uv run pytest tests/test_cas_auth.py -v
```

Expected: FAIL

- [ ] **Step 3: Write auth/cas.py**

```python
import re
from urllib.parse import urlencode

import httpx

from hindsight_manager.auth.session import create_token


class CASClient:
    def __init__(self, server_url: str, service_url: str):
        self.server_url = server_url.rstrip("/")
        self.service_url = service_url

    def get_login_url(self) -> str:
        return f"{self.server_url}/login?{urlencode({'service': self.service_url})}"

    async def validate_ticket(self, ticket: str) -> str | None:
        validate_url = f"{self.server_url}/serviceValidate?{urlencode({'ticket': ticket, 'service': self.service_url})}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(validate_url)
            if resp.status_code != 200:
                return None
            match = re.search(r"<cas:user>(.*?)</cas:user>", resp.text)
            if match:
                return match.group(1)
            return None


class CASAuth:
    def __init__(self, cas_client: CASClient, jwt_secret: str):
        self.cas_client = cas_client
        self.jwt_secret = jwt_secret

    async def authenticate(self, ticket: str) -> dict | None:
        username = await self.cas_client.validate_ticket(ticket)
        if not username:
            return None
        token = create_token(user_id=username, username=username, secret=self.jwt_secret)
        return {"token": token, "username": username}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../hindsight-manager && uv run pytest tests/test_cas_auth.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add CAS authentication client and ticket validation"
```

### Task 7: Auth dependency (FastAPI)

**Files:**
- Create: `../hindsight-manager/hindsight_manager/auth/dependencies.py`

- [ ] **Step 1: Write auth/dependencies.py — session-based auth dependency**

```python
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.session import decode_token
from hindsight_manager.db import get_session
from hindsight_manager.models.user import User

SESSION_COOKIE = "hindsight_session"


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    settings = __import__("hindsight_manager.config", fromlist=["Settings"]).Settings()
    payload = decode_token(token, settings.jwt_secret)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    result = await session.execute(select(User).where(User.username == payload["username"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
```

- [ ] **Step 2: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add FastAPI auth dependency for session-based user lookup"
```

### Task 8: Auth API endpoints

**Files:**
- Create: `../hindsight-manager/hindsight_manager/api/__init__.py`
- Create: `../hindsight-manager/hindsight_manager/api/auth.py`
- Modify: `../hindsight-manager/hindsight_manager/main.py` (create if not exists)

- [ ] **Step 1: Write api/auth.py**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.cas import CASAuth, CASClient
from hindsight_manager.auth.dependencies import SESSION_COOKIE, get_current_user
from hindsight_manager.auth.local import hash_password, verify_password
from hindsight_manager.auth.session import create_token, decode_token
from hindsight_manager.config import Settings
from hindsight_manager.db import get_session
from hindsight_manager.models.user import AuthProvider, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    provider: str
    username: str | None = None
    password: str | None = None
    ticket: str | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    auth_provider: str


@router.post("/login")
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    settings = Settings()

    if req.provider == "local":
        if not req.username or not req.password:
            raise HTTPException(status_code=400, detail="username and password required")
        result = await session.execute(select(User).where(User.username == req.username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(req.password, user.password_hash or ""):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_token(str(user.id), user.username, settings.jwt_secret)
        response = {"token": token, "user": UserResponse(id=str(user.id), username=user.username, display_name=user.display_name, auth_provider=user.auth_provider.value)}
        resp = Response()
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=86400, path="/")
        resp.status_code = 200
        # Use JSONResponse pattern with cookie
        from fastapi.responses import JSONResponse
        resp = JSONResponse(content=response)
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=86400, path="/")
        return resp

    if req.provider == "cas":
        if not req.ticket:
            raise HTTPException(status_code=400, detail="ticket required")
        if not settings.cas_server_url or not settings.cas_service_url:
            raise HTTPException(status_code=500, detail="CAS not configured")
        cas_client = CASClient(settings.cas_server_url, settings.cas_service_url)
        cas_auth = CASAuth(cas_client, settings.jwt_secret)
        result = await cas_auth.authenticate(req.ticket)
        if not result:
            raise HTTPException(status_code=401, detail="CAS authentication failed")
        username = result["username"]
        # Auto-create user on first CAS login
        db_result = await session.execute(select(User).where(User.username == username))
        user = db_result.scalar_one_or_none()
        if not user:
            user = User(username=username, display_name=username, auth_provider=AuthProvider.CAS)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        resp_data = {"token": result["token"], "user": UserResponse(id=str(user.id), username=user.username, display_name=user.display_name, auth_provider=user.auth_provider.value)}
        from fastapi.responses import JSONResponse
        resp = JSONResponse(content=resp_data)
        resp.set_cookie(SESSION_COOKIE, result["token"], httponly=True, max_age=86400, path="/")
        return resp

    raise HTTPException(status_code=400, detail=f"Unsupported provider: {req.provider}")


@router.get("/cas/login")
async def cas_login(request: Request):
    settings = Settings()
    if not settings.cas_server_url or not settings.cas_service_url:
        raise HTTPException(status_code=500, detail="CAS not configured")
    cas_client = CASClient(settings.cas_server_url, settings.cas_service_url)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=cas_client.get_login_url())


@router.get("/cas/callback")
async def cas_callback(ticket: str, session: AsyncSession = Depends(get_session)):
    settings = Settings()
    cas_client = CASClient(settings.cas_server_url, settings.cas_service_url)
    cas_auth = CASAuth(cas_client, settings.jwt_secret)
    result = await cas_auth.authenticate(ticket)
    if not result:
        raise HTTPException(status_code=401, detail="CAS authentication failed")
    username = result["username"]
    db_result = await session.execute(select(User).where(User.username == username))
    user = db_result.scalar_one_or_none()
    if not user:
        user = User(username=username, display_name=username, auth_provider=AuthProvider.CAS)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content={"user": UserResponse(id=str(user.id), username=user.username, display_name=user.display_name, auth_provider=user.auth_provider.value)})
    resp.set_cookie(SESSION_COOKIE, result["token"], httponly=True, max_age=86400, path="/")
    return resp


@router.post("/logout")
async def logout():
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse(id=str(current_user.id), username=current_user.username, display_name=current_user.display_name, auth_provider=current_user.auth_provider.value)
```

- [ ] **Step 2: Create main.py — FastAPI app entry point**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.config import Settings
from hindsight_manager.db import init_db

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings)
    yield


app = FastAPI(title="Hindsight Manager", lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: Verify the app starts**

```bash
cd ../hindsight-manager && HINDSIGHT_MANAGER_DATABASE_URL="..." HINDSIGHT_MANAGER_JWT_SECRET="test" uv run uvicorn hindsight_manager.main:app --port 8001 &
sleep 2
curl -s http://localhost:8001/health
kill %1
```

Expected: `{"status": "ok"}`

- [ ] **Step 4: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add auth API endpoints (login, logout, CAS, me)"
```

---

## Phase 3: Tenant CRUD & Members

### Task 9: Tenant CRUD endpoints

**Files:**
- Create: `../hindsight-manager/hindsight_manager/api/tenants.py`
- Create: `../hindsight-manager/tests/test_tenant_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tenant_api.py
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_user():
    return type("User", (), {
        "id": uuid.uuid4(),
        "username": "alice",
        "display_name": "Alice",
        "auth_provider": type("P", (), {"value": "local"})(),
    })()


@pytest.fixture
def auth_headers():
    from hindsight_manager.auth.session import create_token
    token = create_token(str(uuid.uuid4()), "alice", secret="test-secret")
    return {"Cookie": f"hindsight_session={token}"}


async def test_list_tenants_empty(auth_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/tenants", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []
```

- [ ] **Step 2: Write api/tenants.py**

```python
import secrets
import uuid
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    name: str


class TenantConfigUpdateRequest(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embeddings_provider: str | None = None
    embeddings_model: str | None = None
    embeddings_api_key: str | None = None
    embeddings_base_url: str | None = None
    reranker_provider: str | None = None
    reranker_model: str | None = None
    reranker_api_key: str | None = None


class TenantResponse(BaseModel):
    id: str
    name: str
    schema_name: str
    config: dict | None
    status: str
    created_at: str


class MemberResponse(BaseModel):
    user_id: str
    username: str
    role: str


def _require_membership(session: AsyncSession, user: User, tenant_id: uuid.UUID, require_owner: bool = False) -> tuple[TenantMember, Tenant]:
    result = await session.execute(
        select(TenantMember, Tenant)
        .join(Tenant, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id, TenantMember.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found or you are not a member")
    membership, tenant = row
    if require_owner and membership.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")
    return membership, tenant


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant, TenantMember.role)
        .join(TenantMember, Tenant.id == TenantMember.tenant_id)
        .where(TenantMember.user_id == current_user.id)
    )
    return [
        TenantResponse(
            id=str(t.id),
            name=t.name,
            schema_name=t.schema_name,
            config=t.config,
            status=t.status.value,
            created_at=str(t.created_at),
        )
        for t, role in result.all()
    ]


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    req: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    schema_name = f"tenant_{uuid.uuid4().hex[:8]}"
    tenant = Tenant(name=req.name, schema_name=schema_name, status=TenantStatus.ACTIVE)
    session.add(tenant)
    await session.flush()

    membership = TenantMember(
        user_id=current_user.id,
        tenant_id=tenant.id,
        role=MemberRole.OWNER,
    )
    session.add(membership)
    await session.commit()
    await session.refresh(tenant)

    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        schema_name=tenant.schema_name,
        config=tenant.config,
        status=tenant.status.value,
        created_at=str(tenant.created_at),
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = _require_membership(session, current_user, tenant_id)
    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        schema_name=tenant.schema_name,
        config=tenant.config,
        status=tenant.status.value,
        created_at=str(tenant.created_at),
    )


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_config(
    tenant_id: uuid.UUID,
    req: TenantConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = _require_membership(session, current_user, tenant_id, require_owner=True)

    config = tenant.config or {}
    update_data = req.model_dump(exclude_none=True)
    config.update(update_data)
    tenant.config = config
    await session.commit()
    await session.refresh(tenant)

    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        schema_name=tenant.schema_name,
        config=tenant.config,
        status=tenant.status.value,
        created_at=str(tenant.created_at),
    )


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, tenant = _require_membership(session, current_user, tenant_id, require_owner=True)
    tenant.status = TenantStatus.DELETING
    await session.commit()
```

- [ ] **Step 3: Register tenant router in main.py**

Add to main.py after `app.include_router(auth_router)`:

```python
from hindsight_manager.api.tenants import router as tenants_router
app.include_router(tenants_router)
```

- [ ] **Step 4: Run tests**

```bash
cd ../hindsight-manager && uv run pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add tenant CRUD endpoints"
```

### Task 10: Member management endpoints

**Files:**
- Create: `../hindsight-manager/hindsight_manager/api/members.py`

- [ ] **Step 1: Write api/members.py**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["members"])


class AddMemberRequest(BaseModel):
    username: str
    role: MemberRole = MemberRole.MEMBER


class UpdateRoleRequest(BaseModel):
    role: MemberRole


class MemberResponse(BaseModel):
    user_id: str
    username: str
    role: str


async def _get_tenant(session: AsyncSession, user: User, tenant_id: uuid.UUID) -> Tenant:
    result = await session.execute(
        select(TenantMember, Tenant)
        .join(Tenant, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id, TenantMember.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    membership, tenant = row
    if membership.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")
    return tenant


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_tenant(session, current_user, tenant_id)

    result = await session.execute(
        select(TenantMember, User)
        .join(User, TenantMember.user_id == User.id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    return [
        MemberResponse(user_id=str(u.id), username=u.username, role=m.role.value)
        for m, u in result.all()
    ]


@router.post("/members", response_model=MemberResponse, status_code=201)
async def add_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant = await _get_tenant(session, current_user, tenant_id)

    result = await session.execute(select(User).where(User.username == req.username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == target_user.id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    member = TenantMember(
        user_id=target_user.id,
        tenant_id=tenant_id,
        role=req.role,
    )
    session.add(member)
    await session.commit()

    return MemberResponse(user_id=str(target_user.id), username=target_user.username, role=req.role.value)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_tenant(session, current_user, tenant_id)

    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    await session.delete(member)
    await session.commit()


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateRoleRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_tenant(session, current_user, tenant_id)

    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = req.role
    await session.commit()

    target_user = await session.get(User, user_id)
    return MemberResponse(
        user_id=str(user_id),
        username=target_user.username if target_user else "unknown",
        role=req.role.value,
    )
```

- [ ] **Step 2: Register member router in main.py**

Add after tenant router:

```python
from hindsight_manager.api.members import router as members_router
app.include_router(members_router)
```

- [ ] **Step 3: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add member management endpoints"
```

### Task 11: API key management endpoints

**Files:**
- Create: `../hindsight-manager/hindsight_manager/api/api_keys.py`

- [ ] **Step 1: Write api/api_keys.py**

```python
import secrets
import uuid
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import MemberRole, TenantMember
from hindsight_manager.models.user import User

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["api-keys"])

KEY_PREFIX = "hsm_"


def _generate_api_key() -> tuple[str, str]:
    raw = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw, sha256(raw.encode()).hexdigest()


async def _require_owner(session: AsyncSession, user: User, tenant_id: uuid.UUID) -> Tenant:
    result = await session.execute(
        select(TenantMember, Tenant)
        .join(Tenant, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id, TenantMember.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    membership, tenant = row
    if membership.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")
    return tenant


class CreateApiKeyRequest(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: str | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str


class RevokeResponse(BaseModel):
    ok: bool


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    tenant_id: uuid.UUID,
    req: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    raw_key, key_hash = _generate_api_key()
    api_key = ApiKey(
        tenant_id=tenant_id,
        key_hash=key_hash,
        key_prefix=raw_key[:16],
        name=req.name,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    return ApiKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        created_at=str(api_key.created_at),
        last_used_at=str(api_key.last_used_at) if api_key.last_used_at else None,
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_id)
    )
    return [
        ApiKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            created_at=str(k.created_at),
            last_used_at=str(k.last_used_at) if k.last_used_at else None,
        )
        for k in result.scalars().all()
    ]


@router.delete("/api-keys/{key_id}", response_model=RevokeResponse)
async def revoke_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(session, current_user, tenant_id)

    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    await session.delete(api_key)
    await session.commit()
    return RevokeResponse(ok=True)
```

- [ ] **Step 2: Register API key router in main.py**

```python
from hindsight_manager.api.api_keys import router as api_keys_router
app.include_router(api_keys_router)
```

- [ ] **Step 3: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add API key management endpoints"
```

---

## Phase 4: CLI

### Task 12: CLI scaffolding and auth commands

**Files:**
- Create: `../hindsight-manager/hindsight_manager/cli/__init__.py`
- Create: `../hindsight-manager/hindsight_manager/cli/main.py`
- Create: `../hindsight-manager/hindsight_manager/cli/auth.py`

- [ ] **Step 1: Write cli/main.py — Typer app entry point**

```python
import typer

app = typer.Typer(name="hindsight-manager")

from hindsight_manager.cli.auth import app as auth_app
from hindsight_manager.cli.tenant import app as tenant_app

app.add_typer(auth_app, name="auth")
app.add_typer(tenant_app, name="tenant")
```

- [ ] **Step 2: Write cli/auth.py**

```python
import os
from pathlib import Path

import httpx
import typer

app = typer.Typer()

CONFIG_DIR = Path.home() / ".hindsight-manager"
SESSION_FILE = CONFIG_DIR / "session"


def _get_base_url() -> str:
    return os.environ.get("HINDSIGHT_MANAGER_URL", "http://localhost:8001")


def _save_session(base_url: str, token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(f"{base_url}\n{token}")


def _load_session() -> tuple[str, str] | None:
    if not SESSION_FILE.exists():
        return None
    lines = SESSION_FILE.read_text().strip().split("\n")
    if len(lines) != 2:
        return None
    return lines[0], lines[1]


def _get_auth_headers() -> dict[str, str]:
    session = _load_session()
    if not session:
        typer.echo("Not logged in. Run 'hindsight-manager auth login' first.", err=True)
        raise typer.Exit(1)
    base_url, token = session
    return {"Cookie": f"hindsight_session={token}"}


@app.command()
def login():
    base_url = _get_base_url()
    username = typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True)

    try:
        resp = httpx.post(
            f"{base_url}/auth/login",
            json={"provider": "local", "username": username, "password": password},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        typer.echo(f"Login failed: {e}", err=True)
        raise typer.Exit(1)

    data = resp.json()
    _save_session(base_url, data["token"])
    typer.echo(f"Logged in as {data['user']['username']}")


@app.command()
def logout():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    typer.echo("Logged out")


@app.command()
def me():
    session = _load_session()
    if not session:
        typer.echo("Not logged in.", err=True)
        raise typer.Exit(1)
    base_url, token = session
    try:
        resp = httpx.get(f"{base_url}/auth/me", headers={"Cookie": f"hindsight_session={token}"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        typer.echo(f"Request failed: {e}", err=True)
        raise typer.Exit(1)

    user = resp.json()
    typer.echo(f"ID:          {user['id']}")
    typer.echo(f"Username:    {user['username']}")
    typer.echo(f"Display:     {user['display_name']}")
    typer.echo(f"Auth:        {user['auth_provider']}")
```

- [ ] **Step 3: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add CLI auth commands (login, logout, me)"
```

### Task 13: CLI tenant commands

**Files:**
- Create: `../hindsight-manager/hindsight_manager/cli/tenant.py`

- [ ] **Step 1: Write cli/tenant.py**

```python
import os
from pathlib import Path

import httpx
import typer

app = typer.Typer()

CONFIG_DIR = Path.home() / ".hindsight-manager"
SESSION_FILE = CONFIG_DIR / "session"


def _get_base_url() -> str:
    return os.environ.get("HINDSIGHT_MANAGER_URL", "http://localhost:8001")


def _load_session() -> tuple[str, str] | None:
    if not SESSION_FILE.exists():
        return None
    lines = SESSION_FILE.read_text().strip().split("\n")
    if len(lines) != 2:
        return None
    return lines[0], lines[1]


def _get_auth_headers() -> dict[str, str]:
    session = _load_session()
    if not session:
        typer.echo("Not logged in. Run 'hindsight-manager auth login' first.", err=True)
        raise typer.Exit(1)
    _, token = session
    return {"Cookie": f"hindsight_session={token}"}


@app.command(name="list")
def list_tenants():
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants", headers=headers)
    resp.raise_for_status()
    tenants = resp.json()
    if not tenants:
        typer.echo("No tenants.")
        return
    for t in tenants:
        typer.echo(f"  {t['id'][:8]}  {t['name']}  ({t['schema_name']})  [{t['status']}]")


@app.command()
def create(name: str = typer.Option(..., "--name", help="Tenant name")):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(f"{base_url}/tenants", json={"name": name}, headers=headers)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"Created tenant: {t['name']} (schema: {t['schema_name']})")


@app.command()
def show(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}", headers=headers)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"ID:       {t['id']}")
    typer.echo(f"Name:     {t['name']}")
    typer.echo(f"Schema:   {t['schema_name']}")
    typer.echo(f"Status:   {t['status']}")
    typer.echo(f"Config:   {t['config'] or '(default)'}")


@app.command(name="delete")
def delete_tenant(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.delete(f"{base_url}/tenants/{tenant_id}", headers=headers)
    resp.raise_for_status()
    typer.echo("Tenant marked for deletion.")


@app.command()
def config_set(
    tenant_id: str,
    llm_provider: str | None = typer.Option(None),
    llm_model: str | None = typer.Option(None),
    llm_api_key: str | None = typer.Option(None),
    llm_base_url: str | None = typer.Option(None),
    embeddings_provider: str | None = typer.Option(None),
    embeddings_model: str | None = typer.Option(None),
):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    data = {}
    if llm_provider is not None:
        data["llm_provider"] = llm_provider
    if llm_model is not None:
        data["llm_model"] = llm_model
    if llm_api_key is not None:
        data["llm_api_key"] = llm_api_key
    if llm_base_url is not None:
        data["llm_base_url"] = llm_base_url
    if embeddings_provider is not None:
        data["embeddings_provider"] = embeddings_provider
    if embeddings_model is not None:
        data["embeddings_model"] = embeddings_model
    if not data:
        typer.echo("No config values specified.", err=True)
        raise typer.Exit(1)
    resp = httpx.patch(f"{base_url}/tenants/{tenant_id}", json=data, headers=headers)
    resp.raise_for_status()
    typer.echo("Config updated.")


@app.command()
def config_get(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}", headers=headers)
    resp.raise_for_status()
    t = resp.json()
    config = t.get("config") or {}
    if not config:
        typer.echo("No custom config (using server defaults).")
        return
    for k, v in config.items():
        display = v if "key" not in k.lower() else "***"
        typer.echo(f"  {k}: {display}")


# Member subcommands
member_app = typer.Typer()
app.add_typer(member_app, name="member")


@member_app.command(name="list")
def member_list(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/members", headers=headers)
    resp.raise_for_status()
    members = resp.json()
    for m in members:
        typer.echo(f"  {m['username']}  ({m['role']})")


@member_app.command(name="add")
def member_add(tenant_id: str, username: str, role: str = "member"):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(f"{base_url}/tenants/{tenant_id}/members", json={"username": username, "role": role}, headers=headers)
    resp.raise_for_status()
    typer.echo(f"Added {username} as {role}.")


@member_app.command(name="remove")
def member_remove(tenant_id: str, username: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/members", headers=headers)
    members = resp.json()
    target = next((m for m in members if m["username"] == username), None)
    if not target:
        typer.echo(f"User {username} not found in tenant.", err=True)
        raise typer.Exit(1)
    resp = httpx.delete(f"{base_url}/tenants/{tenant_id}/members/{target['user_id']}", headers=headers)
    resp.raise_for_status()
    typer.echo(f"Removed {username}.")


@member_app.command(name="role")
def member_role(tenant_id: str, username: str, role: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/members", headers=headers)
    members = resp.json()
    target = next((m for m in members if m["username"] == username), None)
    if not target:
        typer.echo(f"User {username} not found in tenant.", err=True)
        raise typer.Exit(1)
    resp = httpx.patch(f"{base_url}/tenants/{tenant_id}/members/{target['user_id']}", json={"role": role}, headers=headers)
    resp.raise_for_status()
    typer.echo(f"Updated {username} role to {role}.")


# API key subcommands
api_key_app = typer.Typer()
app.add_typer(api_key_app, name="api-key")


@api_key_app.command(name="create")
def api_key_create(tenant_id: str, name: str = typer.Option("default")):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(f"{base_url}/tenants/{tenant_id}/api-keys", json={"name": name}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    typer.echo(f"API Key created: {data['key']}")
    typer.echo("Save this key — it will not be shown again.", err=True)


@api_key_app.command(name="list")
def api_key_list(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/api-keys", headers=headers)
    resp.raise_for_status()
    keys = resp.json()
    if not keys:
        typer.echo("No API keys.")
        return
    for k in keys:
        typer.echo(f"  {k['id'][:8]}  {k['name']}  ({k['key_prefix']}...)")


@api_key_app.command(name="revoke")
def api_key_revoke(tenant_id: str, key_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.delete(f"{base_url}/tenants/{tenant_id}/api-keys/{key_id}", headers=headers)
    resp.raise_for_status()
    typer.echo("API key revoked.")
```

- [ ] **Step 2: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add CLI tenant, member, and api-key commands"
```

---

## Phase 5: ManagerTenantExtension (hindsight-api side)

### Task 14: ManagerTenantExtension implementation

**Files:**
- Create: `hindsight-api-slim/hindsight_api/extensions/builtin/manager_tenant.py`

- [ ] **Step 1: Write manager_tenant.py**

This extension lives in the hindsight-api-slim project. It reads metadata from the `manager` schema to authenticate API keys and resolve per-tenant config.

```python
from hashlib import sha256

from hindsight_api.extensions.tenant import (
    AuthenticationError,
    Tenant,
    TenantContext,
    TenantExtension,
)
from hindsight_api.models import RequestContext


class ManagerTenantExtension(TenantExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self._manager_schema = config.get("manager_schema", "manager")
        self._initialized_schemas: set[str] = set()

    async def authenticate(self, context: RequestContext) -> TenantContext:
        api_key = context.api_key
        if not api_key:
            raise AuthenticationError("Missing API key")

        key_hash = sha256(api_key.encode()).hexdigest()

        bind = self.context.get_memory_engine()._db_engine  # noqa: SLF001
        from sqlalchemy import text

        async with bind.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT t.schema_name, t.config
                    FROM {self._manager_schema}.api_keys ak
                    JOIN {self._manager_schema}.tenants t ON ak.tenant_id = t.id
                    WHERE ak.key_hash = :key_hash AND t.status = 'active'
                    """
                ),
                {"key_hash": key_hash},
            )
            row = result.fetchone()
            if not row:
                raise AuthenticationError("Invalid API key")

            schema_name, config = row[0], row[1]
            context.tenant_id = schema_name  # not strictly needed but useful for logging

            # Provision schema on first access
            if schema_name not in self._initialized_schemas:
                await self.context.run_migration(schema_name)
                self._initialized_schemas.add(schema_name)

            return TenantContext(schema_name=schema_name)

    async def get_tenant_config(self, context: RequestContext) -> dict[str, object]:
        api_key = context.api_key
        if not api_key:
            return {}

        key_hash = sha256(api_key.encode()).hexdigest()
        bind = self.context.get_memory_engine()._db_engine  # noqa: SLF001
        from sqlalchemy import text

        async with bind.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT t.config
                    FROM {self._manager_schema}.api_keys ak
                    JOIN {self._manager_schema}.tenants t ON ak.tenant_id = t.id
                    WHERE ak.key_hash = :key_hash AND t.status = 'active'
                    """
                ),
                {"key_hash": key_hash},
            )
            row = result.fetchone()
            if not row or not row[0]:
                return {}
            return row[0]

    async def list_tenants(self) -> list[Tenant]:
        bind = self.context.get_memory_engine()._db_engine  # noqa: SLF001
        from sqlalchemy import text

        async with bind.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT schema_name FROM {self._manager_schema}.tenants WHERE status = 'active'"
                )
            )
            return [Tenant(schema=row[0]) for row in result.fetchall()]
```

- [ ] **Step 2: Write test for ManagerTenantExtension**

```python
# hindsight-api-slim/tests/test_manager_tenant.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hindsight_api.extensions.builtin.manager_tenant import ManagerTenantExtension
from hindsight_api.models import RequestContext


def _make_row(schema_name: str, config: dict | None = None):
    row = MagicMock()
    row.fetchone.return_value = (schema_name, config)
    return row


def _make_result(rows):
    result = MagicMock()
    result.fetchall.return_value = [(r,) for r in rows]
    result.fetchone.return_value = rows[0] if rows else None
    return result


@pytest.fixture
def ext():
    return ManagerTenantExtension({"manager_schema": "manager"})


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    conn = AsyncMock()
    conn.execute.return_value = _make_result([])
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    engine.connect.return_value = conn
    return engine


@pytest.fixture
def mock_context(mock_engine):
    ctx = MagicMock()
    ctx.run_migration = AsyncMock()
    mem = MagicMock()
    mem._db_engine = mock_engine
    ctx.get_memory_engine.return_value = mem
    return ctx


async def test_authenticate_valid_key(ext, mock_engine, mock_context):
    ext.set_context(mock_context)
    conn = await mock_engine.connect()
    conn.execute.return_value = _make_row("tenant_abc123", {"llm_provider": "openai"})

    ctx = RequestContext(api_key="hsm_testkey123")
    result = await ext.authenticate(ctx)
    assert result.schema_name == "tenant_abc123"
    mock_context.run_migration.assert_called_once_with("tenant_abc123")


async def test_authenticate_missing_key(ext, mock_context):
    ext.set_context(mock_context)
    ctx = RequestContext(api_key=None)
    with pytest.raises(Exception):
        await ext.authenticate(ctx)


async def test_authenticate_invalid_key(ext, mock_engine, mock_context):
    ext.set_context(mock_context)
    conn = await mock_engine.connect()
    conn.execute.return_value = _make_result([])

    ctx = RequestContext(api_key="hsm_badkey")
    with pytest.raises(Exception):
        await ext.authenticate(ctx)


async def test_list_tenants(ext, mock_engine, mock_context):
    ext.set_context(mock_context)
    conn = await mock_engine.connect()
    conn.execute.return_value = _make_result(["tenant_a", "tenant_b"])

    tenants = await ext.list_tenants()
    assert len(tenants) == 2
    assert tenants[0].schema == "tenant_a"
```

- [ ] **Step 3: Run tests**

```bash
cd hindsight-api-slim && uv run pytest tests/test_manager_tenant.py -v
```

- [ ] **Step 4: Commit**

```bash
cd /Users/liling/src/lab/hindsight && git add hindsight-api-slim/hindsight_api/extensions/builtin/manager_tenant.py hindsight-api-slim/tests/test_manager_tenant.py && git commit -m "feat: add ManagerTenantExtension for hindsight-manager integration"
```

---

## Phase 6: Integration & Polish

### Task 15: Integration test — full flow

**Files:**
- Create: `../hindsight-manager/tests/test_integration.py`

- [ ] **Step 1: Write integration test covering the full flow**

```python
# tests/test_integration.py
"""Integration test: create user, create tenant, create API key, verify auth flow."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

Note: Full integration tests require a real PostgreSQL connection. This test file should be run against a test database and can be expanded incrementally. The key scenarios:

1. Create user (local) -> login -> get session
2. Create tenant -> verify schema_name assigned
3. Add member -> verify member appears
4. Create API key -> verify key format
5. Update config -> verify config stored
6. Delete tenant -> verify status = deleting

- [ ] **Step 2: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "test: add integration test scaffold"
```

### Task 16: Add admin CLI commands (user management)

**Files:**
- Create: `../hindsight-manager/hindsight_manager/cli/admin.py`

- [ ] **Step 1: Write cli/admin.py — local user management**

```python
import os
from pathlib import Path

import httpx
import typer

app = typer.Typer()

CONFIG_DIR = Path.home() / ".hindsight-manager"
SESSION_FILE = CONFIG_DIR / "session"


def _get_base_url() -> str:
    return os.environ.get("HINDSIGHT_MANAGER_URL", "http://localhost:8001")


def _load_session() -> tuple[str, str] | None:
    if not SESSION_FILE.exists():
        return None
    lines = SESSION_FILE.read_text().strip().split("\n")
    if len(lines) != 2:
        return None
    return lines[0], lines[1]


def _get_auth_headers() -> dict[str, str]:
    session = _load_session()
    if not session:
        typer.echo("Not logged in. Run 'hindsight-manager auth login' first.", err=True)
        raise typer.Exit(1)
    _, token = session
    return {"Cookie": f"hindsight_session={token}"}


@app.command(name="create-user")
def create_user(username: str, password: str = typer.Option(..., prompt=True, hide_input=True)):
    """Create a local user (admin operation)."""
    base_url = _get_base_url()
    # This will need a corresponding admin API endpoint in the future.
    # For now, direct DB insertion via a dedicated endpoint.
    typer.echo(f"User creation for '{username}' — not yet implemented via API.")
    typer.echo("Use direct database insertion or the admin API when available.")
```

- [ ] **Step 2: Register admin app in cli/main.py**

Add after existing imports:

```python
from hindsight_manager.cli.admin import app as admin_app
app.add_typer(admin_app, name="admin")
```

- [ ] **Step 3: Commit**

```bash
cd ../hindsight-manager && git add -A && git commit -m "feat: add admin CLI scaffold for user management"
```

---

## Summary

| Phase | Tasks | What it produces |
|---|---|---|
| 1. Scaffolding | 1-3 | Project with ORM models and Alembic migration |
| 2. Auth | 4-8 | JWT session, local/CAS auth, FastAPI auth endpoints |
| 3. Tenant CRUD | 9-11 | Tenant CRUD, member management, API key endpoints |
| 4. CLI | 12-13 | Full CLI for all management operations |
| 5. Extension | 14 | ManagerTenantExtension in hindsight-api |
| 6. Integration | 15-16 | Integration tests, admin CLI scaffold |
