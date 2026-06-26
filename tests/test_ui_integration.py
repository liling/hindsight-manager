"""Smoke test: app has ui_common wired via install_ui."""
import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_app_has_ui_state_configured(client: AsyncClient):
    # install_ui runs at module level (not inside lifespan), so app.state.ui
    # is already populated without needing startup.
    ui = app.state.ui
    assert ui["current_service"] == "hindsight-manager"
    assert ui["brand"] == "Hindsight"
    # products is populated in lifespan by build_product_list() when
    # HINDSIGHT_MANAGER_REGISTRATION_TOKEN is set (see main.py lifespan).
    # At module level (no lifespan run) it remains an empty list.
    assert isinstance(ui["products"], list)


@pytest.mark.asyncio
async def test_static_ui_css_served(client: AsyncClient):
    resp = await client.get("/hindsight/_ui/static/ui.css")
    assert resp.status_code == 200
    assert "css" in resp.headers.get("content-type", "").lower() or "text" in resp.headers.get("content-type", "").lower()
