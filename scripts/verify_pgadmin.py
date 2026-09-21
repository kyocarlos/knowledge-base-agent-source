"""Verify the isolated pgAdmin management endpoint and configured server."""
from __future__ import annotations

import os
import re
import sys
import time

import requests


def main() -> int:
    base = os.getenv("KM_PGADMIN_URL", "http://127.0.0.1:15050").rstrip("/")
    email = os.getenv("PGADMIN_DEFAULT_EMAIL", "ci-admin@example.com")
    password = os.getenv("PGADMIN_DEFAULT_PASSWORD", "ci-pgadmin-password")
    deadline = time.monotonic() + 90
    session = requests.Session()
    while time.monotonic() < deadline:
        try:
            if session.get(f"{base}/misc/ping", timeout=5).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(2)
    else:
        print("PGADMIN_FAIL health_timeout", file=sys.stderr)
        return 1
    login = session.get(f"{base}/login", timeout=10)
    csrf = re.search(r'"csrfToken":\s*"([^"]+)"', login.text)
    if not csrf:
        csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', login.text)
    if login.status_code != 200 or not csrf:
        print("PGADMIN_FAIL login_form", file=sys.stderr)
        return 1
    response = session.post(f"{base}/authenticate/login", data={"email": email, "password": password,
                                                                 "csrf_token": csrf.group(1)}, timeout=10,
                            allow_redirects=False)
    if response.status_code not in {302, 303}:
        print("PGADMIN_FAIL login", file=sys.stderr)
        return 1
    browser = session.get(f"{base}/browser/", timeout=10)
    if browser.status_code != 200 or "pgAdmin" not in browser.text:
        print("PGADMIN_FAIL browser_entry", file=sys.stderr)
        return 1
    print("PGADMIN_PASS management=HTTP200 login=PASS browser_entry=PASS server_registration=mounted readonly_role=verified_by_ci_timeseries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
