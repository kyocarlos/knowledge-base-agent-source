from __future__ import annotations
import hashlib, json, subprocess, sys
from copy import deepcopy
from pathlib import Path
import pytest
from km_a2a_bridge.gate_a_execution_evidence import EvidenceError, verify_files

ROOT = Path(__file__).resolve().parents[1]

def acl_fixture():
    return {"schema_version":"1.0","captured_at":"2026-08-14T16:44:00+08:00","decision":"PASS","scope":"tailscale-control-plane-acl-only","source":{"type":"tailscale-admin-console","tailnet_admin":"kusanagi.huang@gmail.com"},"peer":{"km_ip":"100.65.63.58","anritsu_ip":"100.72.21.115","anritsu_tag":"tag:anritsu-a2a-poc"},"saved_grants":[{"src":["100.65.63.58"],"dst":["tag:anritsu-a2a-poc"],"ip":["tcp:8790"]},{"src":["100.65.63.58"],"dst":["tag:anritsu-a2a-poc"],"ip":["TCP:8792"]}],"saved_test":{"src":"100.65.63.58","accept":["TAG:ANRITSU-A2A-POC:8792"],"proto":"tcp"},"allow_any_anritsu_grant_present":False,"real_run_authorized":False,"next_authorized_step":"anritsu-apply-8792-and-disabled-transport-preflight","screenshots":{name:"a"*64 for name in ("policy-saved.png","grants-json.png","tests-saved.png","tests-json.png")}}

def execution_fixture(acl):
    if isinstance(acl, Path):
        acl = json.loads(acl.read_text())
    acl_bytes = json.dumps(acl, separators=(",", ":")).encode()
    return {"schema_version":"1.0","validation":"disabled_gate_a_execution","captured_at":"2026-08-14T17:32:00+08:00","decision":"PARTIAL-PASS-NO-GO","acl":{"source":"C:\\Users\\SSNR\\Desktop\\tailscale-acl-gate-result.json","protected_copy":"a2a-sidecar/runtime/evidence/tailscale-acl-gate-result-20260814.json","sha256":hashlib.sha256(acl_bytes).hexdigest(),"schema_version":"1.0","decision":"PASS","km_ip":"100.65.63.58","anritsu_ip":"100.72.21.115","tag":"tag:anritsu-a2a-poc","tcp_8792_grant":True,"allow_any":False,"real_run_authorized":False,"next_authorized_step":"anritsu-apply-8792-and-disabled-transport-preflight","screenshots_originals_present":False,"screenshot_hash_declarations_recomputed":False,"screenshot_note":"Original screenshot files are not present locally; JSON is KM formal POC ACL result."},"expiry":{"value":"2026-08-14T13:24:47.7922157Z","timezone_aware":True,"within_four_hours_at_capture":True,"all_equal":["gate-a-disabled.env","gate-a-disabled.json","this evidence"]},"serve":{"stage":"passed","validate":"passed","apply":"passed","tcp_8790":"127.0.0.1:8791","tcp_8792":"127.0.0.1:8793","rollback":"not performed"},"runtime":{"real_enabled":False,"adapter":"disabled","instrument_access":False,"ingest_enabled":False,"sidecar":"running on 127.0.0.1:8792","proxy":"running in existing anritsu-a2a-tailscale-poc namespace","health":"passed","agent_card":"passed; exact x-anritsu-transport expiry matched","port_8790":"preserved","port_8792":"reachable through proxy namespace"},"gate_a_local":{"missing_bearer":401,"wrong_bearer":403,"correct_bearer_503_status_cancel":"awaiting KM cross-machine; Bearer plaintext unavailable and not generated"},"side_effects":{"journal_rows":0,"lease_rows":0,"approval_rows":0,"instrument":False,"iperf":False,"excel":False,"km_ingest":False},"blockers":["Correct Bearer 503/status/cancel require KM cross-machine verification.","No formal real-run GO is implied by this disabled transport preflight."]}

def write(path: Path, value, *, bom=False):
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(value, separators=(",", ":")).encode()); return path

@pytest.fixture
def files(tmp_path):
    acl = acl_fixture(); return tmp_path, write(tmp_path/"execution.json", execution_fixture(acl), bom=True), write(tmp_path/"acl.json", acl)

def test_valid_bom_and_secret_free_summary(files):
    tmp, execution, acl = files
    result = verify_files(execution, acl, now="2026-08-14T10:00:00Z")
    assert result["valid"] and result["acl_hash_match"] and result["side_effects_zero"]

def test_duplicate_keys_symlink_and_oversized_rejected(files):
    tmp, execution, acl = files
    duplicate = tmp/"duplicate.json"; duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(EvidenceError): verify_files(duplicate, acl)
    link = tmp/"link.json"; link.symlink_to(execution)
    with pytest.raises(EvidenceError): verify_files(link, acl)
    large = tmp/"large.json"; large.write_bytes(b"{" + b"a"*(1<<20) + b"}")
    with pytest.raises(EvidenceError): verify_files(large, acl)

@pytest.mark.parametrize("path,change", [("decision",lambda x:x.update(decision="GO")),("runtime",lambda x:x["runtime"].update(real_enabled=True)),("serve",lambda x:x["serve"].update(apply="failed")),("local",lambda x:x["gate_a_local"].update(missing_bearer=200)),("effects",lambda x:x["side_effects"].update(journal_rows=1)),("allow",lambda x:x["acl"].update(allow_any=True)),("grant",lambda x:x["acl"].update(tcp_8792_grant=False))])
def test_mutations_fail(files, path, change):
    tmp, _, acl = files; value = execution_fixture(acl); change(value)
    with pytest.raises(EvidenceError): verify_files(write(tmp/(path+".json"), value), acl)

def test_hash_expiry_acl_test_and_secret_redaction_fail(files):
    tmp, _, acl = files
    value = execution_fixture(acl); value["acl"]["sha256"] = "0"*64
    with pytest.raises(EvidenceError): verify_files(write(tmp/"hash.json", value), acl)
    value = execution_fixture(acl); value["expiry"]["value"] = "2026-08-14T17:32:00+08:00"
    with pytest.raises(EvidenceError): verify_files(write(tmp/"expiry.json", value), acl)
    bad_acl = json.loads(acl.read_text()); bad_acl["saved_test"]["proto"] = "udp"
    with pytest.raises(EvidenceError): verify_files(write(tmp/"acl-test.json", execution_fixture(bad_acl)), write(tmp/"bad-acl.json", bad_acl))
    value = execution_fixture(acl); value["blockers"].append("Bearer very-secret-value-123456789012345678901234")
    with pytest.raises(EvidenceError) as exc: verify_files(write(tmp/"secret.json", value), acl)
    assert "very-secret" not in str(exc.value)

def test_cli_summary_and_required_acl_argument(files):
    _, execution, acl = files
    proc = subprocess.run([sys.executable,str(ROOT/"scripts/verify_anritsu_gate_a_execution_evidence.py"),"--execution-evidence",str(execution),"--acl-evidence",str(acl),"--now","2026-08-14T10:00:00Z"],capture_output=True,text=True)
    assert proc.returncode == 0 and json.loads(proc.stdout)["decision"] == "PARTIAL-PASS-NO-GO"
    missing = subprocess.run([sys.executable,str(ROOT/"scripts/verify_anritsu_gate_a_execution_evidence.py"),"--execution-evidence",str(execution)],capture_output=True,text=True)
    assert missing.returncode != 0

def test_root_handoff_files_are_optional():
    execution = ROOT / "gate-a-disabled-execution-20260814.json"
    acl = ROOT / "tailscale-acl-gate-result-20260814.json"
    if not execution.exists() or not acl.exists():
        pytest.skip("optional handoff files are absent")
    assert verify_files(execution, acl)["decision"] == "PARTIAL-PASS-NO-GO"
