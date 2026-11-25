"""Organisation units: CSIT's unit list is imported into KM Control, a KM admin assigns accounts to units, and a document readable by a unit is readable by its members.
Everything runs in-process (SQLite control store, in-memory Qdrant); no KM service is touched. Run: python tests/zone_acl/test_units.py"""
import hashlib, os, sys, tempfile, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="km-units-")
os.environ["KM_CONTROL_DB_URL"] = "sqlite:///" + os.path.join(TMP, "control.db")
for k in ("KM_CONTROL_SESSION_SIGNING_KEY", "KM_ENTRY_SESSION_SIGNING_KEY", "KM_OIDC_BINDING_SIGNING_KEY"):
    os.environ[k] = "t" * 48

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from test_zone_acl import DIM, ZONE, encode
from src.csit_integration_v1.access_control import acl_payload, principal_key
from src.csit_integration_v1.doclib_models import DocLibRequest
from src.csit_integration_v1.v2_pipeline import V2QdrantWriter
from src.km_control import ControlError, ControlRegistry
from src.zone_pages import acl
from src.zone_pages.catalog import ZoneCatalog

REG = ControlRegistry.from_environment()
PW = "Test-only-pw-" + uuid.uuid4().hex[:8]       # throw-away password of this test's own temporary accounts


def make_user(name, admin=False):
    u = REG.register(name, PW)
    with REG._connection() as c:
        c.execute(REG._sql("UPDATE km_users SET status = 'active', is_admin = ? WHERE user_id = ?"), (1 if admin else 0, u.user_id))
    return u


ADMIN, ALICE, BOB, CAROL = make_user("admin1", True), make_user("alice"), make_user("bob"), make_user("carol")


def audit_types():
    with REG._connection() as c:
        return [r["event_type"] for r in c.execute("SELECT event_type FROM km_audit_events ORDER BY occurred_at, rowid").fetchall()]


# ---------------------------------------------------------------- the registry
def test_import_assign_and_look_up_units_case_insensitively():
    r = REG.import_units(ADMIN.user_id, [{"code": "HR", "name": "人資部"}, {"code": "RD", "name": "研發部"}, {"code": " QA ", "name": "品保部"}])
    assert r == {"added": 3, "updated": 0, "deactivated": 0, "total": 3}
    assert [u["code"] for u in REG.list_units()] == ["hr", "qa", "rd"]
    assert REG.set_user_units(ADMIN.user_id, BOB.user_id, ["HR", "rd"]) == ["hr", "rd"]
    assert REG.units_for(BOB.user_id) == ["hr", "rd"] and REG.unit_keys_for(BOB.user_id) == ["unit:|hr", "unit:|rd"]
    assert REG.units_for(ALICE.user_id) == []
    again = REG.import_units(ADMIN.user_id, [{"code": "HR", "name": "人資部"}])
    assert again["added"] == 0 and again["updated"] == 0


def test_an_unknown_unit_or_account_is_refused_and_nothing_changes():
    for call in (lambda: REG.set_user_units(ADMIN.user_id, BOB.user_id, ["nope"]), lambda: REG.set_user_units(ADMIN.user_id, "no-such-user", ["hr"]),
                 lambda: REG.import_units(ADMIN.user_id, []), lambda: REG.import_units(ADMIN.user_id, [{"code": "  ", "name": "x"}])):
        try:
            call()
        except ControlError:
            continue
        raise AssertionError("accepted an invalid unit request")
    assert REG.units_for(BOB.user_id) == ["hr", "rd"]


def test_a_deactivated_unit_stops_counting_and_every_change_is_audited():
    REG.import_units(ADMIN.user_id, [{"code": "HR", "name": "人資部"}, {"code": "QA", "name": "品保部"}], deactivate_missing=True)      # RD is no longer in CSIT's list
    assert REG.units_for(BOB.user_id) == ["hr"] and not next(u for u in REG.list_units() if u["code"] == "rd")["active"]
    try:
        REG.set_user_units(ADMIN.user_id, CAROL.user_id, ["rd"])
    except ControlError:
        pass
    else:
        raise AssertionError("assigned an inactive unit")
    REG.import_units(ADMIN.user_id, [{"code": "RD", "name": "研發部"}])
    assert REG.units_for(BOB.user_id) == ["hr", "rd"]                  # back in the list: the membership counts again
    types = audit_types()
    assert "units_imported" in types and "user_units_set" in types


# ---------------------------------------------------------------- the admin API (real router, real login)
def http():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.control_auth_routes import router
    app = FastAPI()
    app.include_router(router, prefix="/_control")
    return TestClient(app, base_url="https://testserver")


def login(client, name):
    r = client.post("/_control/api/auth/login", json={"username": name, "password": PW})
    assert r.status_code == 200, (name, r.status_code, r.text[:120])
    return client


def test_admin_api_imports_csv_assigns_units_and_lists_them():
    c = login(http(), "admin1")
    r = c.put("/_control/api/auth/admin/units", json={"csv": "code,name\nFIN,財務部\nENG-WIFI,研發部/無線組\n"})
    assert r.status_code == 200 and r.json()["added"] == 2, r.text
    assert {"fin", "eng-wifi"} <= {u["code"] for u in c.get("/_control/api/auth/admin/units").json()["units"]}
    r = c.put(f"/_control/api/auth/admin/users/{CAROL.user_id}/units", json={"units": ["FIN", "eng-wifi"]})
    assert r.status_code == 200 and r.json()["units"] == ["eng-wifi", "fin"], r.text
    users = {u["username"]: u for u in c.get("/_control/api/auth/admin/users").json()["users"]}
    assert users["carol"]["units"] == ["eng-wifi", "fin"] and users["bob"]["units"] == ["hr", "rd"]
    assert c.put(f"/_control/api/auth/admin/users/{CAROL.user_id}/units", json={"units": ["ghost"]}).status_code == 422


def test_only_an_admin_session_can_read_or_change_units():
    anon = http()
    assert anon.get("/_control/api/auth/admin/units").status_code == 401
    assert anon.put("/_control/api/auth/admin/units", json={"csv": "X,x"}).status_code == 401
    bob = login(http(), "bob")
    assert bob.get("/_control/api/auth/admin/units").status_code == 403
    assert bob.put(f"/_control/api/auth/admin/users/{BOB.user_id}/units", json={"units": ["hr"]}).status_code == 403


# ---------------------------------------------------------------- permission on documents that name units
def build():
    client = QdrantClient(":memory:")
    client.create_collection("km_csit_docs", vectors_config=VectorParams(size=DIM, distance=Distance.COSINE))
    writer = V2QdrantWriter(client, "km_csit_docs", encode, 1200)

    def add(name, text, access):
        did = str(uuid.uuid4())
        rp = {"classification": {"l1": {"id": 1, "name": "部門文管專區"}}, "source": {}}
        if access:
            rp["accessControl"] = access
        writer.write(text, {"event_id": str(uuid.uuid4()), "source_type": "DocumentLibraryFile", "source_entity_id": did, "document_id": did, "version": 1, "csit_job_id": str(uuid.uuid4()),
                            "document_file_id": did, "original_file_name": name, "file_size_bytes": 10, "expected_sha256": hashlib.sha256(name.encode()).hexdigest(), "request_payload": rp})
        return did
    docs = {"all.txt": add("all.txt", "company wide notice about the office closing on friday", {"mode": "Public", "version": 1}),
            "hr.txt": add("hr.txt", "hr only: salary bands and promotion rules for staff", {"mode": "Restricted", "version": 1, "allowedPrincipals": [{"type": "Unit", "id": "HR"}]}),
            "rd.txt": add("rd.txt", "research and development roadmap for the next wireless chip", {"mode": "Restricted", "version": 1, "allowedPrincipals": [{"type": "Unit", "id": "rd"}, {"type": "Unit", "id": "QA"}]}),
            "fin.txt": add("fin.txt", "finance budget approval workflow for purchasing", {"mode": "Restricted", "version": 1, "allowedPrincipals": [{"type": "Unit", "id": "FIN"}, {"type": "User", "id": "alice", "issuer": "https://ad.example/"}]})}
    return client, docs


def titles(catalog, user):
    os.environ["KM_ZONE_ACL_ENFORCE"] = "1"
    try:
        v = acl.viewer_for({"sub": user.user_id, "role": "user"}, lookup=acl.control_lookup)
        return sorted(d["title"] for d in catalog.documents(ZONE, viewer=v))
    finally:
        os.environ.pop("KM_ZONE_ACL_ENFORCE", None)


def test_documents_naming_units_are_readable_by_members_of_those_units_only():
    client, _docs = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=0)
    # state from the earlier tests: bob = hr + rd, carol = fin + eng-wifi, alice = none
    assert titles(c, ALICE) == ["all.txt"]
    assert titles(c, BOB) == ["all.txt", "hr.txt", "rd.txt"]
    assert titles(c, CAROL) == ["all.txt", "fin.txt"]


def test_a_membership_change_applies_to_the_next_question_without_a_new_login():
    client, _docs = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=0)
    assert "hr.txt" not in titles(c, ALICE)
    REG.set_user_units(ADMIN.user_id, ALICE.user_id, ["hr"])
    assert "hr.txt" in titles(c, ALICE)
    REG.set_user_units(ADMIN.user_id, ALICE.user_id, [])
    assert "hr.txt" not in titles(c, ALICE)


def test_a_failed_unit_lookup_leaves_the_account_with_public_documents_only():
    client, _docs = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=0)
    os.environ["KM_ZONE_ACL_ENFORCE"] = "1"
    try:
        def boom(_):
            raise RuntimeError("control db down")
        v = acl.viewer_for({"sub": BOB.user_id, "role": "user"}, lookup=boom)
        assert sorted(d["title"] for d in c.documents(ZONE, viewer=v)) == ["all.txt"]
    finally:
        os.environ.pop("KM_ZONE_ACL_ENFORCE", None)


# ---------------------------------------------------------------- contract
def test_contract_accepts_unit_principals_and_keys_ignore_case_and_provider():
    base = {"schemaVersion": "1.0", "sourceSystem": "CSIT", "eventType": "DocumentLibraryFileUploaded", "documentFileId": str(uuid.uuid4()), "csitJobId": str(uuid.uuid4()),
            "occurredAt": "2026-11-22T00:00:00+08:00", "file": {"originalFileName": "a.txt", "contentType": "text/plain", "fileSizeBytes": 3, "sha256": "a" * 64}}
    req = DocLibRequest.model_validate({**base, "accessControl": {"mode": "Restricted", "version": 1, "allowedPrincipals": [{"type": "Unit", "id": "HR"}, {"type": "Unit", "id": "ENG-WiFi"}]}})
    assert acl_payload(req.model_dump(mode="json"))["allowed_principals"] == ["unit:|eng-wifi", "unit:|hr"]
    assert principal_key("Unit", "https://whatever/", " HR ") == principal_key("unit", None, "hr")


def test_simulator_parses_unit_principals_without_a_provider():
    from types import SimpleNamespace
    from tools.csit_simulator.sim import Sim
    s = Sim("http://km.invalid", "tok")
    s.identity = SimpleNamespace(issuer="https://csit-sim:8443/")
    ac = s._access_from({"mode": "Restricted", "principals": "unit:HR, unit:RD, alice, group:ops"})
    assert [(p["type"], p["id"], p["issuer"]) for p in ac["allowedPrincipals"]] == [("Unit", "HR", None), ("Unit", "RD", None), ("User", "alice", "https://csit-sim:8443/"), ("Group", "ops", "https://csit-sim:8443/")]


if __name__ == "__main__":
    failed = 0
    for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]:
        try:
            fn(); print("PASS", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print("FAIL", name, "->", type(e).__name__, str(e)[:300]); traceback.print_exc(limit=4)
    print("\nOVERALL:", "ALL PASS" if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)
