#!/usr/bin/env python3
"""Run the WP0/WP1 candidate against isolated shadow dependencies."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import textwrap
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_run_id_gate import check_unique_production_run_id


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, text=True, **kwargs)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> tuple[int, str]:
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})} if body else (headers or {})
        req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def post_json(url: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> tuple[int, str]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def post_multipart(
    url: str,
    field_name: str,
    file_path: Path,
    headers: dict[str, str],
    attachments: list[Path] | None = None,
) -> tuple[int, str]:
    boundary = f"----kb-e2e-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    files = [(field_name, file_path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]
    files.extend(("attachments", item, "application/octet-stream") for item in (attachments or []))
    for name, path, content_type in files:
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        parts.append(path.read_bytes())
        parts.append(b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    request_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        **headers,
    }
    req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def e2e_environment(hash_file: Path | None, prefix: str) -> str:
    if not hash_file:
        return ""
    values = json.loads(hash_file.read_text(encoding="utf-8"))
    required = {"e2e-agent-01", "e2e-reviewer-01", "e2e-cleanup-01"}
    if set(values) != required:
        raise ValueError("E2E hash file must contain exactly the three isolated roles")
    environment = {
        "KB_E2E_WRITE_MODE_ENABLED": "true",
        "KB_E2E_CLEANUP_ENABLED": "true",
        "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": prefix,
        "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({"e2e-agent-01": values["e2e-agent-01"]}),
        "KB_E2E_REVIEWER_TOKEN_HASHES_JSON": json.dumps({"e2e-reviewer-01": values["e2e-reviewer-01"]}),
        "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({"e2e-cleanup-01": values["e2e-cleanup-01"]}),
        "KB_AGENT_TOKEN_HASHES_JSON": json.dumps({"e2e-agent-01": values["e2e-agent-01"]}),
    }
    return yaml.safe_dump(environment, default_flow_style=False, sort_keys=False).rstrip()


def websocket_chat_exchange(url: str, source_root: Path, auth_token: str = "") -> dict[str, object]:
    """Exercise the authenticated OpenClaw challenge/connect/chat sequence."""
    probe = (
        "import asyncio,json,sys\nimport websockets\n"
        "async def main():\n"
        " r={'handshake':False,'auth_sent':False,'ready':False,'chat_sent':False,'response':False,'closed':False,'close_code':None,'frames':[]}\n"
        " try:\n"
        "  async with websockets.connect(sys.argv[1],open_timeout=10,close_timeout=5) as ws:\n"
        "   r['handshake']=True\n"
        "   await ws.send(json.dumps({'type':'auth','token':sys.argv[2]})); r['auth_sent']=True; r['frames'].append({'direction':'client_to_candidate','type':'auth','token_present':bool(sys.argv[2])})\n"
        "   for _ in range(20):\n"
        "    try: msg=json.loads(await asyncio.wait_for(ws.recv(),timeout=10))\n"
        "    except Exception as exc: r['frames'].append({'direction':'candidate_to_client','exception':type(exc).__name__,'close_code':getattr(ws,'close_code',None)}); break\n"
        "    frame={'direction':'candidate_to_client','type':msg.get('type'),'event':msg.get('event'),'method':msg.get('method'),'id':msg.get('id'),'state':(msg.get('payload') or {}).get('state')}\n"
        "    r['frames'].append(frame)\n"
        "    if msg.get('event')=='connect.challenge':\n"
        "     p=msg.get('payload') or {}; connect={'type':'req','id':'c1','method':'connect','params':{'minProtocol':3,'maxProtocol':3,'client':{'id':'cli','version':'1.0.0','platform':'linux','mode':'cli'},'role':'operator','scopes':['operator.read','operator.write'],'auth':{'token':sys.argv[2],'deviceToken':'isolated-device-token'},'device':{'id':'isolated-device','publicKey':'redacted','signature':'redacted','signedAt':p.get('ts'),'nonce':p.get('nonce')},'locale':'zh-TW','userAgent':'openclaw-e2e/1.0.0'}}\n"
        "     await ws.send(json.dumps(connect)); r['frames'].append({'direction':'client_to_candidate','type':'req','method':'connect','id':'c1','auth_token_present':bool(sys.argv[2]),'device_signature':'redacted'})\n"
        "    elif msg.get('type')=='res' and msg.get('id')=='c1' and msg.get('ok'):\n"
        "     r['ready']=True\n"
        "     chat={'type':'req','id':'ws-e2e-1','method':'chat.send','params':{'message':'synthetic gateway probe','sessionKey':'agent:isolated:e2e','idempotencyKey':'ws-e2e-1'}}\n"
        "     await ws.send(json.dumps(chat)); r['chat_sent']=True; r['frames'].append({'direction':'client_to_candidate','type':'req','method':'chat.send','id':'ws-e2e-1','session_key':'agent:isolated:e2e'})\n"
        "    elif msg.get('event')=='chat' and (msg.get('payload') or {}).get('state') in ('final','end'):\n"
        "     r['response']=True; break\n"
        "   await ws.close()\n"
        "   r['closed']=True; r['close_code']=getattr(ws,'close_code',None)\n"
        " except Exception as exc: r['error']=type(exc).__name__\n"
        " print(json.dumps(r))\nasyncio.run(main())\n"
    )
    python = source_root / ".venv/bin/python"
    if not python.is_file():
        return {"handshake": False, "error": "websocket runtime unavailable"}
    result = subprocess.run([str(python), "-c", probe, url, auth_token], capture_output=True, text=True, check=False)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"handshake": False, "error": "websocket probe produced no JSON"}


def read_secret_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def wait_http(url: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if request(url)[0] == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"candidate did not become healthy: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-root", type=Path, default=Path.home() / "kb-pre-wp01-drills")
    parser.add_argument("--e2e-hash-file", type=Path)
    parser.add_argument("--e2e-secret-file", type=Path)
    parser.add_argument("--test-run-id-prefix", default="")
    parser.add_argument("--write-fixture", type=Path)
    parser.add_argument("--write-test-run-id")
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-image-digest")
    parser.add_argument("--expected-build-timestamp")
    parser.add_argument("--prior-production-evidence-root", type=Path)
    parser.add_argument("--versioned-runner-fixture", type=Path)
    parser.add_argument("--versioned-runner-run-id")
    parser.add_argument("--runner-python", type=Path)
    args = parser.parse_args()

    if args.prior_production_evidence_root and args.write_test_run_id:
        check_unique_production_run_id(args.write_test_run_id, args.prior_production_evidence_root.resolve())
    if bool(args.versioned_runner_fixture) != bool(args.versioned_runner_run_id):
        raise ValueError("--versioned-runner-fixture and --versioned-runner-run-id must be provided together")
    if args.versioned_runner_fixture and not args.prior_production_evidence_root:
        raise ValueError("versioned runner validation requires --prior-production-evidence-root")

    source = args.source_root.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project = f"kb-wp01-candidate-{stamp.lower().replace('_', '-')}"
    prefix = project
    port = free_port()
    neo_password = secrets.token_urlsafe(24)
    report_password = secrets.token_urlsafe(24)
    app_uid = os.getuid()
    app_gid = os.getgid()
    report_dir = args.report_root.expanduser().resolve() / f"candidate-{stamp}"
    report_dir.mkdir(parents=True, mode=0o700)
    evidence: dict[str, object] = {"project": project, "image": args.image, "port": port}
    e2e_env = e2e_environment(args.e2e_hash_file.resolve() if args.e2e_hash_file else None, args.test_run_id_prefix)
    e2e_env_block = textwrap.indent(e2e_env, "      ") if e2e_env else ""
    e2e_secrets = read_secret_env(args.e2e_secret_file.resolve()) if args.e2e_secret_file else {}

    with tempfile.TemporaryDirectory(prefix="kb-wp01-candidate-") as temp:
        work = Path(temp)
        data_dir = work / "data"
        config_dir = work / "config"
        data_dir.mkdir()
        (data_dir / "uploads").mkdir()
        config_dir.mkdir()
        openclaw_dir = work / "openclaw"
        (openclaw_dir / "identity").mkdir(parents=True)
        (openclaw_dir / "workspace" / "memory").mkdir(parents=True)
        isolated_gateway_token = "isolated-gateway-token"
        device_key = Ed25519PrivateKey.generate()
        private_pem = device_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        public_pem = device_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        public_raw = base64.urlsafe_b64encode(device_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )).decode("ascii").rstrip("=")
        (openclaw_dir / "openclaw.json").write_text(json.dumps({"gateway": {"auth": {"token": isolated_gateway_token}, "port": 8765}}) + "\n", encoding="utf-8")
        (openclaw_dir / "identity" / "device.json").write_text(json.dumps({
            "deviceId": "isolated-device", "privateKeyPem": private_pem, "publicKeyPem": public_pem,
        }) + "\n", encoding="utf-8")
        (openclaw_dir / "identity" / "device-auth.json").write_text(json.dumps({
            "tokens": {"operator": {"token": "isolated-device-token", "scopes": ["operator.read", "operator.write"]}},
        }) + "\n", encoding="utf-8")
        gateway_script = work / "gateway.py"
        gateway_script.write_text(
            "import asyncio,json,time\nimport websockets\n"
            "TOKEN='isolated-gateway-token'\n"
            "async def record(frame):\n"
            " with open('/app/data/gateway-frames.jsonl','a',encoding='utf-8') as f: f.write(json.dumps(frame,sort_keys=True)+'\\n')\n"
            "async def handler(ws):\n"
            " await ws.send(json.dumps({'type':'event','event':'connect.challenge','payload':{'nonce':'isolated-nonce','ts':int(time.time()*1000)}}))\n"
            " ready=False\n"
            " async for raw in ws:\n"
            "  m=json.loads(raw); await record({'direction':'gateway_received','type':m.get('type'),'method':m.get('method'),'id':m.get('id'),'session_key':(m.get('params') or {}).get('sessionKey'),'auth_token_present':bool(((m.get('params') or {}).get('auth') or {}).get('token'))})\n"
            "  if m.get('type')=='req' and m.get('method')=='connect':\n"
            "   auth=(m.get('params') or {}).get('auth') or {}\n"
            "   if auth.get('token') != TOKEN:\n"
            "    await ws.close(code=4401,reason='invalid gateway token'); return\n"
            "   ready=True; await ws.send(json.dumps({'type':'res','id':m.get('id'),'ok':True,'payload':{'protocol':3}})); continue\n"
            "  if m.get('type')=='req' and m.get('method')=='chat.send':\n"
            "   if not ready: await ws.close(code=4401,reason='connect required'); return\n"
            "   await ws.send(json.dumps({'type':'res','id':m.get('id'),'ok':True,'payload':{'status':'queued'}}))\n"
            "   await ws.send(json.dumps({'type':'event','event':'chat','payload':{'state':'final','sessionKey':(m.get('params') or {}).get('sessionKey'),'message':{'content':[{'type':'text','text':'synthetic gateway response'}]}}}))\n"
            "async def main():\n"
            " async with websockets.serve(handler,'0.0.0.0',8765): await asyncio.Future()\n"
            "asyncio.run(main())\n",
            encoding='utf-8'
        )
        config_path = source / "config/config.yaml"
        if not config_path.is_file():
            config_path = source / "config/config.yaml.example"
        config = yaml.safe_load(config_path.read_text())
        config.setdefault("neo4j", {})["uri"] = "bolt://neo4j:7687"
        config["neo4j"]["user"] = "neo4j"
        config["neo4j"]["password"] = neo_password
        config.setdefault("qdrant", {})["url"] = "http://qdrant:6333"
        (config_dir / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))

        compose = work / "compose.yml"
        compose.write_text(f"""services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: [\"CMD\", \"redis-cli\", \"ping\"]
      interval: 2s
      timeout: 2s
      retries: 30
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: kb_reports
      POSTGRES_USER: kb_report
      POSTGRES_PASSWORD: {report_password}
    healthcheck:
      test: [\"CMD-SHELL\", \"pg_isready -U kb_report -d kb_reports\"]
      interval: 2s
      timeout: 2s
      retries: 30
  neo4j:
    image: neo4j:latest
    pull_policy: never
    environment:
      NEO4J_AUTH: neo4j/{neo_password}
    healthcheck:
      test: [\"CMD-SHELL\", \"/var/lib/neo4j/bin/cypher-shell -u neo4j -p \\\"$${{NEO4J_AUTH#neo4j/}}\\\" 'RETURN 1'\"]
      interval: 3s
      timeout: 3s
      retries: 60
  qdrant:
    image: qdrant/qdrant:latest
    pull_policy: never
  web:
    image: {args.image}
    user: "{app_uid}:{app_gid}"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
    ports: [\"127.0.0.1:{port}:8000\"]
    environment: &app_env
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      REDIS_HOST: redis
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: {neo_password}
      QDRANT_URL: http://qdrant:6333
      KB_REPORT_REGISTRY_URL: postgresql://kb_report:{report_password}@postgres:5432/kb_reports
      KB_INGEST_UPLOAD_ROOT: /app/data/uploads
      KB_INGEST_REGISTRY_URL: sqlite:////app/data/ingestion-registry.sqlite3
      HOME: /app/data/home
      HF_HOME: /app/data/home/.cache/huggingface
      HUGGINGFACE_HUB_CACHE: /app/data/home/.cache/huggingface/hub
      TRANSFORMERS_CACHE: /app/data/home/.cache/huggingface/transformers
      SENTENCE_TRANSFORMERS_HOME: /app/data/home/.cache/sentence-transformers
      KM_GIT_COMMIT: {json.dumps(args.expected_commit or '')}
      KM_RELEASE_ID: {json.dumps(args.expected_release_id or '')}
      KM_IMAGE_DIGEST: {json.dumps(args.expected_image_digest or '')}
      KM_BUILD_TIMESTAMP: {json.dumps(args.expected_build_timestamp or '')}
      OPENCLAW_GATEWAY_WS_URL: ws://gateway:8765/ws
      OPENCLAW_HOME: /app/openclaw
      OPENCLAW_CHAT_SESSION_KEY: agent:isolated:e2e
{e2e_env_block}
    volumes: &app_volumes
      - {config_dir}:/app/config:ro
      - {openclaw_dir}:/app/openclaw:ro
      - {data_dir}:/app/data
      - {data_dir}:/home/da40_ai_gb10/knowledge-base/data
    depends_on:
      redis: {{condition: service_healthy}}
      postgres: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
      gateway: {{condition: service_healthy}}
  gateway:
    image: {args.image}
    command: python /app/gateway.py
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; s=socket.create_connection(('127.0.0.1',8765),1); s.close()"]
      interval: 1s
      timeout: 2s
      retries: 30
    volumes:
      - {gateway_script}:/app/gateway.py:ro
      - {data_dir}:/app/data
  search_worker:
    image: {args.image}
    user: "{app_uid}:{app_gid}"
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q search
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  ingest_worker:
    image: {args.image}
    user: "{app_uid}:{app_gid}"
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q ingest
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      postgres: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  beat:
    image: {args.image}
    command: celery -A src.web_api.tasks:celery_app beat --loglevel=info
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
""")
        command = ["docker", "compose", "--project-name", project, "-f", str(compose)]
        try:
            run([*command, "up", "-d", "--no-build"])
            wait_http(f"http://127.0.0.1:{port}/health")
            probes = {}
            for path in ("/health", "/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready", "/api/v1/version", "/api/agent/v1/health"):
                probes[path] = dict(zip(("status", "body"), request(f"http://127.0.0.1:{port}{path}")))
            expected = {
                "/health": 200, "/api/v1/health": 200, "/api/v1/health/live": 200,
                "/api/v1/health/ready": 200, "/api/v1/version": 200, "/api/agent/v1/health": 401,
            }
            if any(probes[path]["status"] != status for path, status in expected.items()):
                raise RuntimeError(f"candidate API contract mismatch: {probes}")
            if all((args.expected_commit, args.expected_release_id, args.expected_image_digest, args.expected_build_timestamp)):
                version_data = json.loads(probes["/api/v1/version"]["body"])["data"]
                expected_metadata = {
                    "commit": args.expected_commit,
                    "release_id": args.expected_release_id,
                    "image_digest": args.expected_image_digest,
                    "build_timestamp": args.expected_build_timestamp,
                }
                if {key: version_data.get(key) for key in expected_metadata} != expected_metadata:
                    raise RuntimeError(f"candidate metadata mismatch: {version_data}")
                metadata_env = {}
                for service in ("web", "search_worker", "ingest_worker", "beat"):
                    container_id = subprocess.check_output([*command, "ps", "-q", service], text=True).strip()
                    env_values = json.loads(subprocess.check_output(
                        ["docker", "inspect", container_id, "--format", "{{json .Config.Env}}"], text=True
                    ))
                    env_map = dict(item.split("=", 1) for item in env_values if "=" in item)
                    metadata_env[service] = {key: env_map.get(key) for key in (
                        "KM_GIT_COMMIT", "KM_RELEASE_ID", "KM_IMAGE_DIGEST", "KM_BUILD_TIMESTAMP"
                    )}
                expected_env = {
                    "KM_GIT_COMMIT": args.expected_commit,
                    "KM_RELEASE_ID": args.expected_release_id,
                    "KM_IMAGE_DIGEST": args.expected_image_digest,
                    "KM_BUILD_TIMESTAMP": args.expected_build_timestamp,
                }
                if any(values != expected_env for values in metadata_env.values()):
                    raise RuntimeError(f"service metadata mismatch: {metadata_env}")
                evidence["runtime_metadata"] = {"version": expected_metadata, "services": metadata_env}
            if e2e_secrets:
                e2e_headers = {
                    "Authorization": f"Bearer {e2e_secrets['E2E_AGENT_TOKEN']}",
                    "X-E2E-Agent-ID": e2e_secrets["E2E_AGENT_ID"],
                    "X-E2E-Test-Mode": "true",
                }
                cleanup_headers = {
                    "Authorization": f"Bearer {e2e_secrets['E2E_CLEANUP_TOKEN']}",
                    "X-E2E-Cleanup-ID": e2e_secrets["E2E_CLEANUP_ID"],
                }
                e2e_probes = {
                    "agent_health": dict(zip(("status", "body"), request(f"http://127.0.0.1:{port}/api/agent/v1/health", e2e_headers))),
                    "cleanup_missing_token": dict(zip(("status", "body"), request(
                        f"http://127.0.0.1:{port}/api/internal/e2e/v1/runs/TR-E2E-WP0-probe/cleanup",
                        method="POST",
                        payload={"apply": False},
                    ))),
                    "cleanup_wrong_role_token": dict(zip(("status", "body"), request(
                        f"http://127.0.0.1:{port}/api/internal/e2e/v1/runs/TR-E2E-WP0-probe/cleanup",
                        {"Authorization": "Bearer wrong", "X-E2E-Cleanup-ID": e2e_secrets["E2E_CLEANUP_ID"]},
                        method="POST",
                        payload={"apply": False},
                    ))),
                }
                if e2e_probes["agent_health"]["status"] != 200 or e2e_probes["cleanup_missing_token"]["status"] != 401 or e2e_probes["cleanup_wrong_role_token"]["status"] != 403:
                    raise RuntimeError(f"E2E credential probe mismatch: {e2e_probes}")
                evidence["e2e_auth_probes"] = e2e_probes
            if bool(args.write_fixture) != bool(args.write_test_run_id):
                raise ValueError("--write-fixture 與 --write-test-run-id 必須同時提供")
            if args.write_fixture:
                if not e2e_secrets:
                    raise ValueError("寫入型 E2E 必須提供隔離 E2E credentials")
                fixture = args.write_fixture.resolve()
                if not fixture.is_file() or fixture.suffix.lower() != ".xlsx":
                    raise ValueError("--write-fixture 必須是存在的 .xlsx 檔案")
                write_agent_headers = {
                    "Authorization": f"Bearer {e2e_secrets['E2E_AGENT_TOKEN']}",
                    "X-E2E-Agent-ID": e2e_secrets["E2E_AGENT_ID"],
                    "X-E2E-Test-Mode": "true",
                    "X-E2E-Test-Run-ID": args.write_test_run_id,
                    "Idempotency-Key": args.write_test_run_id,
                }
                upload_status, upload_body = post_multipart(
                    f"http://127.0.0.1:{port}/api/agent/v1/reports",
                    "file",
                    fixture,
                    write_agent_headers,
                    [fixture.parent / "synthetic-e2e-log.txt"],
                )
                if upload_status != 202:
                    raise RuntimeError(f"shadow report upload failed: {upload_status} {upload_body}")
                submission_id = json.loads(upload_body).get("submission_id")
                if not submission_id:
                    raise RuntimeError("shadow upload response missing submission_id")
                reviewer_headers = {
                    "Authorization": f"Bearer {e2e_secrets['E2E_REVIEWER_TOKEN']}",
                    "X-E2E-Reviewer-ID": e2e_secrets["E2E_REVIEWER_ID"],
                    "X-E2E-Test-Mode": "true",
                }
                approve_status, approve_body = post_json(
                    f"http://127.0.0.1:{port}/api/admin/v1/report-submissions/{submission_id}/approve",
                    {"comment": "isolated shadow write E2E"},
                    reviewer_headers,
                )
                if approve_status != 200:
                    raise RuntimeError(f"shadow report approval failed: {approve_status} {approve_body}")
                terminal_status = None
                terminal_error = None
                ingest_task_id = None
                for _ in range(30):
                    item_status, item_body = request(
                        f"http://127.0.0.1:{port}/api/admin/v1/report-submissions/{submission_id}",
                        reviewer_headers,
                    )
                    if item_status != 200:
                        raise RuntimeError(f"shadow report status failed: {item_status} {item_body}")
                    item = json.loads(item_body)
                    terminal_status = item.get("status")
                    terminal_error = item.get("error")
                    ingest_task_id = item.get("ingest_task_id")
                    if terminal_status in {"completed", "ingest_failed", "rejected", "validation_failed"}:
                        break
                    time.sleep(2)
                if terminal_status not in {"completed", "ingest_failed"}:
                    raise RuntimeError(f"shadow ingest did not reach terminal status: {terminal_status}")
                self_read_status, self_read_body = request(
                    f"http://127.0.0.1:{port}/api/agent/v1/reports/{submission_id}", {
                        "Authorization": write_agent_headers["Authorization"],
                        "X-Agent-ID": e2e_secrets["E2E_AGENT_ID"],
                    }
                )
                if self_read_status != 200:
                    raise RuntimeError(f"shadow report self-read failed: {self_read_status} {self_read_body}")
                duplicate_status, duplicate_body = post_multipart(
                    f"http://127.0.0.1:{port}/api/agent/v1/reports", "file", fixture,
                    write_agent_headers, [fixture.parent / "synthetic-e2e-log.txt"]
                )
                duplicate_payload = json.loads(duplicate_body)
                if duplicate_status != 202 or duplicate_payload.get("duplicate") is not True:
                    raise RuntimeError(f"shadow duplicate upload failed: {duplicate_status} {duplicate_body}")
                worker_log_excerpt = ""
                if terminal_status == "ingest_failed":
                    log_result = subprocess.run(
                        [*command, "logs", "--no-color", "--tail", "200", "ingest_worker"],
                        check=False,
                        text=True,
                        capture_output=True,
                    )
                    worker_log_excerpt = (log_result.stdout or log_result.stderr)[-12000:]
                cleanup_status, cleanup_body = post_json(
                    f"http://127.0.0.1:{port}/api/internal/e2e/v1/runs/{args.write_test_run_id}/cleanup",
                    {"environment": "anritsu", "apply": False},
                    cleanup_headers,
                )
                cleanup_plan = json.loads(cleanup_body)
                if cleanup_status != 200 or cleanup_plan.get("mode") != "dry-run":
                    raise RuntimeError(f"shadow cleanup dry-run failed: {cleanup_status} {cleanup_body}")
                apply_status, apply_body = post_json(
                    f"http://127.0.0.1:{port}/api/internal/e2e/v1/runs/{args.write_test_run_id}/cleanup",
                    {"environment": "anritsu", "apply": True},
                    cleanup_headers,
                )
                cleanup_result = json.loads(apply_body)
                if apply_status != 200 or cleanup_result.get("mode") != "apply":
                    raise RuntimeError(f"shadow cleanup apply failed: {apply_status} {apply_body}")
                deleted_status, _ = request(
                    f"http://127.0.0.1:{port}/api/admin/v1/report-submissions/{submission_id}",
                    reviewer_headers,
                )
                if deleted_status != 404:
                    raise RuntimeError(f"shadow cleanup did not remove submission: HTTP {deleted_status}")
                evidence["write_e2e"] = {
                    "test_run_id": args.write_test_run_id,
                    "upload_status": upload_status,
                    "approval_status": approve_status,
                    "self_read_status": self_read_status,
                    "duplicate_upload": {"status": duplicate_status, "duplicate": duplicate_payload.get("duplicate")},
                    "terminal_status": terminal_status,
                    "terminal_error": terminal_error,
                    "worker_log_excerpt": worker_log_excerpt,
                    "ingest_task_id_present": bool(ingest_task_id),
                    "cleanup_dry_run_status": cleanup_status,
                    "cleanup_apply_status": apply_status,
                    "cleanup_plan_counts": {
                        "reports": len(cleanup_plan.get("reports", [])),
                        "ingest_records": len(cleanup_plan.get("ingest_records", [])),
                        "neo4j": cleanup_plan.get("neo4j", {}),
                        "qdrant": cleanup_plan.get("qdrant", {}),
                    },
                    "cleanup_deleted_counts": cleanup_result.get("deleted", {}),
                    "submission_after_cleanup": deleted_status,
                    "result": "passed",
                }
            search_status, search_body = post_json(
                f"http://127.0.0.1:{port}/search",
                {"query": "WP01 shadow search submission", "mode": "basic", "sources_only": True},
                {"X-Trace-ID": "wp01-shadow-trace"},
            )
            if search_status != 200 or not json.loads(search_body).get("task_id"):
                raise RuntimeError(f"candidate search submission failed: {search_status} {search_body}")
            if args.versioned_runner_fixture:
                runner = source / "scripts/run_wp1_production_acceptance.py"
                runner_evidence = report_dir / "versioned-runner-evidence.json"
                runner_python = args.runner_python or source / ".venv/bin/python"
                runner_command = [
                    str(runner_python if runner_python.is_file() else Path(sys.executable)), str(runner),
                    "--base-url", f"http://127.0.0.1:{port}",
                    "--run-id", args.versioned_runner_run_id,
                    "--fixture", str(args.versioned_runner_fixture.resolve()),
                    "--attachment", str((args.versioned_runner_fixture.resolve().parent / "synthetic-e2e-log.txt")),
                    "--credentials-env", str(args.e2e_secret_file.resolve()),
                    "--production-evidence-root", str(args.prior_production_evidence_root.resolve()),
                    "--source-root", str(source),
                    "--expected-git-head", subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
                    "--expected-runner-sha256", hashlib.sha256(runner.read_bytes()).hexdigest(),
                    "--expected-crypto-sha256", hashlib.sha256((source / "scripts/websocket_crypto_preflight.py").read_bytes()).hexdigest(),
                    "--expected-commit", args.expected_commit,
                    "--expected-release-id", args.expected_release_id,
                    "--expected-image-id", args.expected_image_digest,
                    "--expected-build-timestamp", args.expected_build_timestamp,
                    "--evidence-out", str(runner_evidence),
                ]
                result = subprocess.run(runner_command, text=True, capture_output=True, check=False)
                if result.returncode != 0 or not runner_evidence.is_file():
                    raise RuntimeError("versioned production acceptance runner failed in isolated Compose")
                versioned = json.loads(runner_evidence.read_text(encoding="utf-8"))
                if versioned.get("result") != "PASS":
                    raise RuntimeError("versioned production acceptance runner did not pass")
                evidence["versioned_runner"] = versioned
                evidence["websocket"] = versioned["websocket"]
            else:
                evidence["websocket"] = websocket_chat_exchange(f"ws://127.0.0.1:{port}/ws", source, isolated_gateway_token)
                if not evidence["websocket"].get("handshake"):
                    raise RuntimeError(f"candidate WebSocket handshake failed: {evidence['websocket']}")
            evidence["websocket"]["gateway_frames"] = []
            gateway_log = data_dir / "gateway-frames.jsonl"
            if gateway_log.is_file():
                evidence["websocket"]["gateway_frames"] = [json.loads(line) for line in gateway_log.read_text().splitlines()]
            running = {}
            for service in ("web", "search_worker", "ingest_worker", "beat"):
                container_id = subprocess.check_output([*command, "ps", "-q", service], text=True).strip()
                running[service] = bool(container_id) and subprocess.check_output(
                    ["docker", "inspect", container_id, "--format", "{{.State.Running}}"], text=True
                ).strip() == "true"
            if not all(running.values()):
                raise RuntimeError(f"candidate services are not all running: {running}")
            evidence.update({
                "probes": probes,
                "search_submission": {"status": search_status, "task_id_present": True},
                "services_running": running,
                "result": "passed",
            })
        finally:
            subprocess.run([*command, "down", "--volumes", "--remove-orphans"], check=False)
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        report = report_dir / "candidate-drill.json"
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        report.chmod(0o600)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
