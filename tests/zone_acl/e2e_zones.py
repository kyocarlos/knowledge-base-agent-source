"""End-to-end check of the two permission layers on the km-acl-test stack: (1) which zones an account may enter, set by a KM admin in KM Control; (2) which documents of an
opened zone it may read (document units). Runs on the KM host against the test stack only. A temporary admin of the TEST stack is created with a random password that never
leaves this process and is removed at the end. Leaves the demo matrix (alice/bob/carol/dave) in place."""
import http.cookiejar, json, secrets, subprocess, sys, time, urllib.request

WEB = "http://127.0.0.1:8800"
CTL = "/_control/api/auth"
ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail)[:260].replace("\n", " ") if detail != "" else ""), flush=True)


def call(path, body=None, jar=None, method=None, cookie=None):
    h = {"Content-Type": "application/json"}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(WEB + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method or ("POST" if body is not None else "GET"))
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)) if jar is not None else urllib.request.build_opener()
    try:
        with op.open(req, timeout=240) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), e.headers
        except Exception:  # noqa: BLE001
            return e.code, {}, e.headers


def web(code, env=None):
    cmd = ["docker", "exec", "-i"] + sum([["-e", f"{k}={v}"] for k, v in (env or {}).items()], []) + ["km-acl-test-web", "python", "-c", code]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


PW = "E2e-" + secrets.token_urlsafe(18)
web('''
import os
from src.km_control import ControlRegistry
from src.km_accounts import hash_password
r = ControlRegistry.from_environment()
u = next((x for x in r.list_users() if x.username == "e2e-admin"), None) or r.register("e2e-admin", os.environ["E2E_PW"])
with r._connection() as c:
    c.execute(r._sql("UPDATE km_users SET status = 'active', is_admin = 1, password_hash = ? WHERE user_id = ?"), (hash_password(os.environ["E2E_PW"]), u.user_id))
''', {"E2E_PW": PW})
code, _b, hdr = call(CTL + "/login", {"username": "e2e-admin", "password": PW})
cookie = "; ".join(c.split(";")[0] for c in (hdr.get_all("Set-Cookie") or []))
check("admin signs in to the real KM Control login", code == 200 and "km_control_session" in cookie, code)


def admin(path, body=None, method=None):
    return call(CTL + path, body, method=method, cookie=cookie)


_, acc, _ = call("/testbed/accounts")
PAGE = {z["id"]: z["page"] for z in acc["zones"]}
LABEL = {z["page"]: z["label"] for z in acc["zones"]}
ALLPAGES = list(PAGE.values())
check("the nine KM zones exist (CSIT's names)", len(ALLPAGES) == 9 and LABEL["wifi"] == "WiFi 知識專區" and LABEL["csit"] == "產品驗證專區", LABEL)

c, zl, _ = admin("/admin/zones")
check("admin lists the nine zones to grant", c == 200 and [z["id"] for z in zl["zones"]] == list(PAGE), [z["id"] for z in zl.get("zones", [])])

c, us, _ = admin("/admin/users")
uid = {u["username"]: u["user_id"] for u in us["users"]}
MATRIX = {
    "alice": (["HR"], ["admin", "lab", "cert"]),
    "bob": (["RD"], ["wifi", "mobile", "broadband", "verification", "equipment", "lab"]),
    "carol": (["HR", "FIN"], ["admin", "equipment", "cert"]),
    "dave": ([], ["lab"]),
}
for name, (units, zones) in MATRIX.items():
    c1, r1, _ = admin(f"/admin/users/{uid[name]}/units", {"units": units}, "PUT")
    c2, r2, _ = admin(f"/admin/users/{uid[name]}/zones", {"zones": zones}, "PUT")
    check(f"admin sets {name}: units {units or 'none'}, zones {zones}", c1 == 200 and c2 == 200 and r2["zones"] == sorted(zones), (r1, r2))
c, us, _ = admin("/admin/users")
check("the admin list shows each account's zones", all(sorted(next(u for u in us["users"] if u["username"] == n)["zones"]) == sorted(z) for n, (_, z) in MATRIX.items()))
check("an unknown zone is refused", admin(f"/admin/users/{uid['dave']}/zones", {"zones": ["nope"]}, "PUT")[0] == 422)
check("no session, no admin API / no zone list", call(CTL + "/admin/zones")[0] == 401 and call(CTL + f"/admin/users/{uid['dave']}/zones", {"zones": ["wifi"]}, method="PUT")[0] == 401 and call("/api/zone-access")[0] == 401)

truth = call("/testbed/truth")[1]["documents"]
ZONE_PAGE_BY_NAME = {LABEL[p]: p for p in ALLPAGES}
UNIT_KEY = lambda u: "unit:|" + u.lower()


def expected_titles(units, page):
    keys = {UNIT_KEY(u) for u in units}
    return sorted(d["name"] for d in truth if ZONE_PAGE_BY_NAME.get(d["zone"]) == page and (d["acl_mode"] == "Public" or keys & set(d["allowed"] or [])))


class User:
    def __init__(self, name):
        self.name, self.jar = name, http.cookiejar.CookieJar()
        call("/testbed/login", {"user": name}, self.jar)

    def zones(self):
        c, d, _ = call("/api/zone-access", jar=self.jar)
        return sorted(z["page"] for z in d.get("zones", [])) if c == 200 else None

    def titles(self, page):
        c, d, _ = call(f"/api/zones/{page}/documents", jar=self.jar)
        return c, (sorted(x["title"] for x in d.get("documents", [])) if c == 200 else None)

    def ask(self, page, q):
        return call("/testbed/ask", {"question": q, "zone": page}, self.jar)[:2]


U = {n: User(n) for n in MATRIX}
time.sleep(4)
for n, (units, zones) in MATRIX.items():
    want = sorted(PAGE[z] for z in zones)
    check(f"{n}: the left navigation lists exactly the granted zones", U[n].zones() == want, U[n].zones())
    bad = []
    for p in ALLPAGES:
        c, t = U[n].titles(p)
        if p in want:
            if c != 200 or t != expected_titles(units, p):
                bad.append((p, c, t, expected_titles(units, p)))
        elif c != 403:
            bad.append((p, c))
    check(f"{n}: granted zones open and show only the documents of their units; every other zone answers 403 when called directly", not bad, bad[:2])

# the two layers together, in words
Q = "Telefonica 的 Veriwave 測試目前進行到什麼狀態?"
_, r = U["bob"].ask("equipment", Q)
check("bob (RD, may enter 設備儀器) is answered on the RD-only Veriwave presentation", not str(r.get("stop_reason", "")).startswith("access_denied") and bool(r.get("answer_main")) and bool(r.get("citations")), r.get("answer_main"))
_, r = U["carol"].ask("equipment", Q)
check("carol (FIN, may enter 設備儀器 but not in RD) is refused on it: she holds the zone, not the document", str(r.get("stop_reason", "")).startswith("access_denied") and not r.get("citations"), r.get("answer_main"))
c, r = U["alice"].ask("wifi", "WPS 的 PIN 驗證流程是什麼?")
check("alice has no WiFi zone: asking there is stopped with 403 before anything is searched", c == 403 and "answer_main" not in r, (c, r))
c, r = U["dave"].ask("lab", "設備借用流程是什麼?")
check("dave (no unit, only 實驗室管理) is answered on a public document of that zone", c == 200 and not str(r.get("stop_reason", "")).startswith("access_denied") and bool(r.get("answer_main")), r.get("answer_main"))
c, r = U["dave"].ask("equipment", "MT8862A 是什麼設備?")
check("dave asking in 設備儀器 (not granted) gets 403", c == 403, (c, r))

# an admin change applies to the next request, no new login
admin(f"/admin/users/{uid['dave']}/zones", {"zones": []}, "PUT")
time.sleep(3)
check("dave's last zone revoked: empty navigation, every zone 403", U["dave"].zones() == [] and all(U["dave"].titles(p)[0] == 403 for p in ALLPAGES), U["dave"].zones())
admin(f"/admin/users/{uid['dave']}/zones", {"zones": ["lab", "wifi"]}, "PUT")
time.sleep(3)
check("dave granted 實驗室管理 + WiFi: both appear, only public documents (no unit)", U["dave"].zones() == ["lab", "wifi"] and U["dave"].titles("wifi") == (200, expected_titles([], "wifi")), U["dave"].titles("wifi"))
admin(f"/admin/users/{uid['dave']}/zones", {"zones": MATRIX["dave"][1]}, "PUT")
admin(f"/admin/users/{uid['bob']}/zones", {"zones": MATRIX["bob"][1][:-1]}, "PUT")      # bob loses 實驗室管理
time.sleep(3)
check("bob loses 實驗室管理: gone from his navigation and 403 when called", "lab" not in (U["bob"].zones() or []) and U["bob"].titles("lab")[0] == 403, U["bob"].zones())
admin(f"/admin/users/{uid['bob']}/zones", {"zones": MATRIX["bob"][1]}, "PUT")
time.sleep(3)
check("bob given it back: it returns", "lab" in (U["bob"].zones() or []), U["bob"].zones())

# audit trail
web('''
from src.km_control import ControlRegistry
r = ControlRegistry.from_environment()
with r._connection() as c:
    n = c.execute(r._sql("SELECT COUNT(*) AS n FROM km_audit_events WHERE event_type = 'user_zones_set'")).fetchone()["n"]
print("AUDIT", n)
''')
res = web('''
from src.km_control import ControlRegistry
r = ControlRegistry.from_environment()
with r._connection() as c:
    print("AUDIT", c.execute(r._sql("SELECT COUNT(*) AS n FROM km_audit_events WHERE event_type = 'user_zones_set'")).fetchone()["n"])
''')
n = next((int(l.split()[1]) for l in res.stdout.splitlines() if l.startswith("AUDIT")), 0)
check("every zone change is audited", n >= 8, n)

# cleanup of the temporary admin only
web('''
from src.km_control import ControlRegistry
r = ControlRegistry.from_environment()
with r._connection() as c:
    u = next((x for x in r.list_users() if x.username == "e2e-admin"), None)
    if u:
        c.execute(r._sql("UPDATE km_users SET is_admin = 0, status = 'disabled', session_epoch = session_epoch + 1 WHERE user_id = ?"), (u.user_id,))
''')
print("OVERALL", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)
