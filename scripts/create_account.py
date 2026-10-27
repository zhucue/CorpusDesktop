"""Create a user account; the password is read without echo.

uv run python scripts/create_account.py --email a@example.edu --name 张三 [--admin] [--password-stdin]
docker compose -f deploy/compose.yaml exec api python scripts/create_account.py --email ...
批量（测试与运维脚本用）：每行一个 JSON {"email", "password", "name"?, "admin"?}，输出每行 {"id", "email"}：
docker compose -f deploy/compose.yaml exec -T api python scripts/create_account.py --batch < accounts.jsonl
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from services.api.auth import HASHER, normalize_email
from services.api.db import transaction
from services.api.models import User


def check_password(password):
    if not 12 <= len(password) <= 1024:
        raise SystemExit("密码长度须为 12 到 1024 位")


def add_user(db, email, password, name=None, admin=False):
    try:
        email = normalize_email(email)
    except ValueError as e:
        raise SystemExit(str(e))
    check_password(password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise SystemExit(f"账号已存在：{email}")
    user = User(
        email=email,
        display_name=name or email.split("@")[0],
        password_hash=HASHER.hash(password),
        is_admin=admin,
    )
    db.add(user)
    db.flush()
    return user


def batch():
    """All lines in one transaction: any bad line creates nothing."""
    rows = [json.loads(line) for line in sys.stdin if line.strip()]
    with transaction() as db:
        users = [
            add_user(db, r["email"], r["password"], r.get("name"), bool(r.get("admin")))
            for r in rows
        ]
        out = [{"id": str(u.id), "email": u.email} for u in users]
    for item in out:
        print(json.dumps(item))


def main():
    parser = argparse.ArgumentParser(description="创建账号")
    parser.add_argument("--email")
    parser.add_argument("--name", help="显示名，默认取邮箱前缀")
    parser.add_argument(
        "--admin", action="store_true", help="平台管理员（维护内置语料）"
    )
    parser.add_argument(
        "--password-stdin", action="store_true", help="从标准输入读取密码（脚本用）"
    )
    parser.add_argument(
        "--batch", action="store_true", help="从标准输入按行读取 JSON 批量创建"
    )
    args = parser.parse_args()
    if args.batch:
        return batch()
    if not args.email:
        parser.error("需要 --email 或 --batch")
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("密码（至少 12 位）：")
    check_password(password)
    if not args.password_stdin and password != getpass.getpass("再次输入："):
        raise SystemExit("两次输入不一致")
    with transaction() as db:
        user = add_user(db, args.email, password, args.name, args.admin)
        print(f"已创建：{user.id} {user.email}{'（管理员）' if args.admin else ''}")


if __name__ == "__main__":
    main()
