"""Create a user account; the password is read without echo.

uv run python scripts/create_account.py --email a@example.edu --name 张三 [--admin] [--password-stdin]
docker compose -f deploy/compose.yaml exec api python scripts/create_account.py --email ...
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from services.api.auth import HASHER, normalize_email
from services.api.db import transaction
from services.api.models import User


def main():
    parser = argparse.ArgumentParser(description="创建账号")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", help="显示名，默认取邮箱前缀")
    parser.add_argument(
        "--admin", action="store_true", help="平台管理员（维护内置语料）"
    )
    parser.add_argument(
        "--password-stdin", action="store_true", help="从标准输入读取密码（脚本用）"
    )
    args = parser.parse_args()
    try:
        email = normalize_email(args.email)
    except ValueError as e:
        raise SystemExit(str(e))
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("密码（至少 12 位）：")
    if not 12 <= len(password) <= 1024:
        raise SystemExit("密码长度须为 12 到 1024 位")
    if not args.password_stdin and password != getpass.getpass("再次输入："):
        raise SystemExit("两次输入不一致")
    with transaction() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("账号已存在")
        user = User(
            email=email,
            display_name=args.name or email.split("@")[0],
            password_hash=HASHER.hash(password),
            is_admin=args.admin,
        )
        db.add(user)
        db.flush()
        print(f"已创建：{user.id} {email}{'（管理员）' if args.admin else ''}")


if __name__ == "__main__":
    main()
