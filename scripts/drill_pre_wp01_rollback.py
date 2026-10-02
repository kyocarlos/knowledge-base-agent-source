#!/usr/bin/env python3
"""Exercise the application rollback path in an isolated Docker shadow stack."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SERVER = """import os
from http.server import BaseHTTPRequestHandler,HTTPServer
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  code=int(os.environ.get('STATUS_CODE','200')); body=os.environ.get('MARKER','unknown').encode()
  self.send_response(code); self.end_headers(); self.wfile.write(body)
 def log_message(self,*args): pass
HTTPServer(('0.0.0.0',18000),H).serve_forever()
"""


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, text=True, **kwargs)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def probe(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def wait_for(url: str, code: int, marker: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            if probe(url) == (code, marker):
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"shadow endpoint did not reach {code}/{marker}")


def compose_text(image: str, container: str, port: int, marker: str, status: int) -> str:
    command = json.dumps(["python3", "-c", SERVER])
    return f"""services:
  web:
    image: {image}
    container_name: {container}
    command: {command}
    environment:
      MARKER: {marker}
      STATUS_CODE: \"{status}\"
    ports:
      - \"127.0.0.1:{port}:18000\"
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, default=Path.home() / "kb-pre-wp01-drills")
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    tags = json.loads((checkpoint / "images/image-tags.json").read_text())
    image = tags["web"]
    expected_image_id = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
    port = free_port()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project = f"kb-wp01-shadow-{stamp.lower().replace('_', '-')}"
    container = f"{project}-web"
    report_dir = args.report_root.expanduser().resolve() / stamp
    report_dir.mkdir(parents=True, mode=0o700)

    with tempfile.TemporaryDirectory(prefix="kb-wp01-shadow-") as temp:
        work = Path(temp)
        baseline = work / "baseline.yml"
        candidate = work / "candidate.yml"
        override = work / "rollback-images.yml"
        env_file = work / "empty.env"
        baseline.write_text(compose_text(image, container, port, "pre-wp01-baseline", 200))
        candidate.write_text(compose_text(image, container, port, "wp01-candidate-failed", 503))
        override.write_text(f"services:\n  web:\n    image: {image}\n    pull_policy: never\n")
        env_file.write_text("")
        base_cmd = ["docker", "compose", "--project-name", project, "--project-directory", str(work)]
        evidence: dict[str, object] = {"project": project, "port": port, "checkpoint": str(checkpoint)}
        try:
            run([*base_cmd, "-f", str(baseline), "up", "-d", "--no-build"])
            wait_for(f"http://127.0.0.1:{port}/", 200, "pre-wp01-baseline")
            evidence["baseline_before"] = {"status": 200, "marker": "pre-wp01-baseline"}

            run([*base_cmd, "-f", str(candidate), "up", "-d", "--no-build", "--force-recreate"])
            wait_for(f"http://127.0.0.1:{port}/", 503, "wp01-candidate-failed")
            evidence["candidate_failure"] = {"status": 503, "marker": "wp01-candidate-failed"}

            rollback = Path(__file__).with_name("rollback_pre_wp01.py")
            run([
                str(rollback), "--checkpoint", str(checkpoint), "--project-name", project,
                "--project-directory", str(work), "--compose-file", str(baseline),
                "--override-file", str(override), "--env-file", str(env_file),
                "--services", "web", "--health-url", f"http://127.0.0.1:{port}/",
                "--health-contains", "pre-wp01-baseline", "--execute",
            ])
            status, marker = probe(f"http://127.0.0.1:{port}/")
            actual_image_id = subprocess.check_output(["docker", "inspect", container, "--format", "{{.Image}}"], text=True).strip()
            if (status, marker) != (200, "pre-wp01-baseline") or actual_image_id != expected_image_id:
                raise RuntimeError("shadow rollback verification failed")
            evidence["rollback"] = {"status": status, "marker": marker, "image_id_matches": True}
            evidence["result"] = "passed"
        finally:
            subprocess.run([*base_cmd, "-f", str(baseline), "down", "--volumes", "--remove-orphans"], check=False)
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        report = report_dir / "rollback-drill.json"
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        report.chmod(0o600)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
