"""End-to-end check with organisation units, run on the KM host against the km-acl-test stack (simulator :8798, testbed + real KM Control admin API :8800).
CSIT (the simulator) provides the unit list and sends documents that name the units allowed to read them; a KM admin imports the list and assigns accounts to units
through the real KM Control admin API; the testbed then answers Chinese questions as accounts with different units. A temporary admin of the TEST stack is created
here with a random password that never leaves this process, and removed at the end."""
import http.cookiejar, json, secrets, subprocess, sys, time, urllib.request

SIM, WEB = "http://127.0.0.1:8798", "http://127.0.0.1:8800"
CTL = "/_control/api/auth"
ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail)[:200].replace("\n", " ") if detail != "" else ""), flush=True)


def call(base, path, body=None, jar=None, method=None, cookie=None):
    h = {"Content-Type": "application/json"}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method or ("POST" if body is not None else "GET"))
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)) if jar is not None else urllib.request.build_opener()
    try:
        with op.open(req, timeout=240) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
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
code, _b, hdr = call(WEB, CTL + "/login", {"username": "e2e-admin", "password": PW})
cookie = "; ".join(c.split(";")[0] for c in (hdr.get_all("Set-Cookie") or []))
check("admin signs in to the real KM Control login", code == 200 and "km_control_session" in cookie, code)


def admin(path, body=None, method=None):
    return call(WEB, CTL + path, body, method=method, cookie=cookie)


class User:
    def __init__(self, name):
        self.name, self.jar = name, http.cookiejar.CookieJar()
        call(WEB, "/testbed/login", {"user": name}, self.jar)

    def titles(self):
        c, d, _ = call(WEB, "/api/zones/admin/documents", jar=self.jar)
        return sorted(x["title"] for x in d.get("documents", [])) if c == 200 else None

    def ask(self, q):
        return call(WEB, "/testbed/ask", {"question": q}, self.jar)[1]


def denied(r):
    return str(r.get("stop_reason", "")).startswith("access_denied")


# ---- CSIT provides the unit list; a KM admin imports it
_, units, _ = call(SIM, "/api/units")
csv = "code,name\n" + "\n".join(f"{u['code']},{u['name']}" for u in units["units"])
c, r, _ = admin("/admin/units", {"csv": csv}, "PUT")
check("admin imports CSIT's unit list", c == 200 and r.get("total") == 5, r)
c, listed, _ = admin("/admin/units")
check("KM lists the imported units", {"hr", "rd", "qa", "fin", "eng-wifi"} <= {u["code"] for u in listed["units"]}, [u["code"] for u in listed["units"]])
c, us, _ = admin("/admin/users")
uid = {u["username"]: u["user_id"] for u in us["users"]}
for name, codes in {"alice": ["HR"], "bob": ["RD"], "carol": ["HR", "FIN"], "dave": []}.items():
    c, r, _ = admin(f"/admin/users/{uid[name]}/units", {"units": codes}, "PUT")
    check(f"admin assigns {name} -> {codes or 'no unit'}", c == 200 and r["units"] == sorted(x.lower() for x in codes), r)
check("no session, no admin API", call(WEB, CTL + "/admin/units")[0] == 401 and call(WEB, CTL + "/admin/units", {"csv": "X,x"}, method="PUT")[0] == 401)

# ---- CSIT sends documents with unit permissions
call(SIM, "/api/reset", {})
web('''
import httpx
b = "http://kb-qdrant:6333"
httpx.post(b + "/collections/km_acl_test_docs/points/delete?wait=true", json={"filter": {"must": [{"key": "source_system", "match": {"value": "CSIT"}}]}})
''')
DOCS = {
    "差旅報帳規定.txt": ("出差報帳規定:員工出差每日交通補助為新台幣三百元,住宿費以實報實銷為原則,需於出差結束後七個工作天內送出報帳。", {"mode": "Public"}),
    "薪資制度與調薪準則.txt": ("薪資制度與調薪準則(機密):各職等薪資級距與年度調薪原則,每年調薪幅度上限為百分之八,僅限人資部使用。", {"mode": "Restricted", "principals": "unit:HR"}),
    "無線晶片研發藍圖.txt": ("無線晶片研發藍圖(機密):下一代 Wi-Fi 7 晶片的規格目標與量產時程,預計二零二八年第二季量產,僅限研發部與品保部。", {"mode": "Restricted", "principals": "unit:RD, unit:QA"}),
    "採購預算核准流程.txt": ("採購預算核准流程(內部):單筆超過五十萬元的採購,需由財務部主管核准後才能下單。", {"mode": "Restricted", "principals": "unit:FIN"}),
    "舊版員工手冊.txt": ("舊版員工手冊:加班費計算方式為平日每小時一點三三倍,假日每小時兩倍。", None),
}
ids = {}
for name, (text, ac) in DOCS.items():
    spec = {"fileName": name, "contentText": text, "classification": {"l1": "90"}, "autoRun": True}
    if ac:
        spec["accessControl"] = ac
    ids[name] = call(SIM, "/api/docs", spec)[1]["id"]


def state(i):
    return next(x for x in call(SIM, "/api/state")[1]["docs"] if x["id"] == i)


def wait(pred, what, limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        if pred():
            return True
        time.sleep(4)
    print("TIMEOUT", what)
    return False


for name, i in ids.items():
    done = wait(lambda: "Completed" in (state(i)["jobs"][-1]["callbackStatuses"] if state(i)["jobs"] else []), name)
    check("KM completed ingestion of " + name, done)
t = {d["name"]: d for d in call(WEB, "/testbed/truth")[1]["documents"]}
check("units are stored on the documents (no unit appears for the public or unlabeled ones)", t["薪資制度與調薪準則.txt"]["allowed"] == ["unit:|hr"] and t["無線晶片研發藍圖.txt"]["allowed"] == ["unit:|qa", "unit:|rd"]
      and t["差旅報帳規定.txt"]["allowed"] == [] and t["舊版員工手冊.txt"]["acl_mode"] is None, {k: v["allowed"] for k, v in t.items()})

alice, bob, carol, dave = User("alice"), User("bob"), User("carol"), User("dave")
time.sleep(4)
check("alice (HR) sees public + HR document", alice.titles() == ["差旅報帳規定.txt", "薪資制度與調薪準則.txt"], alice.titles())
check("bob (RD) sees public + R&D document", bob.titles() == ["差旅報帳規定.txt", "無線晶片研發藍圖.txt"], bob.titles())
check("carol (HR + FIN) sees public + HR + purchasing", carol.titles() == ["差旅報帳規定.txt", "採購預算核准流程.txt", "薪資制度與調薪準則.txt"], carol.titles())
check("dave (no unit) sees the public document only", dave.titles() == ["差旅報帳規定.txt"], dave.titles())
check("the unlabeled handbook is visible to nobody", all("舊版員工手冊.txt" not in (u.titles() or []) for u in (alice, bob, carol, dave)))

Q_PAY, Q_ROAD, Q_BUY, Q_TRIP = "各職等薪資的年度調薪幅度上限是多少?", "下一代 Wi-Fi 7 晶片預計什麼時候量產?", "單筆採購超過多少錢要財務部主管核准?", "出差的交通補助每天多少錢?"
r = alice.ask(Q_PAY); check("alice (HR) is answered on the pay rules", not denied(r) and "八" in r.get("answer_main", ""), r.get("answer_main"))
r = bob.ask(Q_PAY); check("bob (RD) is refused on the pay rules", denied(r) and not r.get("citations"), r.get("answer_main"))
r = dave.ask(Q_PAY); check("dave (no unit) is refused on the pay rules", denied(r))
r = bob.ask(Q_ROAD); check("bob (RD) is answered on the chip roadmap", not denied(r) and "二零二八" in r.get("answer_main", "") or "2028" in r.get("answer_main", ""), r.get("answer_main"))
r = alice.ask(Q_ROAD); check("alice (HR) is refused on the chip roadmap", denied(r))
r = carol.ask(Q_BUY); check("carol (FIN) is answered on the purchasing flow", not denied(r) and "五十萬" in r.get("answer_main", "") or "50" in r.get("answer_main", ""), r.get("answer_main"))
r = alice.ask(Q_BUY); check("alice is refused on the purchasing flow", denied(r))
r = dave.ask(Q_TRIP); check("dave is answered on the public travel rules", not denied(r) and "三百" in r.get("answer_main", ""), r.get("answer_main"))

# ---- membership changes by the admin apply to the next question, no new login
admin(f"/admin/users/{uid['bob']}/units", {"units": ["HR"]}, "PUT")
time.sleep(3)
check("bob moved RD -> HR: sees the HR document, no longer the R&D one", bob.titles() == ["差旅報帳規定.txt", "薪資制度與調薪準則.txt"], bob.titles())
r = bob.ask(Q_PAY); check("bob is now answered on the pay rules", not denied(r) and "八" in r.get("answer_main", ""), r.get("answer_main"))
r = bob.ask(Q_ROAD); check("bob is now refused on the chip roadmap", denied(r))
admin(f"/admin/users/{uid['carol']}/units", {"units": []}, "PUT")
time.sleep(3)
check("carol's units removed: public document only", carol.titles() == ["差旅報帳規定.txt"], carol.titles())
c, r, _ = admin(f"/admin/users/{uid['dave']}/units", {"units": ["ghost"]}, "PUT")
check("assigning a unit that is not on CSIT's list is refused", c == 422, r)

# ---- CSIT changes a document's units
road = ids["無線晶片研發藍圖.txt"]
call(SIM, f"/api/docs/{road}/change", {"accessControl": {"mode": "Restricted", "principals": "unit:HR"}})
wait(lambda: "Completed" in (state(road)["changes"][-1]["callbackStatuses"] if state(road)["changes"] else []), "unit change")
time.sleep(3)
check("CSIT re-targets the roadmap to HR: HR members see it now", "無線晶片研發藍圖.txt" in (alice.titles() or []) and "無線晶片研發藍圖.txt" in (bob.titles() or []), alice.titles())
r = alice.ask(Q_ROAD); check("alice (HR) is now answered on the roadmap", not denied(r) and ("二零二八" in r.get("answer_main", "") or "2028" in r.get("answer_main", "")), r.get("answer_main"))

# ---- audit trail
out = web('''
from src.km_control import ControlRegistry
r = ControlRegistry.from_environment()
with r._connection() as c:
    print(",".join(sorted({x["event_type"] for x in c.execute("SELECT event_type FROM km_audit_events").fetchall()})))
''').stdout.strip()
check("unit import and every assignment are in the audit log", "units_imported" in out and "user_units_set" in out, out)

web('''
from src.km_control import ControlRegistry
r = ControlRegistry.from_environment()
with r._connection() as c:
    c.execute(r._sql("DELETE FROM km_users WHERE username = 'e2e-admin'"))
''')
print("\nOVERALL:", "ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
