from unittest.mock import AsyncMock, patch

from hindsight_manager.auth.cas import CASClient


def test_get_login_url():
    client = CASClient(
        server_url="https://cas.example.com",
        service_url="https://manager.example.com/auth/cas/callback",
    )
    url = client.get_login_url()
    assert "cas.example.com" in url
    assert "service=" in url


async def test_validate_ticket_success():
    client = CASClient(
        server_url="https://cas.example.com",
        service_url="https://manager.example.com/auth/cas/callback",
    )
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
    client = CASClient(
        server_url="https://cas.example.com",
        service_url="https://manager.example.com/auth/cas/callback",
    )
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
