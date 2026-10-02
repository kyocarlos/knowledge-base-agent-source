#!/usr/bin/env python3
"""Create/reset a KM account in exactly one configured data plane.

Passwords are read from stdin or a protected terminal prompt; they are never a
command-line argument or written to an env example.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from src.instance_isolation import require_instance_config
from src.km_accounts import AccountRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage one isolated KM account registry")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=("admin", "user"), default="user")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    config = require_instance_config()
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
    if not password:
        parser.error("password must not be empty")
    account = AccountRegistry.from_environment().create_or_reset(args.username, password, args.role)
    print(f"account updated: instance={config.instance_id} username={account.username} role={account.role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
