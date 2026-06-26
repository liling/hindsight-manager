"""Tests for ManagerTenantExtension."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("hindsight_api", reason="ManagerTenantExtension runs inside the hindsight-api process; skip when running in this repo without it.")

from hindsight_api.extensions.tenant import AuthenticationError, TenantContext
from hindsight_api.models import RequestContext
from hindsight_manager.extensions.manager_tenant import ManagerTenantExtension


def _make_ext() -> ManagerTenantExtension:
    return ManagerTenantExtension({"manager_schema": "manager"})


def _mock_result(rows):
    """Create a mock DB result. *rows* is a list of tuples (one per row)."""
    result = MagicMock()
    result.fetchall.return_value = rows
    result.fetchone.return_value = rows[0] if rows else None
    return result


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=_mock_result([]))
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    engine.connect.return_value = conn
    return engine


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.run_migration = AsyncMock()
    ctx._database_url = "postgresql+asyncpg://localhost/test"
    return ctx


# ------------------------------------------------------------------
# authenticate
# ------------------------------------------------------------------


async def test_authenticate_valid_key(mock_context, mock_engine):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = mock_engine

    conn = mock_engine.connect.return_value
    conn.execute.return_value = _mock_result([("tenant_abc123",)])

    result = await ext.authenticate(RequestContext(api_key="hsm_testkey123"))
    assert isinstance(result, TenantContext)
    assert result.schema_name == "tenant_abc123"
    mock_context.run_migration.assert_called_once_with("tenant_abc123")


async def test_authenticate_missing_key(mock_context):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = MagicMock()

    with pytest.raises(AuthenticationError):
        await ext.authenticate(RequestContext(api_key=None))


async def test_authenticate_invalid_key(mock_context, mock_engine):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = mock_engine

    conn = mock_engine.connect.return_value
    conn.execute.return_value = _mock_result([])

    with pytest.raises(AuthenticationError):
        await ext.authenticate(RequestContext(api_key="hsm_badkey"))


async def test_authenticate_caches_schema(mock_context, mock_engine):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = mock_engine

    conn = mock_engine.connect.return_value
    conn.execute.return_value = _mock_result([("tenant_abc123",)])

    await ext.authenticate(RequestContext(api_key="hsm_testkey123"))
    await ext.authenticate(RequestContext(api_key="hsm_testkey123"))

    assert mock_context.run_migration.call_count == 1


# ------------------------------------------------------------------
# get_tenant_config
# ------------------------------------------------------------------


async def test_get_tenant_config(mock_context, mock_engine):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = mock_engine

    conn = mock_engine.connect.return_value
    conn.execute.return_value = _mock_result(
        [({"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-20250514"},)]
    )

    config = await ext.get_tenant_config(RequestContext(api_key="hsm_testkey123"))
    assert config["llm_provider"] == "anthropic"
    assert config["llm_model"] == "claude-sonnet-4-20250514"


async def test_get_tenant_config_no_key(mock_context):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = MagicMock()

    config = await ext.get_tenant_config(RequestContext(api_key=None))
    assert config == {}


# ------------------------------------------------------------------
# list_tenants
# ------------------------------------------------------------------


async def test_list_tenants(mock_context, mock_engine):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = mock_engine

    conn = mock_engine.connect.return_value
    conn.execute.return_value = _mock_result([("tenant_a",), ("tenant_b",)])

    tenants = await ext.list_tenants()
    assert len(tenants) == 2
    assert tenants[0].schema == "tenant_a"
    assert tenants[1].schema == "tenant_b"


async def test_list_tenants_no_engine(mock_context):
    ext = _make_ext()
    ext.set_context(mock_context)
    ext._engine = None

    tenants = await ext.list_tenants()
    assert tenants == []
