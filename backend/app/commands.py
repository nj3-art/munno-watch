import re
from datetime import datetime, timezone

import click
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import AuditLog, User


@click.command("create-admin")
@click.option("--username", prompt=True)
@click.option("--email", prompt=True)
def create_admin_command(username: str, email: str) -> None:
    """Create an administrator using an interactively entered password."""
    username = username.strip()
    email = email.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
        raise click.ClickException(
            "Username must be 3 to 32 letters, numbers or underscores."
        )
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise click.ClickException("Enter a valid email address.")
    if db.session.scalar(
        select(User.id).where(or_(User.username == username, User.email == email))
    ):
        raise click.ClickException("A user with that username or email already exists.")

    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < 12 or len(password) > 128:
        raise click.ClickException("Password must be between 12 and 128 characters.")
    administrator = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_admin=True,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.session.add(administrator)
    try:
        db.session.flush()
        db.session.add(
            AuditLog(
                actor_user_id=administrator.id,
                action="administrator.created",
                entity_type="user",
                entity_id=administrator.id,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise click.ClickException("Could not create the administrator; verify the account is unique.") from error
    click.echo(f"Administrator account created for {username}.")
