#!/usr/bin/env bash
set -Eeuo pipefail

# Install the account and broker only. Starting the service is an explicit action.
if [ "$(id -u)" -ne 0 ]; then
  printf 'FAIL_CLOSED: run this installer as root\n' >&2
  exit 1
fi

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUNNER_USER=km-status-runner
RUNNER_HOME=/var/lib/km-status-runner

if id "$RUNNER_USER" >/dev/null 2>&1; then
  test "$(getent passwd "$RUNNER_USER" | cut -d: -f6)" = "$RUNNER_HOME"
  test "$(getent passwd "$RUNNER_USER" | cut -d: -f7)" = /usr/sbin/nologin
else
  useradd --system --create-home --home-dir "$RUNNER_HOME" \
    --shell /usr/sbin/nologin "$RUNNER_USER"
fi

if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -Fxq docker; then
  printf 'FAIL_CLOSED: %s is a member of docker\n' "$RUNNER_USER" >&2
  exit 1
fi

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 750 "$RUNNER_HOME"
install -d -o root -g "$RUNNER_USER" -m 750 /run/km-status-broker
install -d -o root -g root -m 755 /usr/local/libexec
install -o root -g root -m 755 "$ROOT/scripts/km_status_broker.py" \
  /usr/local/libexec/km-status-broker
install -o root -g root -m 644 "$ROOT/deploy/km-status-broker.service" \
  /etc/systemd/system/km-status-broker.service

systemctl daemon-reload
printf 'km_status_runner_install=PASS\n'
printf 'service_start=NOT_REQUESTED\n'

if [ "${1:-}" = --start ]; then
  systemctl enable --now km-status-broker.service
  printf 'service_start=PASS\n'
else
  printf 'next_action=systemctl enable --now km-status-broker.service\n'
fi
