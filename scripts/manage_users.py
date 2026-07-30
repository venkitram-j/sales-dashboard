#!/usr/bin/env python3
"""Manage application login users (Authentication component).

There is no self-service sign-up UI by design; accounts are provisioned
through this script.

Usage:
    python scripts/manage_users.py add <username> [--password PASSWORD]
    python scripts/manage_users.py set-password <username> [--password PASSWORD]
    python scripts/manage_users.py activate <username>
    python scripts/manage_users.py deactivate <username>
    python scripts/manage_users.py list
    python scripts/manage_users.py purge-sessions

If --password is omitted for `add` / `set-password`, you'll be prompted
interactively (input is hidden) -- preferred over passing it on the command
line, which can leak into shell history.

Examples:
    python scripts/manage_users.py add jane.doe
    python scripts/manage_users.py set-password jane.doe
    python scripts/manage_users.py deactivate jane.doe
    python scripts/manage_users.py list
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import session_scope  # noqa: E402
from app.services.auth_service import (  # noqa: E402
    AuthService,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.utils.logging_config import configure_logging  # noqa: E402


def _prompt_password(confirm: bool = True) -> str:
    password = getpass.getpass("Password: ")
    if confirm:
        again = getpass.getpass("Confirm password: ")
        if password != again:
            print("Passwords do not match.", file=sys.stderr)
            raise SystemExit(1)
    return password


def cmd_add(args: argparse.Namespace) -> int:
    password = args.password or _prompt_password()
    try:
        with session_scope() as session:
            AuthService(session).create_user(args.username, password)
        print(f"User '{args.username}' created.")
        return 0
    except (UserAlreadyExistsError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_set_password(args: argparse.Namespace) -> int:
    password = args.password or _prompt_password()
    try:
        with session_scope() as session:
            AuthService(session).set_password(args.username, password)
        print(f"Password updated for '{args.username}'.")
        return 0
    except (UserNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_activate(args: argparse.Namespace, active: bool) -> int:
    try:
        with session_scope() as session:
            AuthService(session).set_active(args.username, active)
        state = "activated" if active else "deactivated"
        print(f"User '{args.username}' {state}.")
        return 0
    except UserNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_list(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        users = AuthService(session).list_users()
    if not users:
        print("No users found.")
        return 0
    print(f"{'USERNAME':<30} {'ACTIVE':<8} {'LAST LOGIN':<25} CREATED")
    for u in users:
        last_login = u.last_login_at.isoformat() if u.last_login_at else "-"
        print(f"{u.username:<30} {str(u.is_active):<8} {last_login:<25} {u.created_at.isoformat()}")
    return 0


def cmd_purge_sessions(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        count = AuthService(session).purge_expired_sessions()
    print(f"Removed {count} expired 'remember me' session(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage application login users.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a new user")
    p_add.add_argument("username")
    p_add.add_argument("--password", help="Plaintext password (prompted if omitted)")
    p_add.set_defaults(func=cmd_add)

    p_set = sub.add_parser("set-password", help="Change an existing user's password")
    p_set.add_argument("username")
    p_set.add_argument("--password", help="Plaintext password (prompted if omitted)")
    p_set.set_defaults(func=cmd_set_password)

    p_deact = sub.add_parser("deactivate", help="Disable a user's login access")
    p_deact.add_argument("username")
    p_deact.set_defaults(func=lambda a: cmd_activate(a, active=False))

    p_act = sub.add_parser("activate", help="Re-enable a user's login access")
    p_act.add_argument("username")
    p_act.set_defaults(func=lambda a: cmd_activate(a, active=True))

    p_list = sub.add_parser("list", help="List all users")
    p_list.set_defaults(func=cmd_list)

    p_purge = sub.add_parser(
        "purge-sessions", help="Delete expired 'remember me' session rows (safe to run periodically)"
    )
    p_purge.set_defaults(func=cmd_purge_sessions)

    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
