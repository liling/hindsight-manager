# 自动注册与服务发现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 HM 和 DM 启动时自动注册到 xinyi-platform，product switcher 从数据库动态拉取，新增服务零代码改动。

**Architecture:** `business_clients` 表扩展导航字段。平台新增注册端点（registration token 鉴权）和发现端点（client secret 鉴权）。共享逻辑放 `xinyi_platform.ui_common.service_discovery`。`install_ui()` 删除硬编码 URL 参数，products 改为 lifespan 中动态填充。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, httpx, APScheduler, pytest-asyncio。

## Global Constraints

- **三个仓库**：`/Users/liling/src/lab/xinyi-platform/`、`/Users/liling/src/lab/hindsight-manager/`、`/Users/liling/src/lab/docupipe-manager/`
- **REGISTRATION_TOKEN**：三个服务各自 env 配同一个值（前缀不同：`XINYI_PLATFORM_`、`HINDSIGHT_MANAGER_`、`DOCUPIPE_MANAGER_`）
- **secret 派生公式**：`base64url(HMAC-SHA256(token, client_id))`，两边各自算
- **迁移 revision**：xinyi-platform 下一个是 `005`（当前 head 是 `004`）
- **Schema**：所有 xinyi 表用 `schema="xinyi"`
- **现有测试模式**：`pytest-asyncio` auto mode，mock session 用 `MagicMock` + `AsyncMock`，无 `@pytest.mark.asyncio`

## File Structure

### 新建文件

```
xinyi_platform/
├── ui_common/
│   └── service_discovery.py          # 共享：派生 secret + 注册 + 发现 + 组装 products
├── api/
│   └── internal_clients.py           # 新建：POST /internal/clients/register + GET /internal/clients/active
├── migrations/versions/
│   └── 005_add_client_navigation_fields.py
└── tests/
    ├── unit/
    │   └── test_service_discovery.py # 派生公式 + build_product_list 测试
    └── api/
        └── test_internal_clients_api.py  # 注册 + 发现端点测试
```

### 修改文件

```
xinyi_platform/
├── models/business_client.py         # +5 字段
├── config.py                         # +registration_token
├── services/business_client_service.py  # +register_or_update()
├── auth/internal_auth.py             # +verify_registration_token()
├── api/internal_clients.py           # 新建（见上）
├── main.py                           # install_ui 调用改参数 + lifespan 填充 products + include_router
├── ui_common/install.py              # 删 manager_url/docupipe_url 参数 + 删 _resolve_products
├── ui_common/registry.py             # 删除整个文件
└── api/admin_clients.py              # _ui_ctx 去掉 manager_url

hindsight_manager/
├── config.py                         # +registration_token
└── main.py                           # lifespan 加派生 secret + 注册 + 发现 + 后台刷新

docupipe_manager/
├── config.py                         # +registration_token
└── main.py                           # lifespan 加派生 secret + 注册 + 发现 + 后台刷新
```

---

## Task 1: BusinessClient 模型扩展 + 迁移

**Files:**
- Modify: `xinyi_platform/models/business_client.py`
- Create: `xinyi_platform/migrations/versions/005_add_client_navigation_fields.py`

**Interfaces:**
- Produces: `BusinessClient` 新增 `base_url`、`home_path`、`description`、`logo_url`、`last_seen_at` 字段

- [ ] **Step 1: 扩展模型**

在 `xinyi_platform/models/business_client.py` 的 `BusinessClient` 类中，在 `logout_url` 之后、`status` 之前加入：

```python
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    home_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

注意：现有文件有 `created_at`/`updated_at` 重复声明（legacy bug），不修复，仅追加新字段。

- [ ] **Step 2: 创建迁移**

`xinyi_platform/migrations/versions/005_add_client_navigation_fields.py`:

```python
"""add client navigation fields

Revision ID: 005
Revises: 004
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("business_clients", sa.Column("base_url", sa.String(512), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("home_path", sa.String(255), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("description", sa.String(255), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("logo_url", sa.String(512), nullable=True), schema="xinyi")
    op.add_column("business_clients", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True), schema="xinyi")


def downgrade() -> None:
    op.drop_column("business_clients", "last_seen_at", schema="xinyi")
    op.drop_column("business_clients", "logo_url", schema="xinyi")
    op.drop_column("business_clients", "description", schema="xinyi")
    op.drop_column("business_clients", "home_path", schema="xinyi")
    op.drop_column("business_clients", "base_url", schema="xinyi")
```

- [ ] **Step 3: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/models/business_client.py xinyi_platform/migrations/versions/005_add_client_navigation_fields.py
git commit -m "feat: add navigation fields to BusinessClient (base_url, home_path, description, logo_url, last_seen_at)"
```

---

## Task 2: Config + 派生 secret + service_discovery 共享模块

**Files:**
- Modify: `xinyi_platform/config.py`
- Create: `xinyi_platform/ui_common/service_discovery.py`
- Create: `xinyi_platform/tests/unit/test_service_discovery.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Settings.registration_token: str`
  - `derive_client_secret(registration_token, client_id) -> str`
  - `register_self(platform_url, registration_token, client_metadata) -> bool`
  - `fetch_active_clients(platform_url, client_id, client_secret) -> list[dict]`
  - `build_product_list(active_clients, *, platform_url, self_client_id, self_name, self_home_path) -> list[dict]`

- [ ] **Step 1: 加 registration_token 到 config**

在 `xinyi_platform/config.py` 的 `Settings` 类中，在 `session_secure: bool = False` 之后加：

```python
    registration_token: str = ""
```

- [ ] **Step 2: 写 service_discovery 测试**

`xinyi_platform/tests/unit/test_service_discovery.py`:

```python
import hashlib
import hmac
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from xinyi_platform.ui_common.service_discovery import (
    derive_client_secret,
    register_self,
    fetch_active_clients,
    build_product_list,
)


def test_derive_client_secret_deterministic():
    token = "test-registration-token-1234567890"
    client_id = "hm-prod"
    s1 = derive_client_secret(token, client_id)
    s2 = derive_client_secret(token, client_id)
    assert s1 == s2
    assert len(s1) > 30


def test_derive_client_secret_different_client_ids():
    token = "test-registration-token-1234567890"
    s1 = derive_client_secret(token, "hm-prod")
    s2 = derive_client_secret(token, "docupipe-prod")
    assert s1 != s2


def test_derive_client_secret_matches_hmac_formula():
    token = "my-token"
    client_id = "hm-prod"
    expected = base64.urlsafe_b64encode(
        hmac.new(token.encode(), client_id.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert derive_client_secret(token, client_id) == expected


async def test_register_self_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "registered"}
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await register_self(
            platform_url="http://xinyi:8000/xinyi",
            registration_token="tok",
            client_metadata={"client_id": "hm-prod", "name": "HM"},
        )
    assert result is True


async def test_register_self_platform_down_returns_false():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await register_self(
            platform_url="http://xinyi:8000/xinyi",
            registration_token="tok",
            client_metadata={"client_id": "hm-prod"},
        )
    assert result is False


async def test_fetch_active_clients_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"clients": [
        {"client_id": "hm-prod", "name": "HM", "base_url": "http://hm:8001", "home_path": "/dashboard", "description": "RAG"},
    ]}
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await fetch_active_clients(
            platform_url="http://xinyi:8000/xinyi",
            client_id="hm-prod",
            client_secret="secret",
        )
    assert len(result) == 1
    assert result[0]["client_id"] == "hm-prod"


async def test_fetch_active_clients_platform_down_returns_empty():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await fetch_active_clients(
            platform_url="http://xinyi:8000/xinyi",
            client_id="hm-prod",
            client_secret="secret",
        )
    assert result == []


def test_build_product_list_includes_platform_first():
    clients = [
        {"client_id": "hm-prod", "name": "HM", "base_url": "http://hm:8001", "home_path": "/dashboard", "description": "RAG"},
    ]
    products = build_product_list(
        clients,
        platform_url="http://xinyi:8000/xinyi",
        self_client_id="hm-prod",
        self_name="Hindsight Manager",
        self_home_path="/dashboard",
    )
    assert products[0]["id"] == "platform"
    assert products[0]["kind"] == "platform"
    assert products[0]["is_current"] is False


def test_build_product_list_marks_current_service():
    clients = [
        {"client_id": "hm-prod", "name": "HM", "base_url": "http://hm:8001", "home_path": "/dashboard", "description": "RAG"},
        {"client_id": "docupipe-prod", "name": "DM", "base_url": "http://dm:8002", "home_path": "/projects", "description": "Pipe"},
    ]
    products = build_product_list(
        clients,
        platform_url="http://xinyi:8000/xinyi",
        self_client_id="hm-prod",
        self_name="Hindsight Manager",
        self_home_path="/dashboard",
    )
    hm = [p for p in products if p["id"] == "hm-prod"][0]
    dm = [p for p in products if p["id"] == "docupipe-prod"][0]
    assert hm["is_current"] is True
    assert dm["is_current"] is False
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/unit/test_service_discovery.py -v`
Expected: ImportError / ModuleNotFoundError

- [ ] **Step 4: 实现 service_discovery.py**

`xinyi_platform/ui_common/service_discovery.py`:

```python
"""Shared auto-registration and service discovery for xinyi-platform business clients."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import httpx

logger = logging.getLogger(__name__)


def derive_client_secret(registration_token: str, client_id: str) -> str:
    """Derive a deterministic client_secret from registration token + client_id."""
    raw = hmac.new(
        registration_token.encode(),
        client_id.encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def register_self(
    platform_url: str,
    registration_token: str,
    client_metadata: dict,
) -> bool:
    """POST /internal/clients/register to register this service.

    Returns True on success, False on failure (never raises).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{platform_url}/internal/clients/register",
                json=client_metadata,
                headers={"X-Registration-Token": registration_token},
            )
            if resp.status_code >= 400:
                logger.warning("register_self failed: %s %s", resp.status_code, resp.text[:200])
                return False
            logger.info("registered with platform as %s", client_metadata.get("client_id"))
            return True
    except Exception as e:
        logger.warning("register_self error: %s", e)
        return False


async def fetch_active_clients(
    platform_url: str,
    client_id: str,
    client_secret: str,
) -> list[dict]:
    """GET /internal/clients/active to discover all registered services.

    Returns list of client dicts, or empty list on failure (never raises).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{platform_url}/internal/clients/active",
                headers={
                    "X-Client-Id": client_id,
                    "X-Client-Secret": client_secret,
                },
            )
            if resp.status_code >= 400:
                logger.warning("fetch_active_clients failed: %s", resp.status_code)
                return []
            data = resp.json()
            return data.get("clients", [])
    except Exception as e:
        logger.warning("fetch_active_clients error: %s", e)
        return []


def build_product_list(
    active_clients: list[dict],
    *,
    platform_url: str,
    self_client_id: str,
    self_name: str,
    self_home_path: str,
) -> list[dict]:
    """Assemble the product switcher list.

    Platform is always first. Each business client follows, with is_current flag.
    """
    products: list[dict] = []

    products.append({
        "id": "platform",
        "label": "平台账户中心",
        "subtitle": "用户 · 审计 · 登录历史",
        "url": f"{platform_url}/account",
        "kind": "platform",
        "is_current": False,
    })

    for c in active_clients:
        products.append({
            "id": c["client_id"],
            "label": c.get("name", c["client_id"]),
            "subtitle": c.get("description", ""),
            "url": f"{c['base_url']}{c.get('home_path', '')}",
            "kind": "business",
            "is_current": c["client_id"] == self_client_id,
        })

    return products
```

- [ ] **Step 5: 运行测试**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/unit/test_service_discovery.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/config.py xinyi_platform/ui_common/service_discovery.py tests/unit/test_service_discovery.py
git commit -m "feat: add registration_token config + service_discovery shared module"
```

---

## Task 3: BusinessClientService.register_or_update()

**Files:**
- Modify: `xinyi_platform/services/business_client_service.py`
- Modify: `xinyi_platform/tests/services/test_business_client_service.py`

**Interfaces:**
- Produces: `BusinessClientService.register_or_update(session, *, client_id, name, client_secret_hash, redirect_uris, logout_url, base_url, home_path, description) -> BusinessClient`

- [ ] **Step 1: 写测试**

在 `xinyi_platform/tests/services/test_business_client_service.py` 末尾追加：

```python
async def test_register_or_update_creates_new():
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    client = await BusinessClientService.register_or_update(
        mock_session,
        client_id="hm-prod",
        name="Hindsight Manager",
        client_secret_hash="$2b$12$abc",
        redirect_uris=["http://hm:8001/callback"],
        logout_url="http://hm:8001/logout",
        base_url="http://hm:8001",
        home_path="/dashboard",
        description="RAG",
    )
    mock_session.add.assert_called_once()
    assert client.client_id == "hm-prod"
    assert client.base_url == "http://hm:8001"


async def test_register_or_update_updates_existing_metadata():
    existing = BusinessClient(
        client_id="hm-prod",
        name="Old Name",
        client_secret_hash="$2b$12$old",
        redirect_uris=["http://old"],
        logout_url=None,
        status=ClientStatus.ACTIVE,
    )
    existing.base_url = None
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))
    mock_session.flush = AsyncMock()

    client = await BusinessClientService.register_or_update(
        mock_session,
        client_id="hm-prod",
        name="New Name",
        client_secret_hash="$2b$12$new",
        redirect_uris=["http://new"],
        logout_url="http://hm:8001/logout",
        base_url="http://hm:8001",
        home_path="/dashboard",
        description="RAG",
    )
    assert client.name == "New Name"
    assert client.base_url == "http://hm:8001"
    assert client.client_secret_hash == "$2b$12$old"  # NOT overwritten
    mock_session.add.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/services/test_business_client_service.py::test_register_or_update_creates_new -v`
Expected: AttributeError (method doesn't exist)

- [ ] **Step 3: 实现 register_or_update**

在 `xinyi_platform/services/business_client_service.py` 的 `BusinessClientService` 类末尾加：

```python
    @staticmethod
    async def register_or_update(
        session: AsyncSession,
        *,
        client_id: str,
        name: str,
        client_secret_hash: str,
        redirect_uris: list[str],
        logout_url: str | None = None,
        base_url: str | None = None,
        home_path: str | None = None,
        description: str | None = None,
    ) -> BusinessClient:
        """Idempotent upsert: creates if absent, updates metadata if present.

        client_secret_hash is only set on INSERT, never overwritten on UPDATE.
        """
        result = await session.execute(
            select(BusinessClient).where(BusinessClient.client_id == client_id)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.name = name
            existing.redirect_uris = redirect_uris
            existing.logout_url = logout_url
            existing.base_url = base_url
            existing.home_path = home_path
            existing.description = description
            existing.last_seen_at = datetime.now(timezone.utc)
            existing.updated_at = datetime.now(timezone.utc)
            await session.flush()
            return existing

        client = BusinessClient(
            client_id=client_id,
            name=name,
            client_secret_hash=client_secret_hash,
            redirect_uris=redirect_uris,
            logout_url=logout_url,
            base_url=base_url,
            home_path=home_path,
            description=description,
            last_seen_at=datetime.now(timezone.utc),
            status=ClientStatus.ACTIVE,
        )
        session.add(client)
        await session.flush()
        return client
```

- [ ] **Step 4: 运行测试**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/services/test_business_client_service.py -v`
Expected: all passed (including existing tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/services/business_client_service.py tests/services/test_business_client_service.py
git commit -m "feat: BusinessClientService.register_or_update for idempotent auto-registration"
```

---

## Task 4: 注册端点 + 发现端点

**Files:**
- Create: `xinyi_platform/api/internal_clients.py`
- Modify: `xinyi_platform/auth/internal_auth.py`
- Modify: `xinyi_platform/main.py`
- Create: `xinyi_platform/tests/api/test_internal_clients_api.py`

**Interfaces:**
- Produces:
  - `verify_registration_token` dependency
  - `POST /internal/clients/register`
  - `GET /internal/clients/active`

- [ ] **Step 1: 加 registration token 验证依赖**

在 `xinyi_platform/auth/internal_auth.py` 末尾追加：

```python
from fastapi import Header as HeaderParam
from xinyi_platform.config import get_settings


async def verify_registration_token(
    x_registration_token: str = HeaderParam(..., alias="X-Registration-Token"),
) -> str:
    settings = get_settings()
    if not settings.registration_token or x_registration_token != settings.registration_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid registration token")
    return x_registration_token
```

- [ ] **Step 2: 写端点测试**

`xinyi_platform/tests/api/test_internal_clients_api.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xinyi_platform.api.internal_clients import router
from xinyi_platform.auth.internal_auth import verify_registration_token, verify_internal_client


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/xinyi")
    return app


def _mock_session(client=None, clients_list=None):
    session = MagicMock()
    session.execute = AsyncMock()
    if client is not None:
        session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=client))
    if clients_list is not None:
        session.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=clients_list))))
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


def test_register_valid_token():
    app = _make_app()
    app.dependency_overrides[verify_registration_token] = lambda: "tok"
    mock_client = MagicMock()
    mock_client.client_id = "hm-prod"
    mock_client.name = "HM"
    mock_session = _make_mock_session(client=mock_client)

    with patch("xinyi_platform.api.internal_clients.get_session") as mock_gs:
        async def _gs():
            yield mock_session
        mock_gs.return_value = _gs()
        # Also need to patch the dependency
        app.dependency_overrides[...] = ...

    # Simpler: patch get_session at module level
    with patch("xinyi_platform.api.internal_clients.BusinessClientService") as mock_svc:
        mock_svc.register_or_update = AsyncMock(return_value=mock_client)
        with patch("xinyi_platform.api.internal_clients.derive_client_secret", return_value="derived-secret"):
            with patch("xinyi_platform.api.internal_clients.bcrypt") as mock_bcrypt:
                mock_bcrypt.hashpw.return_value = b"$2b$12$hash"
                mock_bcrypt.gensalt.return_value = b"$2b$12$salt"

                app.dependency_overrides = {}
                # Override get_session
                from xinyi_platform.db import get_session as real_get_session
                async def _fake_session():
                    yield mock_session
                app.dependency_overrides[real_get_session] = _fake_session
                app.dependency_overrides[verify_registration_token] = lambda: "tok"

                client = TestClient(app)
                resp = client.post("/xinyi/internal/clients/register", json={
                    "client_id": "hm-prod",
                    "name": "Hindsight Manager",
                    "redirect_uris": ["http://hm:8001/callback"],
                    "base_url": "http://hm:8001",
                    "home_path": "/dashboard",
                    "description": "RAG",
                })
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"


def test_register_invalid_token():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/xinyi/internal/clients/register",
                       json={"client_id": "x"},
                       headers={"X-Registration-Token": "wrong"})
    assert resp.status_code == 401


def test_active_clients_returns_list():
    mock_client = MagicMock()
    mock_client.client_id = "hm-prod"
    mock_client.name = "HM"
    mock_client.base_url = "http://hm:8001"
    mock_client.home_path = "/dashboard"
    mock_client.description = "RAG"
    mock_client.logo_url = None
    mock_client.status = MagicMock(value="active")

    app = _make_app()
    mock_session = _make_mock_session(clients_list=[mock_client])

    from xinyi_platform.db import get_session as real_get_session
    from xinyi_platform.auth.internal_auth import verify_internal_client as real_verify

    async def _fake_session():
        yield mock_session
    app.dependency_overrides[real_get_session] = _fake_session
    app.dependency_overrides[real_verify] = lambda: mock_client

    client = TestClient(app)
    resp = client.get("/xinyi/internal/clients/active")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clients"]) == 1
    assert data["clients"][0]["client_id"] == "hm-prod"


def test_active_clients_requires_auth():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/xinyi/internal/clients/active")
    assert resp.status_code == 422  # Missing required headers
```

注意：`_make_mock_session` 需要支持两种 mock 模式。简化为：

```python
def _make_mock_session(client=None, clients_list=None):
    session = MagicMock()
    result = MagicMock()
    if client is not None:
        result.scalar_one_or_none = MagicMock(return_value=client)
    if clients_list is not None:
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=clients_list)))
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/api/test_internal_clients_api.py -v`
Expected: ImportError (module not found)

- [ ] **Step 4: 实现 internal_clients.py**

`xinyi_platform/api/internal_clients.py`:

```python
import bcrypt
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xinyi_platform.auth.internal_auth import verify_internal_client, verify_registration_token
from xinyi_platform.db import get_session
from xinyi_platform.models.business_client import BusinessClient, ClientStatus
from xinyi_platform.services.business_client_service import BusinessClientService
from xinyi_platform.ui_common.service_discovery import derive_client_secret
from xinyi_platform.config import get_settings

router = APIRouter(prefix="/internal/clients", tags=["internal"])


@router.post("/register")
async def register_client(
    body: dict = Body(...),
    _token: str = Depends(verify_registration_token),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    client_id = body["client_id"]

    secret = derive_client_secret(settings.registration_token, client_id)
    secret_hash = bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")

    client = await BusinessClientService.register_or_update(
        session,
        client_id=client_id,
        name=body.get("name", client_id),
        client_secret_hash=secret_hash,
        redirect_uris=body.get("redirect_uris", []),
        logout_url=body.get("logout_url"),
        base_url=body.get("base_url"),
        home_path=body.get("home_path"),
        description=body.get("description"),
    )
    await session.commit()

    return {"status": "registered", "client_id": client.client_id}


@router.get("/active")
async def list_active_clients(
    _client: BusinessClient = Depends(verify_internal_client),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(BusinessClient).where(
            BusinessClient.status == ClientStatus.ACTIVE,
            BusinessClient.base_url.isnot(None),
        ).order_by(BusinessClient.name)
    )
    clients = result.scalars().all()

    return {
        "clients": [
            {
                "client_id": c.client_id,
                "name": c.name,
                "base_url": c.base_url,
                "home_path": c.home_path or "",
                "description": c.description or "",
                "logo_url": c.logo_url,
                "kind": "business",
            }
            for c in clients
        ]
    }
```

- [ ] **Step 5: 注册路由到 main.py**

在 `xinyi_platform/main.py` 的 import 块中加：

```python
from xinyi_platform.api import (
    admin_audit, admin_clients, admin_login_history, admin_users,
    cas, internal, internal_clients, login, logout, me, oauth, password, register,
)
```

在 `app.include_router(internal.router, prefix="/xinyi")` 之后加：

```python
app.include_router(internal_clients.router, prefix="/xinyi")
```

- [ ] **Step 6: 运行测试**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/api/test_internal_clients_api.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/api/internal_clients.py xinyi_platform/auth/internal_auth.py xinyi_platform/main.py tests/api/test_internal_clients_api.py
git commit -m "feat: add /internal/clients/register + /internal/clients/active endpoints"
```

---

## Task 5: 更新 install_ui + 删除 registry.py

**Files:**
- Modify: `xinyi_platform/ui_common/install.py`
- Delete: `xinyi_platform/ui_common/registry.py`
- Modify: `xinyi_platform/ui_common/__init__.py`（如果引用了 registry）
- Modify: `xinyi_platform/tests/test_ui_install.py`

**Interfaces:**
- `install_ui()` 删除 `manager_url`、`docupipe_url` 参数
- `products` 初始为空列表 `[]`
- 删除 `_resolve_products()` 和 `PRODUCTS`

- [ ] **Step 1: 重写 install.py**

`xinyi_platform/ui_common/install.py`（完整替换）:

```python
"""install_ui: wire shared UI assets and globals into a FastAPI app."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATE_DIR = _HERE / "templates"


def install_ui(
    app: FastAPI,
    *,
    current_service: str,
    nav_menu: list[dict],
    brand: str,
    platform_url: str,
    service_prefix: str = "",
) -> None:
    """Install shared UI: Jinja globals, templates loader, static files mount.

    products starts empty; populate via app.state.ui["products"] in lifespan
    using service_discovery.build_product_list().
    """
    app.state.ui = {
        "current_service": current_service,
        "nav_menu": nav_menu,
        "brand": brand,
        "platform_url": platform_url,
        "service_prefix": service_prefix,
        "products": [],
        "template_dir": str(_TEMPLATE_DIR),
    }

    app.mount(
        f"{service_prefix}/_ui/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="ui-static",
    )


def ui_jinja_globals(request: Request) -> dict:
    ui = request.app.state.ui
    return {
        "current_service": ui["current_service"],
        "nav_menu": ui["nav_menu"],
        "brand": ui["brand"],
        "platform_url": ui["platform_url"],
        "products": ui["products"],
        "service_prefix": ui.get("service_prefix", ""),
    }
```

- [ ] **Step 2: 删除 registry.py**

```bash
cd /Users/liling/src/lab/xinyi-platform
rm xinyi_platform/ui_common/registry.py
```

- [ ] **Step 3: 检查 ui_common/__init__.py 是否引用了 registry 或旧参数**

Read `xinyi_platform/ui_common/__init__.py`，如果 import 了 `registry` 或 `_resolve_products`，删除相关行。确保只导出 `install_ui` 和 `ui_jinja_globals`。

- [ ] **Step 4: 更新现有 test_ui_install.py**

打开 `xinyi_platform/tests/test_ui_install.py`。将所有 `install_ui(...)` 调用中的 `manager_url=` 和 `docupipe_url=` 参数删除。断言 `products == []`（初始为空）。

- [ ] **Step 5: 运行测试**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest tests/test_ui_install.py tests/test_ui_integration.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/ui_common/install.py xinyi_platform/ui_common/__init__.py xinyi_platform/ui_common/registry.py tests/test_ui_install.py
git commit -m "refactor: install_ui drops hardcoded URLs; products populated dynamically in lifespan"
```

---

## Task 6: 平台 main.py lifespan 填充 products + install_ui 调用更新

**Files:**
- Modify: `xinyi_platform/main.py`
- Modify: `xinyi_platform/api/admin_clients.py`（_ui_ctx 去掉 manager_url）

**Interfaces:**
- 平台 lifespan 中直接查 DB 填充 products（不走 HTTP，平台就是 DB owner）

- [ ] **Step 1: 更新 install_ui 调用**

在 `xinyi_platform/main.py` 中找到 `install_ui(...)` 调用，改为：

```python
install_ui(
    app,
    current_service="platform",
    nav_menu=PLATFORM_NAV_MENU,
    brand=settings.brand_name,
    platform_url=settings.base_url,
    service_prefix="/xinyi",
)
```

删除 `manager_url=` 和 `docupipe_url=` 行。

- [ ] **Step 2: lifespan 中填充 products**

在 `xinyi_platform/main.py` 的 `lifespan` 函数中，`seed_admin_if_absent` 之后、`scheduler` 之前，加：

```python
    # Populate product switcher from DB
    from xinyi_platform.ui_common.service_discovery import build_product_list
    from xinyi_platform.models.business_client import BusinessClient, ClientStatus

    async with app_state.session_factory() as session:
        result = await session.execute(
            select(BusinessClient).where(
                BusinessClient.status == ClientStatus.ACTIVE,
                BusinessClient.base_url.isnot(None),
            ).order_by(BusinessClient.name)
        )
        active = result.scalars().all()
        active_dicts = [
            {
                "client_id": c.client_id,
                "name": c.name,
                "base_url": c.base_url,
                "home_path": c.home_path or "",
                "description": c.description or "",
            }
            for c in active
        ]
        app.state.ui["products"] = build_product_list(
            active_dicts,
            platform_url=settings.base_url,
            self_client_id="platform",
            self_name=settings.brand_name,
            self_home_path="/account",
        )
```

在文件顶部加 `from sqlalchemy import select`（如果未导入）。

- [ ] **Step 3: 加后台刷新 task**

在 scheduler 配置之后加：

```python
    async def _refresh_products():
        from xinyi_platform.ui_common.service_discovery import build_product_list
        async with app_state.session_factory() as session:
            result = await session.execute(
                select(BusinessClient).where(
                    BusinessClient.status == ClientStatus.ACTIVE,
                    BusinessClient.base_url.isnot(None),
                ).order_by(BusinessClient.name)
            )
            active = result.scalars().all()
            active_dicts = [
                {"client_id": c.client_id, "name": c.name, "base_url": c.base_url,
                 "home_path": c.home_path or "", "description": c.description or ""}
                for c in active
            ]
            app.state.ui["products"] = build_product_list(
                active_dicts,
                platform_url=settings.base_url,
                self_client_id="platform",
                self_name=settings.brand_name,
                self_home_path="/account",
            )

    scheduler.add_job(_refresh_products, "interval", minutes=5, id="refresh-products", replace_existing=True)
```

- [ ] **Step 4: 修复 admin_clients.py _ui_ctx**

在 `xinyi_platform/api/admin_clients.py` 的 `_ui_ctx` 函数中，删除 `"manager_url": ui["manager_url"],` 行（因为 install_ui 不再设置此 key）。

- [ ] **Step 5: 运行全部平台测试**

Run: `cd /Users/liling/src/lab/xinyi-platform && uv run pytest -v 2>&1 | tail -30`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/main.py xinyi_platform/api/admin_clients.py
git commit -m "feat: platform lifespan populates products from DB + install_ui call updated"
```

---

## Task 7: admin clients 页面加导航字段

**Files:**
- Modify: `xinyi_platform/templates/admin/clients.html`
- Modify: `xinyi_platform/api/admin_clients.py`（register_client 和 update_client 支持新字段）

- [ ] **Step 1: 更新 register_client 和 update_client 端点**

在 `xinyi_platform/api/admin_clients.py` 的 `register_client` 函数中，调用 `BusinessClientService.register` 后、返回前，如果有新字段就更新：

```python
@router.post("")
async def register_client(
    body: dict = Body(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        client, raw_secret = await BusinessClientService.register(
            session,
            client_id=body["client_id"],
            name=body["name"],
            redirect_uris=body.get("redirect_uris", []),
            logout_url=body.get("logout_url"),
        )
        # Update navigation fields if provided
        if body.get("base_url"):
            client.base_url = body["base_url"]
        if body.get("home_path"):
            client.home_path = body["home_path"]
        if body.get("description"):
            client.description = body["description"]
        await session.commit()
    except ClientConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "id": str(client.id),
        "client_id": client.client_id,
        "client_secret": raw_secret,
        "name": client.name,
        "redirect_uris": client.redirect_uris,
        "logout_url": client.logout_url,
        "base_url": getattr(client, "base_url", None),
        "home_path": getattr(client, "home_path", None),
        "description": getattr(client, "description", None),
    }
```

在 `update_client` 函数中，现有的 `if "name" in body:` 块后加：

```python
    if "base_url" in body:
        client.base_url = body["base_url"]
    if "home_path" in body:
        client.home_path = body["home_path"]
    if "description" in body:
        client.description = body["description"]
```

并在返回 dict 中加入 `"base_url": client.base_url, "home_path": client.home_path, "description": client.description`。

- [ ] **Step 2: 更新模板**

在 `xinyi_platform/templates/admin/clients.html` 中找到新建 client 的模态框表单，加三个输入框：

```html
<div class="form-group">
    <label>base_url</label>
    <input type="text" name="base_url" placeholder="http://hm:8001/hindsight">
</div>
<div class="form-group">
    <label>home_path</label>
    <input type="text" name="home_path" placeholder="/dashboard">
</div>
<div class="form-group">
    <label>description</label>
    <input type="text" name="description" placeholder="RAG 记忆库">
</div>
```

在 client 列表表格中也加一列显示 `base_url`（可选，看现有表格结构）。

- [ ] **Step 3: Commit**

```bash
cd /Users/liling/src/lab/xinyi-platform
git add xinyi_platform/api/admin_clients.py xinyi_platform/templates/admin/clients.html
git commit -m "feat: admin clients page supports base_url, home_path, description fields"
```

---

## Task 8: hindsight-manager 集成

**Files:**
- Modify: `hindsight_manager/config.py`
- Modify: `hindsight_manager/main.py`

**Interfaces:**
- Consumes: `xinyi_platform.ui_common.service_discovery` 的四个函数
- Produces: HM 启动时自动注册 + 发现 + 后台刷新

- [ ] **Step 1: config.py 加 registration_token**

在 `hindsight_manager/config.py` 的 `Settings` 类中，`refresh_token_ttl_days: int = 7` 之后加：

```python
    registration_token: str = ""
```

- [ ] **Step 2: main.py lifespan 加自动注册 + 发现**

在 `hindsight_manager/main.py` 的 `lifespan` 函数中，`scheduler.start()` 之前加：

```python
    # Auto-registration + service discovery
    from xinyi_platform.ui_common.service_discovery import (
        derive_client_secret,
        register_self,
        fetch_active_clients,
        build_product_list,
    )

    if settings.registration_token:
        # Derive client_secret from registration token
        settings.oauth_client_secret = derive_client_secret(
            settings.registration_token,
            settings.oauth_client_id,
        )

        # Register with platform
        await register_self(
            platform_url=settings.platform_url,
            registration_token=settings.registration_token,
            client_metadata={
                "client_id": settings.oauth_client_id,
                "name": "Hindsight Manager",
                "redirect_uris": [settings.oauth_redirect_uri],
                "logout_url": f"{settings.base_url}/hindsight/auth/logout",
                "base_url": f"{settings.base_url}/hindsight",
                "home_path": "/dashboard",
                "description": "RAG 记忆库",
            },
        )

    # Fetch active clients and populate product switcher
    active = await fetch_active_clients(
        settings.platform_url,
        settings.oauth_client_id,
        settings.oauth_client_secret,
    )
    if app.state.ui:
        app.state.ui["products"] = build_product_list(
            active,
            platform_url=settings.platform_url,
            self_client_id=settings.oauth_client_id,
            self_name="Hindsight Manager",
            self_home_path="/dashboard",
        )

    async def _refresh_products():
        active = await fetch_active_clients(
            settings.platform_url,
            settings.oauth_client_id,
            settings.oauth_client_secret,
        )
        if app.state.ui:
            app.state.ui["products"] = build_product_list(
                active,
                platform_url=settings.platform_url,
                self_client_id=settings.oauth_client_id,
                self_name="Hindsight Manager",
                self_home_path="/dashboard",
            )

    scheduler.add_job(_refresh_products, "interval", minutes=5, id="refresh-products", replace_existing=True)
```

- [ ] **Step 3: 更新 install_ui 调用**

在 `hindsight_manager/main.py` 中找到 `install_ui(...)` 调用，删除 `manager_url=` 和 `docupipe_url=` 参数（如果存在）。

- [ ] **Step 4: 运行 HM 测试确认无破坏**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest -v 2>&1 | tail -20`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add hindsight_manager/config.py hindsight_manager/main.py
git commit -m "feat: HM auto-registers with platform + dynamic product switcher"
```

---

## Task 9: docupipe-manager 集成

**Files:**
- Modify: `docupipe_manager/config.py`
- Modify: `docupipe_manager/main.py`

**Interfaces:**
- 与 Task 8 完全对称，client_id = "docupipe-prod"，home_path = "/projects"

- [ ] **Step 1: config.py 加 registration_token**

在 `docupipe_manager/config.py` 的 `Settings` 类中，`user_cache_ttl_seconds: int = 300` 之后加：

```python
    registration_token: str = ""
```

- [ ] **Step 2: main.py lifespan 加自动注册 + 发现**

在 `docupipe_manager/main.py` 的 `lifespan` 函数中，`app.state.engine = engine` 之后、`session_cleanup_task` 之前加：

```python
    # Auto-registration + service discovery
    from xinyi_platform.ui_common.service_discovery import (
        derive_client_secret,
        register_self,
        fetch_active_clients,
        build_product_list,
    )

    if settings.registration_token:
        settings.oauth_client_secret = derive_client_secret(
            settings.registration_token,
            settings.oauth_client_id,
        )

        await register_self(
            platform_url=settings.platform_url,
            registration_token=settings.registration_token,
            client_metadata={
                "client_id": settings.oauth_client_id,
                "name": "DocuPipe",
                "redirect_uris": [settings.oauth_redirect_uri],
                "logout_url": f"{settings.base_url}/docupipe/auth/logout",
                "base_url": f"{settings.base_url}/docupipe",
                "home_path": "/projects",
                "description": "文档管道调度",
            },
        )

    active = await fetch_active_clients(
        settings.platform_url,
        settings.oauth_client_id,
        settings.oauth_client_secret,
    )
    if hasattr(app.state, "ui") and app.state.ui:
        app.state.ui["products"] = build_product_list(
            active,
            platform_url=settings.platform_url,
            self_client_id=settings.oauth_client_id,
            self_name="DocuPipe",
            self_home_path="/projects",
        )

    # Note: DM doesn't have APScheduler, use asyncio task for periodic refresh
    async def _refresh_products_loop():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            try:
                active = await fetch_active_clients(
                    settings.platform_url,
                    settings.oauth_client_id,
                    settings.oauth_client_secret,
                )
                if hasattr(app.state, "ui") and app.state.ui:
                    app.state.ui["products"] = build_product_list(
                        active,
                        platform_url=settings.platform_url,
                        self_client_id=settings.oauth_client_id,
                        self_name="DocuPipe",
                        self_home_path="/projects",
                    )
            except Exception as e:
                logger.warning("product refresh failed: %s", e)

    product_refresh_task = asyncio.create_task(_refresh_products_loop())
```

在 shutdown 部分（yield 之后），取消 task：

```python
    product_refresh_task.cancel()
```

加在 `session_cleanup_task.cancel()` 之后。

- [ ] **Step 3: 更新 install_ui 调用**

在 `docupipe_manager/main.py` 中找到 `install_ui(...)` 调用，删除 `manager_url=` 和 `docupipe_url=` 参数。

- [ ] **Step 4: 运行 DM 测试确认无破坏**

Run: `cd /Users/liling/src/lab/docupipe-manager && uv run pytest -v 2>&1 | tail -20`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /Users/liling/src/lab/docupipe-manager
git add docupipe_manager/config.py docupipe_manager/main.py
git commit -m "feat: DM auto-registers with platform + dynamic product switcher"
```

---

## Task 10: 端到端验证 + 文档更新

**Files:**
- Modify: 三个仓库各自的 `.env.example`
- Verify: 手动启动三个服务验证流程

- [ ] **Step 1: 更新 .env.example**

在 `xinyi-platform/.env.example` 加：

```
# Auto-registration token (shared with all business services)
XINYI_PLATFORM_REGISTRATION_TOKEN=
```

在 `hindsight-manager/.env.example` 加：

```
# Auto-registration token (must match xinyi-platform's)
HINDSIGHT_MANAGER_REGISTRATION_TOKEN=
```

在 `docupipe-manager/.env.example` 加：

```
# Auto-registration token (must match xinyi-platform's)
DOCUPIPE_MANAGER_REGISTRATION_TOKEN=
```

- [ ] **Step 2: Commit .env.example 更新**

```bash
cd /Users/liling/src/lab/xinyi-platform && git add .env.example && git commit -m "docs: add REGISTRATION_TOKEN to .env.example"
cd /Users/liling/src/lab/hindsight-manager && git add .env.example && git commit -m "docs: add REGISTRATION_TOKEN to .env.example"
cd /Users/liling/src/lab/docupipe-manager && git add .env.example && git commit -m "docs: add REGISTRATION_TOKEN to .env.example"
```

- [ ] **Step 3: 生成共享 token 并配到三个 .env**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 输出例如: aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW3xY5zA7
```

将输出值分别配到三个 .env 文件的 REGISTRATION_TOKEN 变量。

- [ ] **Step 4: 本地启动验证**

```bash
# 启动 xinyi-platform
cd /Users/liling/src/lab/xinyi-platform && uv run alembic upgrade head && uv run uvicorn xinyi_platform.main:app --port 8000

# 启动 hindsight-manager
cd /Users/liling/src/lab/hindsight-manager && uv run uvicorn hindsight_manager.main:app --port 8001

# 启动 docupipe-manager
cd /Users/liling/src/lab/docupipe-manager && uv run uvicorn docupipe_manager.main:app --port 8002
```

验证：
1. 检查 xinyi-platform 日志是否有注册请求
2. `psql` 查 `SELECT client_id, base_url, last_seen_at FROM xinyi.business_clients` 确认两条记录
3. 浏览器访问 HM → product switcher 显示 HM + DM + 平台
4. 浏览器访问 DM → product switcher 显示 HM + DM + 平台
5. 从 HM 的 switcher 点 DM → 静默 SSO 跳转成功

- [ ] **Step 5: 更新设计文档状态**

在 `docs/superpowers/specs/2026-06-25-auto-registration-and-service-discovery-design.md` 中将状态改为 `已实现`。

---

## Self-Review

**Spec coverage check:**
- §1 数据模型变更 → Task 1 ✓
- §2 自动注册机制 → Task 2 (派生公式) + Task 3 (register_or_update) + Task 4 (注册端点) ✓
- §3 服务发现端点 → Task 4 (GET /active) ✓
- §4 共享注册+发现模块 → Task 2 (service_discovery.py) + Task 5 (install_ui 改造) ✓
- §5 跨服务跳转 SSO → 无需代码改动，现有 OAuth2 已支持 ✓
- §6 HM/DM 改造 → Task 8 (HM) + Task 9 (DM) ✓
- §7 环境变量变更 → Task 10 (.env.example) ✓
- §8 优雅降级 → Task 2 (register_self/fetch 都 catch 异常返回 False/[]) ✓
- §9 admin clients 页面 → Task 7 ✓
- §10 安全考量 → Task 4 (verify_registration_token) ✓
- §11 测试策略 → Task 2 (9 tests) + Task 3 (2 tests) + Task 4 (4 tests) ✓

**Placeholder scan:** 无 TBD/TODO。所有代码步骤都包含完整代码块。

**Type consistency:**
- `derive_client_secret(token, client_id) -> str` — Task 2 定义，Task 4/8/9 消费，签名一致 ✓
- `register_self(platform_url, registration_token, client_metadata) -> bool` — Task 2 定义，Task 8/9 消费，签名一致 ✓
- `fetch_active_clients(platform_url, client_id, client_secret) -> list[dict]` — Task 2 定义，Task 8/9 消费，签名一致 ✓
- `build_product_list(active_clients, *, platform_url, self_client_id, self_name, self_home_path) -> list[dict]` — Task 2 定义，Task 6/8/9 消费，签名一致 ✓
- `BusinessClientService.register_or_update(session, *, ...)` — Task 3 定义，Task 4 消费，签名一致 ✓
- `verify_registration_token` — Task 4 定义并使用 ✓
- `install_ui(app, *, current_service, nav_menu, brand, platform_url, service_prefix)` — Task 5 定义，Task 6/8/9 消费，签名一致 ✓

**Gaps:**
- DM 没有 APScheduler，用 asyncio task 做后台刷新（Task 9 Step 2 已处理）
- 平台自己的 install_ui 调用也需要更新（Task 6 Step 1 已处理）
- admin_clients.py 的 _ui_ctx 引用了 `ui["manager_url"]`（Task 6 Step 4 已处理）
