import click

from . import db
from .billing import bill_all
from .models import User


def register_cli(app):
    @app.cli.command("bill")
    def bill():
        """Create monthly charges for all active contracts."""
        click.echo(f"Created {bill_all()} invoices")

    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("password")
    @click.option("--name", default=None)
    @click.option("--role", type=click.Choice(["admin", "collector"]), default="collector")
    def create_user(username, password, name, role):
        u = User(username=username, name=name or username, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Created {role} {username}")

    @app.cli.command("momo-sandbox-user")
    @click.option("--callback-host", default="example.com")
    def momo_sandbox_user(callback_host):
        """Provision MoMo sandbox API user/key using MOMO_SUBSCRIPTION_KEY."""
        from .momo import create_sandbox_user

        user, key = create_sandbox_user(
            app.config["MOMO_SUBSCRIPTION_KEY"], app.config["MOMO_BASE_URL"], callback_host
        )
        click.echo(f"MOMO_API_USER={user}\nMOMO_API_KEY={key}")
