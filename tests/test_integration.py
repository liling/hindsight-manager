"""Integration test scaffold for the full user/tenant/API key flow.

Requires a running PostgreSQL with the manager schema.
Run with: HINDSIGHT_MANAGER_DATABASE_URL=... HINDSIGHT_MANAGER_JWT_SECRET=test-secret uv run pytest tests/test_integration.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
