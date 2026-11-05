
"""Create or update a RescueMesh user.

python -m scripts.seed_users --username prakalya --role coordinator

To change an existing user's password or role:
python -m scripts.seed_users --username prakalya --role coordinator --reset
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.roles import ALL_ROLES
from backend.app.security import pwd

MIN_PASSWORD_LENGTH = 10


def upsert_user(
    db: Session,
    username: str,
    role: str,
    password: str,
    reset: bool = False
) -> str:

    if role not in ALL_ROLES:
        raise ValueError(
            f"role must be one of: {', '.join(ALL_ROLES)}"
        )

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )

    if len(password.encode()) > 72:
        raise ValueError("password must be at most 72 bytes")

    user = db.scalar(
        select(User).where(User.username == username)
    )

    if user and not reset:
        raise ValueError(
            f"user '{username}' already exists "
            "(use --reset to change password or role)"
        )

    if user:
        user.role = role
        user.password_hash = pwd.hash(password)
        db.commit()
        return "updated"

    db.add(
        User(
            username=username,
            role=role,
            password_hash=pwd.hash(password)
        )
    )

    db.commit()
    return "created"


def main() -> int:

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    ap.add_argument("--username", required=True)
    ap.add_argument("--role", required=True, choices=ALL_ROLES)
    ap.add_argument("--reset", action="store_true")

    args = ap.parse_args()

    password = getpass.getpass("Password: ")

    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1

    try:
        with SessionLocal() as db:
            result = upsert_user(
                db,
                args.username,
                args.role,
                password,
                args.reset
            )

        print(
            f"User '{args.username}' {result} with role {args.role}."
        )

    except ValueError as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
