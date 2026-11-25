"""The CSIT simulator sends accessControl, and what it sends is exactly what KM's own request models accept and store (no network: httpx is stubbed)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import httpx
from src.csit_integration_v1.access_control import acl_payload, principal_key
from src.csit_integration_v1.doclib_models import DocLibRequest
from src.csit_integration_v1.v2_models import DocumentJobRequest, MetadataChangeRequest
from tools.csit_simulator.sim import Sim

ISS = "https://csit-sim:8443/"
SENT = []


class Resp:
    status_code = 202
    headers = {}
    text = "{}"

    def __init__(self, body=None):
        self._b = body or {}

    def json(self):
        return self._b


def fake_post(url, json=None, headers=None, timeout=None, **kw):
    SENT.append((url, json))
    return Resp({"csitJobId": (json or {}).get("csitJobId"), "kmJobId": "KM-X-1", "status": "Accepted", "changeId": (json or {}).get("changeId"), "kmChangeJobId": "KM-CHG-1"})


httpx.post = fake_post


def sim():
    SENT.clear()
    s = Sim("http://km.invalid", "tok")
    s.identity = SimpleNamespace(issuer=ISS, mint_for_km=lambda *a, **k: "tok")
    return s


def run(s, **spec):
    d = s.create_doc({"fileName": "a.txt", "contentText": "hello world", **spec})
    s.approve(d["id"]); s.archive(d["id"]); s.dispatch(d["id"])
    return d["id"]


def job_body():
    return next(b for u, b in SENT if "jobs" in u and "status" not in u)


def test_v13_notice_carries_the_permission_and_km_accepts_it():
    s = sim(); run(s, accessControl={"mode": "Restricted", "principals": "alice, group:hr, role:auditor"})
    body = job_body()
    req = DocLibRequest.model_validate(body)
    assert req.accessControl.mode == "Restricted" and req.accessControl.version == 1
    assert [(p.type, p.id, p.issuer) for p in req.accessControl.allowedPrincipals] == [("User", "alice", ISS), ("Group", "hr", ISS), ("Role", "auditor", ISS)]
    assert acl_payload(body)["allowed_principals"] == sorted([principal_key("User", ISS, "alice"), principal_key("Group", ISS, "hr"), principal_key("Role", ISS, "auditor")])


def test_v2_notice_carries_the_permission_and_km_accepts_it():
    s = sim(); run(s, sourceType="EquipmentAttachment", accessControl={"mode": "Public"})
    body = job_body()
    assert body["schemaVersion"] == "2.0" and DocumentJobRequest.model_validate(body).accessControl.mode == "Public"
    assert acl_payload(body) == {"acl_mode": "Public", "acl_version": 1, "allowed_principals": []}


def test_an_old_style_document_sends_no_accesscontrol_at_all():
    s = sim(); run(s)
    assert "accessControl" not in job_body() and acl_payload(job_body()) == {}
    d = s.view(next(iter(s.docs.values())))
    assert d["access"] is None


def test_changing_the_permission_sends_a_new_version_and_km_accepts_the_change():
    s = sim(); did = run(s, sourceType="EquipmentAttachment", accessControl={"mode": "Restricted", "principals": "alice"})
    s.change_metadata(did, {"accessControl": {"mode": "Restricted", "principals": "bob"}})
    url, body = [x for x in SENT if "metadata-changes" in x[0]][-1]
    req = MetadataChangeRequest.model_validate(body)
    assert req.accessControl.version == 2 and [p.id for p in req.accessControl.allowedPrincipals] == ["bob"] and "accessControl" in body["changedFields"]
    s.change_metadata(did, {"accessControl": {"mode": "Public"}})
    body = [x for x in SENT if "metadata-changes" in x[0]][-1][1]
    assert MetadataChangeRequest.model_validate(body).accessControl.version == 3 and body["accessControl"]["allowedPrincipals"] == []


def test_a_change_that_leaves_the_permission_alone_is_rejected_as_nothing_changed_and_keeps_the_version():
    s = sim(); did = run(s, sourceType="EquipmentAttachment", accessControl={"mode": "Restricted", "principals": "alice"})
    try:
        s.change_metadata(did, {"accessControl": {"mode": "Restricted", "principals": "alice"}})
    except Exception as e:  # noqa: BLE001
        assert "nothing changed" in str(getattr(e, "detail", e))
    else:
        raise AssertionError("an unchanged permission produced a change")
    assert s.docs[did]["access"]["version"] == 1


def test_a_metadata_change_for_tags_still_carries_the_current_permission_unchanged():
    s = sim(); did = run(s, sourceType="EquipmentAttachment", accessControl={"mode": "Restricted", "principals": "alice"})
    s.change_metadata(did, {"tags": ["wifi"]})
    body = [x for x in SENT if "metadata-changes" in x[0]][-1][1]
    assert body["accessControl"]["version"] == 1 and "accessControl" not in body["changedFields"]


def test_a_bad_mode_is_refused_by_the_simulator():
    s = sim()
    try:
        s.create_doc({"fileName": "a.txt", "contentText": "x", "accessControl": {"mode": "Everyone"}})
    except Exception as e:  # noqa: BLE001
        assert "Public or Restricted" in str(getattr(e, "detail", e))
    else:
        raise AssertionError("accepted a bad mode")


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn(); print("PASS", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print("FAIL", name, "->", type(e).__name__, str(e)[:300]); traceback.print_exc(limit=4)
    print("\nOVERALL:", "ALL PASS" if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)
