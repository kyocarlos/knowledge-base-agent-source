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

Install the GitHub Actions runner under the dedicated account in a separate
workspace. Use the runner version and SHA-256 published by GitHub for the
selected release; never paste the registration token into this repository:

```bash
sudo install -d -o km-status-runner -g km-status-runner -m 750 \
  /var/lib/km-status-runner/actions-runner
sudo -u km-status-runner -H bash
cd /var/lib/km-status-runner/actions-runner
curl --fail --location --output actions-runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
echo "${RUNNER_SHA256}  actions-runner.tar.gz" | sha256sum --check
tar -xzf actions-runner.tar.gz
./config.sh --url https://github.com/kyocarlos/knowledge-base-agent-source \
  --token "$RUNNER_REGISTRATION_TOKEN" \
  --name "km-status-$(hostname -s)" \
  --labels km-production-readonly \
  --work _work \
  --unattended
exit
sudo ./svc.sh install km-status-runner
```

The registration token is short-lived and must be supplied interactively or
through a protected host mechanism. Do not store it in GitHub repository files
or evidence. Configure the runner service to run as `km-status-runner` and
verify it is not in the `docker` group before starting it.

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
