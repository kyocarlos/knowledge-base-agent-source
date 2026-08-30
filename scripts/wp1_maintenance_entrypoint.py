#!/usr/bin/env python3
"""Persistent maintenance entrypoint for the versioned WP1 dispatcher."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from wp1_transaction_dispatcher import dispatch
from wp1_transaction_wrapper import _safe_command


def _event(log_file: Path, event: str, **fields: object) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event": event,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "secrets_included": False,
        **fields,
    }
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def run_entrypoint(command: list[str], evidence_file: Path, event_log: Path, heartbeat_interval: float) -> int:
    """Run the versioned dispatcher while recording caller supervision events."""
    stop_heartbeat = threading.Event()
    received_signal: int | None = None

    def on_signal(signum: int, _frame: object) -> None:
        nonlocal received_signal
        received_signal = signum
        _event(event_log, "entrypoint_signal", signal_number=signum)
        raise KeyboardInterrupt

    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    for sig in previous_handlers:
        signal.signal(sig, on_signal)

    def heartbeat() -> None:
        while not stop_heartbeat.wait(heartbeat_interval):
            _event(event_log, "entrypoint_heartbeat")

    _event(event_log, "entrypoint_start", command=_safe_command(command))
    os.environ["WP1_FORMAL_ENTRYPOINT"] = "1"
    worker = threading.Thread(target=heartbeat, name="wp1-entrypoint-heartbeat", daemon=True)
    worker.start()
    exit_code = 1
    try:
        _event(event_log, "entrypoint_dispatch_pre")
        exit_code = dispatch(command=command, wrapper=Path(__file__).with_name("wp1_transaction_wrapper.py"), evidence_file=evidence_file, event_log=event_log)
        return exit_code
    except BaseException as exc:  # noqa: BLE001
        _event(event_log, "entrypoint_exception", exception_type=type(exc).__name__, signal_number=received_signal)
        return 1
    finally:
        stop_heartbeat.set()
        worker.join(timeout=max(0.1, heartbeat_interval * 2))
        _event(event_log, "entrypoint_complete", entrypoint_exit=exit_code, signal_number=received_signal)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--orchestration-log", type=Path, required=True)
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a transaction command is required")
    if args.heartbeat_interval <= 0:
        parser.error("--heartbeat-interval must be positive")
    return run_entrypoint(args.command, args.evidence_file, args.orchestration_log, args.heartbeat_interval)


if __name__ == "__main__":
    raise SystemExit(main())
