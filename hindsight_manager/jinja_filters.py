from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from hindsight_manager.config import Settings
from xinyi_platform.ui_common.install import _TEMPLATE_DIR as _UI_TEMPLATE_DIR

_STATIC_ROOT = Path("hindsight_manager/static")


def _asset_url(url_path: str) -> str:
    rel = url_path.removeprefix("/static/")
    try:
        mtime = int((_STATIC_ROOT / rel).stat().st_mtime)
    except OSError:
        return url_path
    return f"{url_path}?v={mtime}"


def make_templates() -> Jinja2Templates:
    business_dir = "hindsight_manager/templates"
    templates = Jinja2Templates(directory=business_dir)
    templates.env.loader = ChoiceLoader([
        FileSystemLoader(business_dir),
        FileSystemLoader(str(_UI_TEMPLATE_DIR)),
    ])
    templates.env.filters["asset_url"] = _asset_url
    templates.env.globals["platform_url"] = Settings().platform_url
    templates.env.globals["brand"] = Settings().brand_name
    return templates
