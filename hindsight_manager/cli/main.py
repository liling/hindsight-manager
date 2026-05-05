import typer

app = typer.Typer(name="hindsight-manager")

from hindsight_manager.cli.admin import app as admin_app  # noqa: E402
from hindsight_manager.cli.auth import app as auth_app  # noqa: E402
from hindsight_manager.cli.tenant import app as tenant_app  # noqa: E402

app.add_typer(admin_app, name="admin")
app.add_typer(auth_app, name="auth")
app.add_typer(tenant_app, name="tenant")
