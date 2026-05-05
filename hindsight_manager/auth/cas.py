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
