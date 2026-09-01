# KM Status Runner Installation

This procedure keeps the existing `da40_ai_gb10` maintenance account and adds
an isolated account for GitHub Actions status collection. It does not reduce
the maintenance account's permissions.

## Host installation

Run these commands in a root maintenance shell. Do not execute them from a
GitHub pull-request job.

```bash
sudo useradd --create-home --home-dir /var/lib/km-status-runner \
  --shell /usr/sbin/nologin km-status-runner
sudo install -d -o km-status-runner -g km-status-runner -m 750 \
  /var/lib/km-status-runner
sudo install -d -o root -g km-status-runner -m 750 /run/km-status-broker
sudo install -d -o root -g root -m 755 /usr/local/libexec
sudo install -o root -g root -m 755 scripts/km_status_broker.py \
  /usr/local/libexec/km-status-broker
sudo install -o root -g root -m 644 deploy/km-status-broker.service \
  /etc/systemd/system/km-status-broker.service
```

The `km-status-runner` account must not be added to `docker`, `sudo`, or any
database group. The broker is the only process that reads Docker status.

## Socket and service checks

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now km-status-broker.service
sudo stat -c 'mode=%a owner=%U:%G path=%n' /run/km-status-broker/status.sock
sudo -u km-status-runner curl --fail --silent \
  --unix-socket /run/km-status-broker/status.sock \
  http://localhost/v1/status
```

The response must contain only status, release identity and image/status data.
It must not contain environment variables, mounts, credentials, database rows,
or private keys.

## Negative verification

Run as `km-status-runner` and preserve only exit codes, never command output:

```bash
sudo -u km-status-runner test ! -w /srv/knowledge-base-production-rebaseline-20260829-v3/.git
sudo -u km-status-runner test ! -w /srv/knowledge-base-production-rebaseline-20260829-v3/config
sudo -u km-status-runner test ! -w /srv/knowledge-base-production-rebaseline-20260829-v3/data
sudo -u km-status-runner test ! -r /home/da40_ai_gb10/.config/knowledge-base/wp01-deployment.env
sudo -u km-status-runner test ! -r /home/da40_ai_gb10/.config/knowledge-base/wp1-production-e2e-20260829/wp1-production-e2e.env
sudo -u km-status-runner test ! -e /var/run/docker.sock
```

All commands must exit `0`. Do not test denied Compose mutation by running it;
absence of Docker access and the account/group audit are sufficient.

## Activation gate

Only after the account, socket ACL, service hardening and all negative checks
pass may the protected GitHub variable `KM_PRODUCTION_STATUS_ENABLED=true` be
considered. Until then it must remain unset or `false`.
