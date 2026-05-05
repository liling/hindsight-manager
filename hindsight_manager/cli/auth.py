import os
from pathlib import Path

import httpx
import typer

app = typer.Typer()

CONFIG_DIR = Path.home() / ".hindsight-manager"
SESSION_FILE = CONFIG_DIR / "session"


def _get_base_url() -> str:
    return os.environ.get("HINDSIGHT_MANAGER_URL", "http://localhost:8001")


def _save_session(base_url: str, token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(f"{base_url}\n{token}")


def _load_session() -> tuple[str, str] | None:
    if not SESSION_FILE.exists():
        return None
    lines = SESSION_FILE.read_text().strip().split("\n")
    if len(lines) != 2:
        return None
    return lines[0], lines[1]


def _get_auth_headers() -> dict[str, str]:
    session = _load_session()
    if not session:
        typer.echo("Not logged in. Run 'hindsight-manager auth login' first.", err=True)
        raise typer.Exit(1)
    base_url, token = session
    return {"Cookie": f"hindsight_session={token}"}


@app.command()
def login():
    base_url = _get_base_url()
    username = typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True)

    try:
        resp = httpx.post(
            f"{base_url}/auth/login",
            json={"provider": "local", "username": username, "password": password},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        typer.echo(f"Login failed: {e}", err=True)
        raise typer.Exit(1)

    data = resp.json()
    _save_session(base_url, data["token"])
    typer.echo(f"Logged in as {data['user']['username']}")


@app.command()
def logout():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    typer.echo("Logged out")


@app.command()
def me():
    session = _load_session()
    if not session:
        typer.echo("Not logged in.", err=True)
        raise typer.Exit(1)
    base_url, token = session
    try:
        resp = httpx.get(f"{base_url}/auth/me", headers={"Cookie": f"hindsight_session={token}"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        typer.echo(f"Request failed: {e}", err=True)
        raise typer.Exit(1)

    user = resp.json()
    typer.echo(f"ID:          {user['id']}")
    typer.echo(f"Username:    {user['username']}")
    typer.echo(f"Display:     {user['display_name']}")
    typer.echo(f"Auth:        {user['auth_provider']}")
