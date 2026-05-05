"""Manager Tenant Extension for Hindsight.

Authenticates API keys against the hindsight-manager metadata schema
and resolves per-tenant configuration.

Configuration via environment variables:
    HINDSIGHT_API_TENANT_EXTENSION=hindsight_manager.extensions.manager_tenant:ManagerTenantExtension
    HINDSIGHT_API_TENANT_MANAGER_SCHEMA=manager

Usage:
    Applications pass their API key in the Authorization header:
    curl -H "Authorization: Bearer hsm_..." https://your-hindsight-server/v1/default/banks/my-bank/memories/recall

    Make sure hindsight-manager is on the Python path:
    PYTHONPATH=/path/to/hindsight-manager hindsight-api
"""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hindsight_api.extensions.tenant import (
    AuthenticationError,
    Tenant,
    TenantContext,
    TenantExtension,
)
from hindsight_api.models import RequestContext

logger = logging.getLogger(__name__)

__all__ = ["ManagerTenantExtension"]


class ManagerTenantExtension(TenantExtension):
    """TenantExtension that validates API keys from hindsight-manager metadata.

    Reads tenant metadata (API keys, per-tenant config, active tenant list)
    from a ``manager`` PostgreSQL schema managed by the hindsight-manager
    service.  On first access, each tenant's schema is lazily provisioned
    by running the standard Alembic migration tree.
    """

    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self._manager_schema: str = config.get("manager_schema", "manager")
        self._initialized_schemas: set[str] = set()
        self._engine: AsyncEngine | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Create an async SQLAlchemy engine from the application database URL."""
        db_url = getattr(self.context, "_database_url", None)
        if not db_url:
            logger.warning("No database URL available for ManagerTenantExtension")
            return
        # Ensure we use asyncpg driver for async SQLAlchemy engine
        for prefix in ("postgresql+psycopg2://", "postgresql://"):
            if db_url.startswith(prefix):
                db_url = "postgresql+asyncpg://" + db_url[len(prefix):]
                break
        self._engine = create_async_engine(db_url, pool_pre_ping=True)
        logger.info(
            "ManagerTenantExtension initialized (schema=%s)",
            self._manager_schema,
        )

    async def on_shutdown(self) -> None:
        """Dispose the async engine."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, context: RequestContext) -> TenantContext:
        """Look up the API key hash in ``manager.api_keys`` and return tenant context.

        If the corresponding tenant schema has not been provisioned yet, the
        full Alembic migration tree is executed for that schema before the
        first request is served.

        Raises:
            AuthenticationError: If the key is missing, the extension is not
                initialised, or the key hash is not found.
        """
        api_key = context.api_key
        if not api_key:
            raise AuthenticationError("Missing API key")

        if not self._engine:
            raise AuthenticationError("Extension not initialized")

        key_hash = sha256(api_key.encode()).hexdigest()
        schema = self._manager_schema

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT t.schema_name
                    FROM {schema}.api_keys ak
                    JOIN {schema}.tenants t ON ak.tenant_id = t.id
                    WHERE ak.key_hash = :key_hash AND t.status = 'ACTIVE'
                    """
                ),
                {"key_hash": key_hash},
            )
            row = result.fetchone()
            if not row:
                raise AuthenticationError("Invalid API key")

            schema_name: str = row[0]

        # Provision schema on first access
        if schema_name not in self._initialized_schemas:
            await self.context.run_migration(schema_name)
            self._initialized_schemas.add(schema_name)
            logger.info("Schema provisioned: %s", schema_name)

        return TenantContext(schema_name=schema_name)

    # ------------------------------------------------------------------
    # Per-tenant configuration
    # ------------------------------------------------------------------

    async def get_tenant_config(self, context: RequestContext) -> dict[str, Any]:
        """Return per-tenant config overrides from ``manager.tenants.config``."""
        api_key = context.api_key
        if not api_key or not self._engine:
            return {}

        key_hash = sha256(api_key.encode()).hexdigest()
        schema = self._manager_schema

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT t.config
                    FROM {schema}.api_keys ak
                    JOIN {schema}.tenants t ON ak.tenant_id = t.id
                    WHERE ak.key_hash = :key_hash AND t.status = 'ACTIVE'
                    """
                ),
                {"key_hash": key_hash},
            )
            row = result.fetchone()
            if not row or not row[0]:
                return {}
            return row[0]

    # ------------------------------------------------------------------
    # Tenant discovery
    # ------------------------------------------------------------------

    async def list_tenants(self) -> list[Tenant]:
        """List all active tenants from ``manager.tenants``."""
        if not self._engine:
            return []
        schema = self._manager_schema

        async with self._engine.connect() as conn:
            result = await conn.execute(text(f"SELECT schema_name FROM {schema}.tenants WHERE status = 'ACTIVE'"))
            return [Tenant(schema=row[0]) for row in result.fetchall()]
