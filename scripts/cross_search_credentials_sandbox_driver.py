"""Sandbox driver: per-user source credentials through Control Auth and CrossSearch.

Runs only inside deploy/cross-search-credentials/sandbox-compose.yaml against
mock sources. Prints PASS/FAIL lines and a latency summary; never prints secrets.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time
from http.cookies import SimpleCookie

import httpx

from src.km_control import ControlRegistry, issue_entry_session

CONTROL = "http://control:8000"
CROSS = "http://cross-api:8000"
MOCK = "https://mock-sources.sandbox.test:8443"
MOCK_CA = "/certs/ca.crt"
NAMES = ["alice", "bob", "carol", "dave", "erin"][: int(os.getenv("SANDBOX_USERS", "5"))]
ROUNDS = int(os.getenv("SANDBOX_ROUNDS", "3"))
SOURCES = ["confluence", "jira", "testrail"]
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f" ({detail})" if detail and not condition else ""), flush=True)
    if not condition:
        failures.append(name)


def wait_ready() -> None:
    for url in (CONTROL + "/api/auth/oidc/availability", CROSS + "/health"):
        for _ in range(60):
            try:
                if httpx.get(url, timeout=2).status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)


def control_login(username: str) -> str:
    response = httpx.post(CONTROL + "/api/auth/login", json={"username": username, "password": "strong-password-123"})
    response.raise_for_status()
    cookie = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookie.load(header)
    return cookie["km_control_session"].value


def link(session: str, source: str, username: str, secret: str) -> httpx.Response:
    return httpx.put(CONTROL + f"/api/auth/source-credentials/{source}", cookies={"km_control_session": session},
                     json={"username": username, "secret": secret, "auth_type": "basic"})


def entry_cookie(registry: ControlRegistry, user_id: str) -> str:
    user = registry.get_user(user_id)
    return issue_entry_session(user_id, "test", "user", user.session_epoch)


def query(entry: str, text: str = "throughput n78") -> tuple[int, dict, float]:
    started = time.monotonic()
    created = httpx.post(CROSS + "/api/cross-search/v1/queries", cookies={"km_entry_session": entry},
                         json={"query": text, "sources": SOURCES, "topK": 10}, timeout=10)
    if created.status_code != 202:
        return created.status_code, {}, time.monotonic() - started
    query_id = created.json()["queryId"]
    for _ in range(600):
        time.sleep(0.2)
        reply = httpx.get(CROSS + f"/api/cross-search/v1/queries/{query_id}", cookies={"km_entry_session": entry}, timeout=10)
        body = reply.json()
        if body.get("status") in ("completed", "failed"):
            return 200, body, time.monotonic() - started
    return 504, {}, time.monotonic() - started


def main() -> int:
    wait_ready()
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    users = {name: registry.create_active_with_grant(admin.user_id, name, "strong-password-123", "user", "test").user_id for name in NAMES}
    sessions = {name: control_login(name) for name in NAMES}

    # 1. First-time linking through the Control Auth page API; never echoes the secret.
    for name in NAMES:
        for source in SOURCES:
            response = link(sessions[name], source, name, f"{name}-pass")
            check(f"link {name}/{source}", response.status_code == 200 and f"{name}-pass" not in response.text, str(response.status_code))
    listed = httpx.get(CONTROL + "/api/auth/source-credentials", cookies={"km_control_session": sessions[NAMES[0]]})
    check("list hides secrets", listed.status_code == 200 and "pass" not in listed.text and "envelope" not in listed.text)

    # 2. Concurrency: every user queries at once for several rounds; no cross-user leakage.
    httpx.delete(MOCK + "/_mock/requests", verify=MOCK_CA)
    latencies, leaks, incomplete = [], [], []
    for round_index in range(ROUNDS):
        barrier = threading.Barrier(len(NAMES))
        outputs: dict[str, tuple[int, dict, float]] = {}

        def run(name: str) -> None:
            entry = entry_cookie(registry, users[name])
            barrier.wait()
            outputs[name] = query(entry)

        threads = [threading.Thread(target=run, args=(name,)) for name in NAMES]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for name, (status, body, elapsed) in outputs.items():
            latencies.append(elapsed)
            statuses = body.get("sourceStatus", {})
            if status != 200 or set(statuses.values()) != {"completed"}:
                incomplete.append((round_index, name, status, statuses))
            for item in body.get("results", []):
                if name not in item["title"].lower():
                    leaks.append((name, item["title"]))
    log = httpx.get(MOCK + "/_mock/requests", verify=MOCK_CA).json()["requests"]
    check("all concurrent queries completed for all sources", not incomplete, json.dumps(incomplete)[:400])
    check("no cross-user results", not leaks, str(leaks[:3]))
    check("every source request authenticated as a sandbox user", log and all(entry["user"] in NAMES for entry in log), str(len(log)))
    check("request count = users x rounds x sources", len(log) == len(NAMES) * ROUNDS * len(SOURCES), str(len(log)))
    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
    print(f"LATENCY n={len(latencies)} p50={statistics.median(latencies):.2f}s p95={p95:.2f}s max={max(latencies):.2f}s", flush=True)
    check("p95 wait+answer <= 120s (external sources only)", p95 <= 120, f"{p95:.1f}")

    # 3. One running query per user.
    entry = entry_cookie(registry, users[NAMES[0]])
    first = httpx.post(CROSS + "/api/cross-search/v1/queries", cookies={"km_entry_session": entry}, json={"query": "throughput", "sources": SOURCES})
    second = httpx.post(CROSS + "/api/cross-search/v1/queries", cookies={"km_entry_session": entry}, json={"query": "throughput", "sources": SOURCES})
    check("second concurrent query of same user -> 429", first.status_code == 202 and second.status_code == 429, f"{first.status_code}/{second.status_code}")
    time.sleep(4)

    # 4. Wrong credential: marked needs_relink once, then not retried against the source.
    victim = NAMES[1]
    link(sessions[victim], "jira", victim, "wrong-password")
    httpx.delete(MOCK + "/_mock/requests", verify=MOCK_CA)
    _, body, _ = query(entry_cookie(registry, users[victim]))
    check("rejected credential -> needs_relink", body.get("sourceStatus", {}).get("jira") == "needs_relink", json.dumps(body.get("sourceStatus")))
    _, body, _ = query(entry_cookie(registry, users[victim]))
    jira_calls = [e for e in httpx.get(MOCK + "/_mock/requests", verify=MOCK_CA).json()["requests"] if e["source"] == "jira"]
    check("needs_relink is not retried", body.get("sourceStatus", {}).get("jira") == "needs_relink" and len(jira_calls) == 1, str(len(jira_calls)))
    listed = httpx.get(CONTROL + "/api/auth/source-credentials", cookies={"km_control_session": sessions[victim]}).json()["sources"]
    check("user sees needs_relink", next(i for i in listed if i["source"] == "jira")["status"] == "needs_relink")
    link(sessions[victim], "jira", victim, f"{victim}-pass")
    _, body, _ = query(entry_cookie(registry, users[victim]))
    check("re-linking restores the source", body.get("sourceStatus", {}).get("jira") == "completed")

    # 5. Logout keeps credentials; next login works without re-entering them.
    name = NAMES[2]
    httpx.post(CONTROL + "/api/auth/logout", cookies={"km_control_session": sessions[name]})
    sessions[name] = control_login(name)
    listed = httpx.get(CONTROL + "/api/auth/source-credentials", cookies={"km_control_session": sessions[name]}).json()["sources"]
    check("credentials kept across logout/login", all(item["status"] == "active" for item in listed))
    _, body, _ = query(entry_cookie(registry, users[name]))
    check("query after re-login uses stored credentials", set(body.get("sourceStatus", {}).values()) == {"completed"})

    # 6. Disabled account / revoked grant: old entry session can no longer use credentials.
    name = NAMES[3]
    stale = entry_cookie(registry, users[name])
    registry.set_user_status(admin.user_id, users[name], "disabled")
    httpx.delete(MOCK + "/_mock/requests", verify=MOCK_CA)
    status, _, _ = query(stale)
    calls = httpx.get(MOCK + "/_mock/requests", verify=MOCK_CA).json()["requests"]
    check("disabled user cannot query or reach sources", status in (401, 403) and not calls, f"{status}/{len(calls)}")

    # 7. Unlinked source is explicit and never falls back to another identity.
    name = NAMES[4]
    httpx.delete(CONTROL + "/api/auth/source-credentials/testrail", cookies={"km_control_session": sessions[name]})
    _, body, _ = query(entry_cookie(registry, users[name]))
    check("unlinked source -> not_linked", body.get("sourceStatus", {}).get("testrail") == "not_linked")

    print("SANDBOX RESULT:", "PASS" if not failures else f"FAIL {failures}", flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
