"""Stage B end-to-end check, run on the KM host against the km-acl-test stack (sim :8798, testbed :8800, both loopback only).
The simulator (as CSIT) sends documents with permissions through the real KM integration API + worker into the TEST collection; the testbed then
answers as different accounts through the real zone routes / ZoneCatalog / ZoneAgent and the real LLM gateway."""
import http.cookiejar, json, sys, time, urllib.request

SIM, WEB = "http://127.0.0.1:8798", "http://127.0.0.1:8800"
ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail)[:230] if detail != "" else ""), flush=True)


def call(base, path, body=None, jar=None, method=None):
    h = {"Content-Type": "application/json"}
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method or ("POST" if body is not None else "GET"))
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)) if jar is not None else urllib.request.build_opener()
    try:
        with op.open(req, timeout=240) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


class User:
    def __init__(self, name):
        self.name, self.jar = name, http.cookiejar.CookieJar()
        call(WEB, "/testbed/login", {"user": name}, self.jar)

    def titles(self):
        c, d = call(WEB, "/api/zones/admin/documents", jar=self.jar)
        return sorted(x["title"] for x in d.get("documents", [])) if c == 200 else None

    def ask(self, q):
        c, d = call(WEB, "/testbed/ask", {"question": q}, self.jar)
        return d


TXT = {
    "leave.txt": "Annual leave policy. Every employee receives fifteen days of annual leave per year. Leave requests must be submitted three days in advance.",
    "salary.txt": "2027 salary adjustment plan (confidential). The engineering department salary raise budget is 8 percent. Only HR directors and vice presidents may know this figure.",
    "review.txt": "Performance review calibration minutes (confidential). Distribution of employee performance ratings per department and the list of employees on improvement plans.",
    "legacy.txt": "Legacy employee handbook. Travel reimbursement rules: the daily transport allowance is 300 dollars.",
}
ACC = {"leave.txt": {"mode": "Public"}, "salary.txt": {"mode": "Restricted", "principals": "alice"}, "review.txt": {"mode": "Restricted", "principals": "group:hr"}, "legacy.txt": None}
Q_SALARY = "What is the 2027 salary raise budget for the engineering department?"
Q_LEAVE = "How many days of annual leave does each employee receive per year?"
Q_REVIEW = "What is the distribution of employee performance ratings and who is on an improvement plan?"
Q_TRAVEL = "What is the daily transport allowance for travel reimbursement?"

ids = {}
for name, text in TXT.items():
    spec = {"fileName": name, "contentText": text, "classification": {"l1": "90"}, "autoRun": True}
    if ACC[name]:
        spec["accessControl"] = ACC[name]
    c, d = call(SIM, "/api/docs", spec)
    assert c == 200, (name, c)
    ids[name] = d["id"]
print("simulator sent", len(ids), "documents (autoRun)", flush=True)


def doc_state(i):
    c, st = call(SIM, "/api/state")
    return next(x for x in st["docs"] if x["id"] == i)


def wait(pred, what, limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        if pred():
            return True
        time.sleep(4)
    print("TIMEOUT waiting for", what, flush=True)
    return False


for name, i in ids.items():
    done = wait(lambda: "Completed" in (doc_state(i)["jobs"][-1]["callbackStatuses"] if doc_state(i)["jobs"] else []), name + " ingestion")
    check("KM completed ingestion of " + name, done, (doc_state(i)["jobs"][-1]["callbackStatuses"] if doc_state(i)["jobs"] else []))

c, truth = call(WEB, "/testbed/truth")
t = {d["name"]: d for d in truth["documents"]}
check("test collection holds exactly the four documents, all in the admin zone", sorted(t) == sorted(TXT) and all(d["zone"] == "部門與公司文管專區" for d in t.values()), {k: v["zone"] for k, v in t.items()})
check("permission stored on every point of the documents", t["leave.txt"]["acl_mode"] == "Public" and t["salary.txt"]["acl_mode"] == "Restricted" and t["review.txt"]["acl_mode"] == "Restricted", {k: (v["acl_mode"], v["allowed"]) for k, v in t.items()})
check("old-style document carries no permission", t["legacy.txt"]["acl_mode"] is None)

alice, bob, carol, dave = User("alice"), User("bob"), User("carol"), User("dave")
time.sleep(4)   # past the catalog's cache window
check("bob sees only the public document", bob.titles() == ["leave.txt"], bob.titles())
check("alice sees public + her salary document", alice.titles() == ["leave.txt", "salary.txt"], alice.titles())
check("carol (hr group) sees public + review", carol.titles() == ["leave.txt", "review.txt"], carol.titles())
check("the unlabeled document is visible to nobody", all("legacy.txt" not in (u.titles() or []) for u in (alice, bob, carol, dave)))

r = bob.ask(Q_SALARY)
check("bob asking about the restricted salary plan is refused", str(r.get("stop_reason", "")).startswith("access_denied") and not r.get("citations"), r.get("answer_main"))
r = alice.ask(Q_SALARY)
check("alice gets the answer with the salary document cited", not str(r.get("stop_reason", "")).startswith("access_denied") and any("salary" in c["source"] for c in r.get("citations", [])) and "8" in r.get("answer_main", ""), r.get("answer_main"))
r = bob.ask(Q_LEAVE)
check("bob is answered about the public leave policy", not str(r.get("stop_reason", "")).startswith("access_denied") and any("leave" in c["source"] for c in r.get("citations", [])), r.get("answer_main"))
check("the answer to bob does not leak restricted facts", "8 percent" not in r.get("answer_main", "") and "improvement" not in r.get("answer_main", "").lower())
r = bob.ask(Q_REVIEW)
check("bob is refused on the hr-only review minutes", str(r.get("stop_reason", "")).startswith("access_denied"), r.get("answer_main"))
r = carol.ask(Q_REVIEW)
check("carol (hr group) is answered on the review minutes", not str(r.get("stop_reason", "")).startswith("access_denied") and any("review" in c["source"] for c in r.get("citations", [])), r.get("answer_main"))
r = alice.ask(Q_REVIEW)
check("alice (not in hr) is refused on the review minutes", str(r.get("stop_reason", "")).startswith("access_denied"), r.get("answer_main"))
r = carol.ask(Q_TRAVEL)
check("a question whose best source is the unlabeled document is refused (fail closed)", str(r.get("stop_reason", "")).startswith("access_denied"), r.get("answer_main"))

# ---- permission changes sent by the simulator (CSIT) while KM is running
sal = ids["salary.txt"]
call(SIM, "/api/docs/%s/change" % sal, {"accessControl": {"mode": "Restricted", "principals": "dave"}})
ok_change = wait(lambda: "Completed" in (doc_state(sal)["changes"][-1]["callbackStatuses"] if doc_state(sal)["changes"] else []), "revocation change")
check("KM accepted and completed the permission change (alice removed, dave added, version 2)", ok_change, doc_state(sal)["changes"][-1]["callbackStatuses"] if doc_state(sal)["changes"] else None)
time.sleep(4)
check("after revocation alice no longer sees the salary document", "salary.txt" not in (alice.titles() or []), alice.titles())
r = alice.ask(Q_SALARY)
check("after revocation alice is refused", str(r.get("stop_reason", "")).startswith("access_denied"), r.get("answer_main"))
r = dave.ask(Q_SALARY)
check("dave, newly allowed, is answered", not str(r.get("stop_reason", "")).startswith("access_denied") and "8" in r.get("answer_main", ""), r.get("answer_main"))
c, truth = call(WEB, "/testbed/truth")
check("stored permission is version 2", {d["name"]: d for d in truth["documents"]}["salary.txt"]["acl_version"] == 2)

call(SIM, "/api/docs/%s/change" % sal, {"accessControl": {"mode": "Public"}})
wait(lambda: len(doc_state(sal)["changes"]) >= 2 and "Completed" in doc_state(sal)["changes"][-1]["callbackStatuses"], "widening change")
time.sleep(4)
r = bob.ask(Q_SALARY)
check("after the document is made public, bob is answered", not str(r.get("stop_reason", "")).startswith("access_denied") and "8" in r.get("answer_main", ""), r.get("answer_main"))

check("no session, no access to the zone API", call(WEB, "/api/zones/admin/documents")[0] == 401)
print("\nOVERALL:", "ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
