import os
from pathlib import Path

import httpx
import typer

app = typer.Typer()

CONFIG_DIR = Path.home() / ".hindsight-manager"
SESSION_FILE = CONFIG_DIR / "session"


def _get_base_url() -> str:
    return os.environ.get("HINDSIGHT_MANAGER_URL", "http://localhost:8001")


def _get_auth_headers() -> dict[str, str]:
    if not SESSION_FILE.exists():
        typer.echo("Not logged in. Run 'hindsight-manager auth login' first.", err=True)
        raise typer.Exit(1)
    lines = SESSION_FILE.read_text().strip().split("\n")
    if len(lines) != 2:
        typer.echo("Invalid session. Run 'hindsight-manager auth login' first.", err=True)
        raise typer.Exit(1)
    _, token = lines
    return {"Cookie": f"hindsight_session={token}"}


@app.command(name="create-user")
def create_user(username: str, password: str = typer.Option(..., prompt=True, hide_input=True), display_name: str | None = None):
    """Create a local user. Requires admin API endpoint (TODO)."""
    typer.echo(f"User creation for '{username}' — use direct database insertion for now.")
    typer.echo("A dedicated admin API endpoint will be added in a future version.")
