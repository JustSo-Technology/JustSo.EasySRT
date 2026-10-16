# Install EasySRT on Ubuntu

[Documentation home](../README.md) · [Configure your first stream](configuration.md) · [Platform support](platform-support.md)

## Before you start

Use a fresh Ubuntu Server 24.04 LTS VM, a sudo-capable login, and outbound access to Ubuntu packages, NodeSource, npm, PyPI and GitHub. The installer accepts newer Ubuntu releases, but that is not evidence that every release/architecture has been tested. Python 3.12+ is required. Choose VM CPU, RAM and network capacity for your stream; no minimum sizing benchmark is established.

Run commands in an interactive SSH terminal on the VM. If `curl` is missing, run `sudo apt-get update && sudo apt-get install -y curl ca-certificates` first. This installer installs packages, creates services and starts the management UI. It does not start the sender or configure a public HTTPS proxy/firewall for you.

## One-command install

```bash
bash -c 'set -euo pipefail; installer=$(mktemp); trap "rm -f \"$installer\"" EXIT; curl --fail --silent --show-error --location https://raw.githubusercontent.com/JustSo-Technology/JustSo.EasySRT/main/ops/install-ubuntu.sh -o "$installer"; bash "$installer"'
```

This command downloads with curl and then executes a file, preserving stdin for installer prompts. Do not substitute `curl ... | bash`: the current installer checks whether stdin is a terminal and otherwise uses defaults. “One command” is interactive, not an unattended/cloud-init interface.

Follow the prompts for frontend port, localhost-only binding, station name and support contact. Default frontend is TCP 5173 when available; the backend uses loopback TCP 8000 and the updater normally TCP 5174. Open the URL printed at completion. Keep UI/updater access restricted to the management network. If you choose localhost-only, use an SSH tunnel or reverse proxy; the VM's frontend port is not directly reachable remotely.

Then [create your owner account and configure a stream](configuration.md). For HTTPS, set the public origin with `EASYSRT_PUBLIC_ORIGIN` when invoking the installer and configure the reverse proxy, updater origin and firewall as described in [deployment security](deployment-security.md). Choosing an HTTPS origin does not provision TLS.

## Inspect or select the source before installation

```bash
git clone https://github.com/JustSo-Technology/JustSo.EasySRT.git
cd JustSo.EasySRT
# Inspect ops/install-ubuntu.sh before running it.
bash ops/install-ubuntu.sh
```

The installer builds the application from the selected remote ref and independently fetches privileged code into a root-owned checkout. It does not deploy uncommitted changes from the directory where you run it. A local `git checkout` alone does not change the installer's target: it defaults to `main`.

To pin a published tag, check out that tag and set `EASYSRT_REPO_REF` to the same tag when running the installer. Example shape (replace `YOUR_PUBLISHED_TAG` with an existing tag):

```bash
git checkout YOUR_PUBLISHED_TAG
EASYSRT_REPO_REF=refs/tags/YOUR_PUBLISHED_TAG bash ops/install-ubuntu.sh
```

For curl installation, change the download ref and `EASYSRT_REPO_REF` together. A tag stays pinned; `main` tracks development commits. No automatic latest-release channel is implied. To deploy your own committed fork, set `EASYSRT_REPO_URL` and `EASYSRT_REPO_REF` consistently for both application and privileged code. See [update policy](deployment-security.md#privileged-code-and-updates).

For local development or inspecting a build without installing services, use [build from source](development.md).

## Manual production build from source (advanced)

Use this when you want full control over the install process instead of the guided installer.

This path is more manual and assumes you are comfortable with:

- Ubuntu package management
- `systemd`
- Python virtual environments
- Node.js / `pnpm`

#### 3.1 Install base packages

```bash
sudo apt-get update
sudo apt-get install -y \
  git curl ca-certificates ffmpeg python3 python3-venv build-essential acl rsync
```

Install Node.js 22 LTS (22.13 or newer) and `pnpm`. Node 20 and 21 are unsupported:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo corepack enable
sudo corepack prepare pnpm@10.17.1 --activate
```

#### 3.2 Create the service user and group

```bash
sudo groupadd --system easysrt || true
sudo useradd --system --gid easysrt --create-home --home-dir /home/easysrt --shell /usr/sbin/nologin easysrt || true
sudo usermod -aG easysrt "$USER"
```

#### 3.3 Clone the repo into the production path

```bash
sudo git clone https://github.com/JustSo-Technology/JustSo.EasySRT.git /opt/justso-easysrt
```

Then:

```bash
sudo chown -R easysrt:easysrt /opt/justso-easysrt
```

#### 3.4 Create runtime config

Create `/etc/justso-easysrt/easysrt.env`:

```bash
sudo install -d -o root -g easysrt -m 0750 /etc/justso-easysrt
sudo tee /etc/justso-easysrt/easysrt.env >/dev/null <<'EOF'
EASYSRT_ENVIRONMENT=production
EASYSRT_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_HEX_VALUE
EASYSRT_SESSION_COOKIE_SECURE=false
EASYSRT_ALLOW_INSECURE_HTTP=true
EASYSRT_FRONTEND_HOST=0.0.0.0
EASYSRT_FRONTEND_PORT=5173
EASYSRT_BACKEND_HOST=127.0.0.1
EASYSRT_BACKEND_PORT=8000
EASYSRT_UPDATER_HOST=0.0.0.0
EASYSRT_UPDATER_PORT=5174
EASYSRT_FRONTEND_ORIGIN=http://SERVER_IP:5173
EASYSRT_TRUSTED_HOSTS=SERVER_IP,localhost,127.0.0.1
EASYSRT_SENDER_SERVICE_NAME=easysrt-sender
EASYSRT_HELPER_SOCKET_PATH=/run/justso-easysrt/helper.sock
EASYSRT_UPDATE_SCRIPT_PATH=/usr/local/lib/justso-easysrt/update-ubuntu.sh
EASYSRT_UPDATE_STATE_PATH=/var/lib/justso-easysrt-updates/update-job.json
EASYSRT_UPDATE_LOG_PATH=/var/lib/justso-easysrt-updates/update-job.log
EASYSRT_UPDATE_REPO_URL=https://github.com/JustSo-Technology/JustSo.EasySRT.git
EASYSRT_UPDATE_REPO_REF=main
EOF
sudo chown root:easysrt /etc/justso-easysrt/easysrt.env
sudo chmod 0640 /etc/justso-easysrt/easysrt.env
```

Before starting any service, replace `SERVER_IP` with the VM address and replace the secret placeholder with a fresh value from `openssl rand -hex 32`. Never use the example placeholder as a real secret. This example enables private-management-network HTTP; for HTTPS use [deployment security](deployment-security.md).

Create the backend data directory:

```bash
sudo -u easysrt mkdir -p /opt/justso-easysrt/backend/data
```

Optional initial app metadata:

```bash
sudo -u easysrt tee /opt/justso-easysrt/backend/data/app_config.json >/dev/null <<'EOF'
{
  "station_name": "JustSo Demo Station",
  "support_contact": "support@justso.dev"
}
EOF
```

#### 3.5 Build the backend

```bash
sudo python3 -m venv /usr/local/lib/justso-easysrt-tools
sudo /usr/local/lib/justso-easysrt-tools/bin/python -m pip install uv==0.8.22
sudo -u easysrt /usr/local/lib/justso-easysrt-tools/bin/uv sync --project /opt/justso-easysrt/backend --locked --no-dev --no-editable --python /usr/bin/python3
```

#### 3.6 Build the frontend

```bash
sudo -u easysrt bash -lc "cd /opt/justso-easysrt/frontend && pnpm install --frozen-lockfile"
sudo -u easysrt bash -lc "cd /opt/justso-easysrt/frontend && pnpm build"
```

#### 3.7 Install the runtime scripts and services

Privileged scripts and units must come from an independently fetched, root-owned checkout. Never copy them from the service-account-writable application checkout. Use the same administrator-approved URL and ref for the app and the update policy. This example deliberately tracks `main`; select a published tag for a pinned installation.

```bash
sudo -u easysrt chmod +x /opt/justso-easysrt/ops/run-backend.sh /opt/justso-easysrt/ops/run-frontend.sh /opt/justso-easysrt/ops/run-updater.sh /opt/justso-easysrt/ops/serve-frontend.py
sudo bash <<'ROOT'
set -euo pipefail
trusted_dir=$(mktemp -d /var/tmp/easysrt-trusted.XXXXXXXX)
trap 'rm -rf -- "$trusted_dir"' EXIT
export HOME="$trusted_dir" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
git -c core.hooksPath=/dev/null clone --depth 1 --branch main https://github.com/JustSo-Technology/JustSo.EasySRT.git "$trusted_dir/repo"
install -d -o root -g root -m 0755 /usr/local/lib/justso-easysrt
install -o root -g root -m 0755 "$trusted_dir/repo/ops/host-control-helper.py" "$trusted_dir/repo/ops/update-ubuntu.sh" /usr/local/lib/justso-easysrt/
for unit in justso-easysrt-helper justso-easysrt-backend justso-easysrt-frontend justso-easysrt-updater easysrt-sender; do
  install -o root -g root -m 0644 "$trusted_dir/repo/ops/$unit.service" /etc/systemd/system/
done
printf '%s\n' '{"repo_url":"https://github.com/JustSo-Technology/JustSo.EasySRT.git","repo_ref":"main"}' > /etc/justso-easysrt/update-policy.json
chown root:root /etc/justso-easysrt/update-policy.json
chmod 0644 /etc/justso-easysrt/update-policy.json
install -d -o root -g root -m 0755 /var/lib/justso-easysrt-updates
install -o root -g easysrt -m 0660 /dev/null /var/lib/justso-easysrt-updates/update-job.json
install -o root -g easysrt -m 0660 /dev/null /var/lib/justso-easysrt-updates/update-job.log
ROOT
sudo rm -f /etc/sudoers.d/justso-easysrt-update
sudo systemctl daemon-reload
sudo systemctl enable justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service
sudo systemctl restart justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service
sudo systemctl disable easysrt-sender.service >/dev/null 2>&1 || true
```

#### 3.8 Validate the install

```bash
sudo systemctl is-active justso-easysrt-helper.service
sudo systemctl is-active justso-easysrt-backend.service
sudo systemctl is-active justso-easysrt-frontend.service
sudo systemctl is-active justso-easysrt-updater.service
curl http://127.0.0.1:5174/health
sudo stat -c '%F %U:%G %a %n' /run/justso-easysrt/helper.sock
curl http://127.0.0.1:8000/health
curl -I http://127.0.0.1:5173/
```

Expected results:

- helper, backend, frontend and updater return `active`
- helper socket is `root:easysrt`
- backend health returns `{"ok":true}`
- frontend returns `200 OK`

Then open:

```text
http://<server-ip>:5173
```


## Updates and recovery

Use the owner-only updater UI or `sudo /usr/local/lib/justso-easysrt/update-ubuntu.sh`. It backs up environment/data/privileged files, builds the selected ref and checks health; failed application updates attempt rollback. Review the reported result and logs. The control plane restarts; the sender is not deliberately restarted. An older installation with privileged code under `/opt` needs migration using a trusted installer. See [deployment security](deployment-security.md#privileged-code-and-updates). Keep independent backups; preset export is not a full database/account backup.
