#!/usr/bin/env python3
"""Create the initial Control admin without passing its password on a CLI."""
from __future__ import annotations
import argparse
import getpass
import sys
from src.km_control import ControlRegistry

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
    if not password:
        parser.error("password must not be empty")
    user = ControlRegistry.from_environment().bootstrap_admin(args.username, password)
    print(f"Control admin created: {user.username}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
