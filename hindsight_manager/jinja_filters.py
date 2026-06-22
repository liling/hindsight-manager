from pathlib import Path

from fastapi.templating import Jinja2Templates

from hindsight_manager.config import Settings

_STATIC_ROOT = Path("hindsight_manager/static")


def _asset_url(url_path: str) -> str:
    rel = url_path.removeprefix("/static/")
    try:
        mtime = int((_STATIC_ROOT / rel).stat().st_mtime)
    except OSError:
        return url_path
    return f"{url_path}?v={mtime}"


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory="hindsight_manager/templates")
    templates.env.filters["asset_url"] = _asset_url
    templates.env.globals["platform_url"] = Settings().platform_url
    return templates
