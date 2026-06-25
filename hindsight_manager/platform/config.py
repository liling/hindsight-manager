from dataclasses import dataclass


@dataclass
class PlatformSettings:
    platform_url: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_redirect_uri: str

    @classmethod
    def from_app_settings(cls, settings) -> "PlatformSettings":
        return cls(
            platform_url=settings.platform_url,
            oauth_client_id=settings.oauth_client_id,
            oauth_client_secret=settings.oauth_client_secret,
            oauth_redirect_uri=f"{settings.base_url}/hindsight{settings.oauth_redirect_uri}",
        )
