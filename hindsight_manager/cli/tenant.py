import os
from pathlib import Path

import httpx
import typer

app = typer.Typer()

CONFIG_DIR = Path.home() / ".hindsight-manager"
SESSION_FILE = CONFIG_DIR / "session"


def _get_base_url() -> str:
    return os.environ.get("HINDSIGHT_MANAGER_URL", "http://localhost:8001")


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
    _, token = session
    return {"Cookie": f"hindsight_session={token}"}


@app.command(name="list")
def list_tenants():
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants", headers=headers)
    resp.raise_for_status()
    tenants = resp.json()
    if not tenants:
        typer.echo("No tenants.")
        return
    for t in tenants:
        typer.echo(f"  {t['id'][:8]}  {t['name']}  ({t['schema_name']})  [{t['status']}]")


@app.command()
def create(name: str = typer.Option(..., "--name", help="Tenant name")):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(f"{base_url}/tenants", json={"name": name}, headers=headers)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"Created tenant: {t['name']} (schema: {t['schema_name']})")


@app.command()
def show(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}", headers=headers)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"ID:       {t['id']}")
    typer.echo(f"Name:     {t['name']}")
    typer.echo(f"Schema:   {t['schema_name']}")
    typer.echo(f"Status:   {t['status']}")
    typer.echo(f"Config:   {t['config'] or '(default)'}")


@app.command(name="delete")
def delete_tenant(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.delete(f"{base_url}/tenants/{tenant_id}", headers=headers)
    resp.raise_for_status()
    typer.echo("Tenant marked for deletion.")


@app.command(name="purge")
def purge_tenant(tenant_id: str):
    """彻底清空已软删除的租户（DROP SCHEMA，不可逆）。"""
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(f"{base_url}/admin/api/tenants/{tenant_id}/purge", headers=headers)
    if resp.status_code == 409:
        detail = resp.json().get("detail", "")
        typer.echo(
            f"无法清空：{detail}。请先运行 'hindsight-manager tenant delete {tenant_id}'。",
            err=True,
        )
        raise typer.Exit(1)
    if resp.status_code == 404:
        typer.echo("租户不存在。", err=True)
        raise typer.Exit(1)
    resp.raise_for_status()
    data = resp.json()
    dropped = data.get("schema_dropped")
    typer.echo(f"已清空租户 {tenant_id}（schema_dropped={dropped}）。")


@app.command()
def config_set(
    tenant_id: str,
    llm_provider: str | None = typer.Option(None),
    llm_model: str | None = typer.Option(None),
    llm_api_key: str | None = typer.Option(None),
    llm_base_url: str | None = typer.Option(None),
    embeddings_provider: str | None = typer.Option(None),
    embeddings_model: str | None = typer.Option(None),
):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    data = {}
    if llm_provider is not None:
        data["llm_provider"] = llm_provider
    if llm_model is not None:
        data["llm_model"] = llm_model
    if llm_api_key is not None:
        data["llm_api_key"] = llm_api_key
    if llm_base_url is not None:
        data["llm_base_url"] = llm_base_url
    if embeddings_provider is not None:
        data["embeddings_provider"] = embeddings_provider
    if embeddings_model is not None:
        data["embeddings_model"] = embeddings_model
    if not data:
        typer.echo("No config values specified.", err=True)
        raise typer.Exit(1)
    resp = httpx.patch(f"{base_url}/tenants/{tenant_id}", json=data, headers=headers)
    resp.raise_for_status()
    typer.echo("Config updated.")


@app.command()
def config_get(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}", headers=headers)
    resp.raise_for_status()
    t = resp.json()
    config = t.get("config") or {}
    if not config:
        typer.echo("No custom config (using server defaults).")
        return
    for k, v in config.items():
        display = v if "key" not in k.lower() else "***"
        typer.echo(f"  {k}: {display}")


# Member subcommands
member_app = typer.Typer()
app.add_typer(member_app, name="member")


@member_app.command(name="list")
def member_list(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/members", headers=headers)
    resp.raise_for_status()
    members = resp.json()
    for m in members:
        typer.echo(f"  {m['username']}  ({m['role']})")


@member_app.command(name="add")
def member_add(tenant_id: str, username: str, role: str = "member"):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(
        f"{base_url}/tenants/{tenant_id}/members",
        json={"username": username, "role": role},
        headers=headers,
    )
    resp.raise_for_status()
    typer.echo(f"Added {username} as {role}.")


@member_app.command(name="remove")
def member_remove(tenant_id: str, username: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/members", headers=headers)
    members = resp.json()
    target = next((m for m in members if m["username"] == username), None)
    if not target:
        typer.echo(f"User {username} not found in tenant.", err=True)
        raise typer.Exit(1)
    resp = httpx.delete(
        f"{base_url}/tenants/{tenant_id}/members/{target['user_id']}", headers=headers
    )
    resp.raise_for_status()
    typer.echo(f"Removed {username}.")


@member_app.command(name="role")
def member_role(tenant_id: str, username: str, role: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/members", headers=headers)
    members = resp.json()
    target = next((m for m in members if m["username"] == username), None)
    if not target:
        typer.echo(f"User {username} not found in tenant.", err=True)
        raise typer.Exit(1)
    resp = httpx.patch(
        f"{base_url}/tenants/{tenant_id}/members/{target['user_id']}",
        json={"role": role},
        headers=headers,
    )
    resp.raise_for_status()
    typer.echo(f"Updated {username} role to {role}.")


# API key subcommands
api_key_app = typer.Typer()
app.add_typer(api_key_app, name="api-key")


@api_key_app.command(name="create")
def api_key_create(tenant_id: str, name: str = typer.Option("default")):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.post(
        f"{base_url}/tenants/{tenant_id}/api-keys", json={"name": name}, headers=headers
    )
    resp.raise_for_status()
    data = resp.json()
    typer.echo(f"API Key created: {data['key']}")
    typer.echo("Save this key — it will not be shown again.", err=True)


@api_key_app.command(name="list")
def api_key_list(tenant_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.get(f"{base_url}/tenants/{tenant_id}/api-keys", headers=headers)
    resp.raise_for_status()
    keys = resp.json()
    if not keys:
        typer.echo("No API keys.")
        return
    for k in keys:
        typer.echo(f"  {k['id'][:8]}  {k['name']}  ({k['key_prefix']}...)")


@api_key_app.command(name="revoke")
def api_key_revoke(tenant_id: str, key_id: str):
    base_url = _get_base_url()
    headers = _get_auth_headers()
    resp = httpx.delete(
        f"{base_url}/tenants/{tenant_id}/api-keys/{key_id}", headers=headers
    )
    resp.raise_for_status()
    typer.echo("API key revoked.")
