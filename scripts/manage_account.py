"""Create or disable local accounts via the migration identity; passwords use getpass."""

import argparse
import getpass
import os

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from services.api.auth import HASHER, normalize_email
from services.api.db import lock_actor
from services.api.models import LoginSession, User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "disable"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--platform-admin", action="store_true")
    args = parser.parse_args()
    email = normalize_email(args.email)
    engine = create_engine(os.environ["MIGRATION_DATABASE_URL"], hide_parameters=True)
    with Session(engine) as session, session.begin():
        if session.scalar(text("SELECT current_user")) != "corpus_owner":
            raise RuntimeError(
                "Account management requires the dedicated corpus_owner identity"
            )
        user = session.scalar(select(User).where(User.email == email))
        if args.action == "disable":
            if not user:
                raise SystemExit("Account does not exist")
            lock_actor(session, user.id)
            user.is_active = False
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            print("Account disabled and sessions revoked")
        else:
            if user:
                raise SystemExit("Account already exists")
            password = getpass.getpass("Password (at least 12 characters): ")
            if len(password) < 12 or len(password) > 1024:
                raise SystemExit("Password must contain 12 to 1024 characters")
            if password != getpass.getpass("Repeat password: "):
                raise SystemExit("Passwords do not match")
            user = User(
                email=email,
                password_hash=HASHER.hash(password),
                is_platform_admin=args.platform_admin,
            )
            session.add(user)
            session.flush()
            print(f"Account created: {user.id}")


if __name__ == "__main__":
    main()
