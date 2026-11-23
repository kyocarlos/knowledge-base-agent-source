"""Zone document permissions (experiment 2026-11-21), stage A: everything runs against an in-memory Qdrant, no KM service is touched.

Runs with pytest or plainly:  python tests/zone_acl/test_zone_acl.py
"""
import hashlib, math, os, re, sys, uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from src.csit_integration_v1.access_control import acl_payload, principal_key
from src.csit_integration_v1.doclib_models import DocLibRequest
from src.csit_integration_v1.v2_pipeline import V2QdrantWriter, metadata_payload
from src.zone_pages import acl
from src.zone_pages.agent import ZoneAgent, ACCESS_DENIED
from src.zone_pages.catalog import ZoneCatalog

ISS = "https://ad.example.test/"
ZONE = ["部門與公司文管專區"]
DIM = 256


def encode(texts):
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in re.findall(r"[A-Za-z0-9]+|[一-鿿]", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def principals(*pairs):
    return [{"type": k, "id": i, "issuer": ISS} for k, i in pairs]


def build():
    client = QdrantClient(":memory:")
    client.create_collection("km_csit_docs", vectors_config=VectorParams(size=DIM, distance=Distance.COSINE))
    writer = V2QdrantWriter(client, "km_csit_docs", encode, 1200)
    writer.ensure_index()
    docs = {}

    def add(name, text, access):
        did = str(uuid.uuid4())
        rp = {"classification": {"l1": {"id": 1, "name": "部門文管專區"}}, "source": {}}
        if access is not None:
            rp["accessControl"] = access
        job = {"event_id": str(uuid.uuid4()), "source_type": "DocumentLibraryFile", "source_entity_id": did, "document_id": did, "version": 1,
               "csit_job_id": str(uuid.uuid4()), "document_file_id": did, "original_file_name": name, "file_size_bytes": 10,
               "expected_sha256": hashlib.sha256(name.encode()).hexdigest(), "request_payload": rp}
        writer.write(text, job)
        docs[name] = did
    add("leave.txt", "annual leave policy: employees get fifteen days of annual leave per year", {"mode": "Public", "version": 1})
    add("salary.txt", "salary adjustment plan 2027: confidential raise budget for the engineering department", {"mode": "Restricted", "version": 1, "allowedPrincipals": principals(("User", "alice"))})
    add("hr-review.txt", "performance review calibration notes: confidential ratings of staff", {"mode": "Restricted", "version": 1, "allowedPrincipals": principals(("Group", "hr"))})
    add("legacy.txt", "legacy handbook: old travel reimbursement rules", None)          # delivered before permissions existed: unlabeled
    return client, writer, docs


def viewer(*pairs, admin=False):
    return acl.Viewer(frozenset(principal_key(k, ISS, i) for k, i in pairs), is_admin=admin)


ALICE, BOB, CAROL = viewer(("User", "alice")), viewer(("User", "bob")), viewer(("User", "carol"), ("Group", "hr"))


def names(catalog, v):
    return sorted(d["title"] for d in catalog.documents(ZONE, viewer=v))


# ---------------------------------------------------------------- contract / writer
def test_old_requests_without_accesscontrol_still_validate_and_new_ones_do_too():
    base = {"schemaVersion": "1.0", "sourceSystem": "CSIT", "eventType": "DocumentLibraryFileUploaded", "documentFileId": str(uuid.uuid4()), "csitJobId": str(uuid.uuid4()),
            "occurredAt": "2026-11-21T00:00:00+08:00", "file": {"originalFileName": "a.txt", "contentType": "text/plain", "fileSizeBytes": 3, "sha256": "a" * 64}}
    assert DocLibRequest.model_validate(base).accessControl is None
    ok = DocLibRequest.model_validate({**base, "accessControl": {"mode": "Restricted", "version": 2, "allowedPrincipals": [{"type": "User", "id": "u1", "issuer": ISS}]}})
    assert ok.accessControl.mode == "Restricted"
    for bad in ({"mode": "Everyone", "version": 1}, {"mode": "Public", "version": 0}, {"mode": "Restricted", "version": 1, "allowedPrincipals": [{"type": "Robot", "id": "x"}]}):
        try:
            DocLibRequest.model_validate({**base, "accessControl": bad})
        except ValueError:
            continue
        raise AssertionError("accepted an invalid accessControl: %r" % bad)


def test_payload_is_written_on_every_point_and_absent_when_not_sent():
    client, _w, docs = build()
    pts = {p.payload["doc_name"]: p.payload for p in client.scroll("km_csit_docs", limit=50, with_payload=True)[0]}
    assert pts["leave.txt"]["acl_mode"] == "Public" and pts["leave.txt"]["allowed_principals"] == []
    assert pts["salary.txt"]["allowed_principals"] == [principal_key("User", ISS, "alice")]
    assert "acl_mode" not in pts["legacy.txt"]


def test_principal_keys_ignore_case_and_trailing_slash_of_the_issuer():
    assert principal_key("User", "https://AD.example.test/", "ALICE") == principal_key("user", "https://ad.example.test", "alice")
    assert principal_key("User", ISS, "alice") != principal_key("Group", ISS, "alice")


# ---------------------------------------------------------------- the read side
def test_each_viewer_sees_only_what_the_permission_allows_and_unlabeled_is_hidden():
    client, _w, _d = build()
    c = ZoneCatalog(client, encode, enforce=True)
    assert names(c, BOB) == ["leave.txt"]
    assert names(c, ALICE) == ["leave.txt", "salary.txt"]
    assert names(c, CAROL) == ["hr-review.txt", "leave.txt"]
    assert "legacy.txt" not in names(c, ALICE)


def test_cache_is_per_permission_set_so_one_viewer_never_gets_anothers_documents():
    client, _w, _d = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=3600)
    assert "salary.txt" in names(c, ALICE)
    assert names(c, BOB) == ["leave.txt"]            # served inside the cache window, still without alice's document
    assert "salary.txt" in names(c, ALICE)


def test_search_never_returns_a_passage_of_a_document_the_viewer_may_not_read():
    client, _w, _d = build()
    c = ZoneCatalog(client, encode, enforce=True)
    assert all(h["doc"]["title"] != "salary.txt" for h in c.search("salary adjustment confidential raise", ZONE, 10, viewer=BOB))
    assert any(h["doc"]["title"] == "salary.txt" for h in c.search("salary adjustment confidential raise", ZONE, 10, viewer=ALICE))


def test_document_and_chunk_handles_do_not_open_other_peoples_documents():
    client, _w, docs = build()
    c = ZoneCatalog(client, encode, enforce=True)
    assert c.document(ZONE, docs["salary.txt"] + ":v1", viewer=BOB) is None
    doc = c.document(ZONE, docs["salary.txt"] + ":v1", viewer=ALICE)
    assert c.chunks(doc, viewer=ALICE)[1] > 0
    assert c.chunks(doc, viewer=BOB) == ([], 0)       # a handle alice obtained is useless to bob (and to alice once revoked)


def test_enforcement_fails_closed_when_the_caller_names_no_viewer():
    client, _w, _d = build()
    c = ZoneCatalog(client, encode, enforce=True)
    for call in (lambda: c.documents(ZONE), lambda: c.search("leave", ZONE), lambda: c.best_passage_is_restricted("leave", ZONE, None)):
        try:
            call()
        except PermissionError:
            continue
        raise AssertionError("a call without a viewer was served while enforcement is on")


def test_with_enforcement_off_everything_behaves_as_before():
    client, _w, _d = build()
    c = ZoneCatalog(client, encode)                   # default: enforce=False
    assert names(c, None) == ["hr-review.txt", "leave.txt", "legacy.txt", "salary.txt"]
    assert names(c, BOB) == names(c, None)            # a viewer is ignored while the flag is off
    assert acl.viewer_for({"sub": "x"}) is None       # KM_ZONE_ACL_ENFORCE unset


def test_admin_sees_nothing_extra_unless_that_is_switched_on():
    os.environ["KM_ZONE_ACL_ENFORCE"] = "1"
    try:
        v = acl.viewer_for({"sub": "root", "role": "admin"})
        assert not v.is_admin and not v.principals
        os.environ["KM_ZONE_ACL_ADMIN_SEES_ALL"] = "1"
        assert acl.viewer_for({"sub": "root", "role": "admin"}).is_admin
        assert acl.viewer_for({"sub": "u", "role": "user"}).is_admin is False
    finally:
        os.environ.pop("KM_ZONE_ACL_ENFORCE", None); os.environ.pop("KM_ZONE_ACL_ADMIN_SEES_ALL", None)


def test_a_failed_identity_lookup_narrows_access_never_widens_it():
    os.environ["KM_ZONE_ACL_ENFORCE"] = "1"
    try:
        def boom(_):
            raise RuntimeError("control db down")
        v = acl.viewer_for({"sub": "alice"}, lookup=boom)
        assert v is not None and not v.principals
    finally:
        os.environ.pop("KM_ZONE_ACL_ENFORCE", None)


# ---------------------------------------------------------------- the question: refused before any model call
class Model:
    def __init__(self):
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        return "根據資料 [S1]"


def ask(catalog, v, question, model):
    agent = ZoneAgent(catalog, model)
    events = []
    return agent.answer(task_id="t", zone_label="部門與公司文管專區", zone_names=ZONE, question=question, history=[], owner={"user_id": "u"}, file_records={}, emit=events.append, viewer=v)


def test_restricted_question_is_refused_and_the_model_never_sees_the_document():
    client, _w, _d = build()
    c, m = ZoneCatalog(client, encode, enforce=True), Model()
    r = ask(c, BOB, "salary adjustment plan confidential raise budget", m)
    assert r["answer_main"] == ACCESS_DENIED and r["citations"] == [] and not m.calls
    assert r["stop_reason"].startswith("access_denied")


def test_permitted_user_gets_the_answer_with_the_document_in_context():
    client, _w, _d = build()
    c, m = ZoneCatalog(client, encode, enforce=True), Model()
    r = ask(c, ALICE, "salary adjustment plan confidential raise budget", m)
    assert r["answer_main"] != ACCESS_DENIED and m.calls and "raise budget" in m.calls[0][-1]["content"]


def test_an_allowed_question_never_leaks_restricted_text_into_the_model_context():
    client, _w, _d = build()
    c, m = ZoneCatalog(client, encode, enforce=True), Model()
    r = ask(c, BOB, "how many days of annual leave per year", m)
    assert r["answer_main"] != ACCESS_DENIED and m.calls
    context = m.calls[0][-1]["content"]
    assert "fifteen days" in context and "raise budget" not in context and "ratings of staff" not in context and "travel reimbursement" not in context


# ---------------------------------------------------------------- permission changes (revocation / widening / replay)
def apply(writer, docs, name, access):
    payload = metadata_payload({"classification": {"l1": {"id": 1, "name": "部門文管專區"}}, "attributes": {"tags": [], "keywords": [], "displayName": None, "modelNumbers": [], "vendorReference": None},
                                "accessControl": access})
    did = docs[name]
    writer.apply_metadata(V2QdrantWriter.flt(did, did, 1), payload)


def test_revocation_takes_effect_on_the_next_question_and_an_old_change_cannot_undo_it():
    client, writer, docs = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=0)        # no cache window: the change is visible at once
    assert "salary.txt" in names(c, ALICE)
    apply(writer, docs, "salary.txt", {"mode": "Restricted", "version": 2, "allowedPrincipals": principals(("User", "dave"))})     # alice is removed
    assert "salary.txt" not in names(c, ALICE) and "salary.txt" in names(c, viewer(("User", "dave")))
    apply(writer, docs, "salary.txt", {"mode": "Restricted", "version": 1, "allowedPrincipals": principals(("User", "alice"))})     # replayed older change
    assert "salary.txt" not in names(c, ALICE)
    apply(writer, docs, "salary.txt", {"mode": "Public", "version": 3})                                                             # later widened to everyone
    assert "salary.txt" in names(c, BOB)


def test_a_metadata_change_without_accesscontrol_leaves_the_stored_permission_alone():
    client, writer, docs = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=0)
    apply(writer, docs, "salary.txt", None)
    assert "salary.txt" in names(c, ALICE) and "salary.txt" not in names(c, BOB)
    assert acl_payload({"accessControl": None}) == {}


def test_an_unlabeled_document_becomes_visible_once_csit_sends_its_permission():
    client, writer, docs = build()
    c = ZoneCatalog(client, encode, enforce=True, ttl=0)
    assert "legacy.txt" not in names(c, BOB)
    apply(writer, docs, "legacy.txt", {"mode": "Public", "version": 1})
    assert "legacy.txt" in names(c, BOB)


# ---------------------------------------------------------------- HTTP routes with simulated sessions
def test_routes_apply_the_permission_of_the_signed_in_session():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from src.web_api import zone_routes
    client, _w, docs = build()
    os.environ["KM_ZONE_ACL_ENFORCE"] = "1"
    users = {"alice": [principal_key("User", ISS, "alice")], "bob": [principal_key("User", ISS, "bob")], "carol": [principal_key("User", ISS, "carol"), principal_key("Group", ISS, "hr")]}
    real_lookup = acl.control_lookup
    acl.control_lookup = lambda sub: users.get(sub, [])        # the routes resolve principals through acl.control_lookup
    real_zones = acl.control_zone_lookup
    acl.control_zone_lookup = lambda sub: ["admin"] if sub in users else []      # zone-level grants: the three users may enter 部門與公司文管專區 only
    catalog = ZoneCatalog(client, encode, enforce=True, ttl=0)
    zone_routes._catalog = lambda: catalog
    app = FastAPI()

    @app.middleware("http")
    async def session(request: Request, call_next):
        who = request.headers.get("x-test-user")
        if who:
            request.state.km_identity = {"sub": who, "instance_id": "t", "role": "user"}
        return await call_next(request)
    app.include_router(zone_routes.router)
    http = TestClient(app)
    try:
        def get(path, user=None):
            return http.get(path, headers={"x-test-user": user} if user else {})
        assert get("/api/zones/admin/documents").status_code == 401                                     # no session
        assert get("/api/zones/admin/documents", "erin").status_code == 403 and get("/api/zones/cert/documents", "alice").status_code == 403   # no zone grant / other zone
        assert get("/api/zones/admin/documents", "alice").status_code == 200
        titles = lambda user: sorted(d["title"] for d in get("/api/zones/admin/documents", user).json()["documents"])
        assert titles("bob") == ["leave.txt"] and titles("alice") == ["leave.txt", "salary.txt"] and titles("carol") == ["hr-review.txt", "leave.txt"]
        assert get("/api/zones/admin/documents/" + docs["salary.txt"] + ":v1", "bob").status_code == 404
        assert get("/api/zones/admin/documents/" + docs["salary.txt"] + ":v1", "alice").status_code == 200
        assert get("/api/zones/admin/documents/%s:v1/chunks" % docs["salary.txt"], "bob").status_code == 404
        found = lambda user: [r["title"] if "title" in r else str(r) for r in http.post("/api/zones/admin/search", json={"query": "salary adjustment confidential raise"}, headers={"x-test-user": user}).json()["results"]]
        assert not any("salary" in t for t in found("bob")) and any("salary" in t for t in found("alice"))
        assert get("/api/zones/admin/documents/%s:v1/chunks" % docs["salary.txt"], "alice").json()["total"] > 0
        # a header naming another user is the test's own device; the real session middleware sets km_identity from the signed token only
    finally:
        os.environ.pop("KM_ZONE_ACL_ENFORCE", None)
        acl.control_lookup = real_lookup
        acl.control_zone_lookup = real_zones


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn()
            print("PASS", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print("FAIL", name, "->", type(e).__name__, str(e)[:300]); traceback.print_exc(limit=3)
    print("\nOVERALL:", "ALL PASS" if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)
