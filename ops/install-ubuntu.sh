#!/usr/bin/env bash
set -Eeuo pipefail

# EXIT may run inside a redirected function; always report to the terminal.
exec 3>&1 4>&2

REPO_URL="${EASYSRT_REPO_URL:-https://github.com/JustSo-Technology/JustSo.EasySRT.git}"
REPO_REF="${EASYSRT_REPO_REF:-main}"
APP_USER="easysrt"
APP_GROUP="easysrt"
TOOLS_DIR="/usr/local/lib/justso-easysrt-tools"
UV_VERSION="0.8.22"
PRIVILEGED_DIR="/usr/local/lib/justso-easysrt"
TRUSTED_COMMIT=""
TRUSTED_TMP=""
PRIVILEGED_SOURCE=""
APP_DIR="/opt/justso-easysrt"
CONFIG_DIR="/etc/justso-easysrt"
ENV_FILE="${CONFIG_DIR}/easysrt.env"
BACKEND_DIR="${APP_DIR}/backend"
FRONTEND_DIR="${APP_DIR}/frontend"
HELPER_SOCKET_PATH="/run/justso-easysrt/helper.sock"
INSTALLING_USER="${SUDO_USER:-$USER}"
TOTAL_STEPS=11
CURRENT_STEP=0
STEP_TITLE="Starting installer"
INSTALL_LOG=""
INSTALL_SUCCEEDED=false
FAILURE_MESSAGE=""
VERBOSE="${EASYSRT_VERBOSE:-0}"

OS_NAME=""
OS_VERSION=""
PRIMARY_IP="127.0.0.1"
RECOMMENDED_FRONTEND_PORT="5173"
FRONTEND_PORT="5173"
FRONTEND_HOST="0.0.0.0"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
UPDATER_PORT="5174"
STATION_NAME="JustSo Demo Station"
SUPPORT_CONTACT="support@justso.dev"
PUBLIC_ORIGIN="${EASYSRT_PUBLIC_ORIGIN:-}"
EXISTING_RUNTIME_CONFIG="false"

print_banner() {
  cat <<'EOF'

  EasySRT
  by JustSo. | Ubuntu installer

EOF
}

init_logging() {
  INSTALL_LOG="$(mktemp "${TMPDIR:-/tmp}/easysrt-install.XXXXXXXX.log")"
  chmod 0600 "${INSTALL_LOG}"
  printf 'Installation log: %s\n' "${INSTALL_LOG}"
  printf 'Package and build steps may take a few minutes.\n'
}

# Keep functions in this shell: source resolution and apt setup update state.
# Call directly so errexit still stops failures inside nested functions.
run_logged() {
  if [[ "${VERBOSE}" == "1" ]]; then
    run_interactive "$@"
  else
    "$@" >>"${INSTALL_LOG}" 2>&1
  fi
}

# Prompts and sudo requests stay visible and are included in the log.
run_interactive() {
  "$@" > >(tee -a "${INSTALL_LOG}") 2>&1
}

step() {
  CURRENT_STEP=$((CURRENT_STEP + 1))
  STEP_TITLE="$1"
  printf '[%d/%d] %s\n' "${CURRENT_STEP}" "${TOTAL_STEPS}" "${STEP_TITLE}"
  printf '\n[%d/%d] %s\n' "${CURRENT_STEP}" "${TOTAL_STEPS}" "${STEP_TITLE}" >>"${INSTALL_LOG}"
}

info() {
  printf '  -> %s\n' "$1"
}

ok() {
  printf '  [ok] %s\n' "$1"
}

warn() {
  printf '  [warn] %s\n' "$1"
}

die() {
  FAILURE_MESSAGE="$1"
  printf '  [fail] %s\n' "$1" >&2
  exit 1
}

record_error() {
  local status="$1" line="$2"
  # Do not log BASH_COMMAND: clone URLs and config commands may contain secrets.
  if [[ -n "${INSTALL_LOG}" ]]; then
    printf 'Installer line %s failed (exit %s).\n' "${line}" "${status}" >>"${INSTALL_LOG}"
  fi
}

on_exit() {
  local status=$?
  exec 1>&3 2>&4
  trap - EXIT ERR INT TERM
  set +e
  if [[ "${INSTALL_SUCCEEDED}" != true ]]; then
    [[ "${status}" -ne 0 ]] || status=1
    {
      printf '\nEasySRT installation did not complete.\n'
      printf 'Stopped at step %d/%d: %s (exit %d).\n' "${CURRENT_STEP}" "${TOTAL_STEPS}" "${STEP_TITLE}" "${status}"
      [[ -z "${FAILURE_MESSAGE}" ]] || printf 'Reason: %s\n' "${FAILURE_MESSAGE}"
      if [[ -n "${INSTALL_LOG}" ]]; then
        printf 'Read the detailed error: tail -n 60 %q\n' "${INSTALL_LOG}"
      fi
      case "${CURRENT_STEP}" in
        1) printf 'Use Ubuntu Server 24.04 or newer with Python 3.12+.\n' ;;
        2) printf 'Run sudo -v from a sudo-capable login, then retry.\n' ;;
        3|7|8) printf 'Check the log for package, network or build errors; resolve them, then retry.\n' ;;
        5) printf 'Check repository access and any local changes reported in the log before retrying.\n' ;;
        6) printf 'Check the config permissions and port/origin settings reported in the log, then retry.\n' ;;
        9|10|11)
          printf 'Check service errors: sudo journalctl -u justso-easysrt-helper -u justso-easysrt-backend -u justso-easysrt-frontend -u justso-easysrt-updater -n 60 --no-pager\n'
          ;;
      esac
      printf 'After fixing the error, rerun the same installer command.\n'
      printf 'Keep the log for troubleshooting; it may contain private repository details.\n'
    } >&2
  fi
  if [[ -n "${TRUSTED_TMP}" ]]; then
    sudo rm -rf -- "${TRUSTED_TMP}" || printf 'Could not remove temporary source: %s\n' "${TRUSTED_TMP}" >&2
  fi
  exit "${status}"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' is not available."
}

build_clone_url() {
  if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    printf '%s' "${REPO_URL}"
    return
  fi

  [[ "${GITHUB_TOKEN}" =~ ^[A-Za-z0-9_]+$ ]] || die "Invalid GitHub token format."

  case "${REPO_URL}" in
    https://github.com/*)
      printf 'https://x-access-token:%s@github.com/%s' "${GITHUB_TOKEN}" "${REPO_URL#https://github.com/}"
      ;;
    *)
      printf '%s' "${REPO_URL}"
      ;;
  esac
}

repo_needs_token() {
  case "${REPO_URL}" in
    https://github.com/*) ;;
    *)
      return 1
      ;;
  esac

  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    return 1
  fi

  git -C / -c core.hooksPath=/dev/null ls-remote --heads "${REPO_URL}" "${REPO_REF}" >/dev/null 2>&1
  test $? -ne 0
}

ensure_repo_token_if_needed() {
  local clone_url

  if ! repo_needs_token; then
    return
  fi

  if [[ ! -t 0 ]]; then
    die "This GitHub repo appears to require authentication. Re-run with GITHUB_TOKEN set."
  fi

  info "GitHub authentication is required to clone ${REPO_URL}"
  read -r -s -p "GitHub token: " GITHUB_TOKEN
  printf '\n'

  if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    die "A GitHub token is required to continue."
  fi

  clone_url="$(build_clone_url)"
  git -C / -c core.hooksPath=/dev/null ls-remote --heads "${clone_url}" "${REPO_REF}" >/dev/null 2>&1 || die "GitHub token could not access ${REPO_URL}"
  ok "GitHub token accepted."
}

detect_host() {
  require_command uname
  require_command awk

  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_NAME="${NAME:-Unknown}"
    OS_VERSION="${VERSION_ID:-Unknown}"
  else
    die "Unable to detect operating system. /etc/os-release is missing."
  fi
}

assert_supported_ubuntu() {
  [[ "${OS_NAME}" == "Ubuntu" ]] || die "This installer currently supports Ubuntu only. Detected: ${OS_NAME}"
  python3 - "${OS_VERSION}" <<'PY' || die "Ubuntu 24.04 or newer is required because EasySRT needs Python 3.12+."
import sys
version = tuple(int(part) for part in sys.argv[1].split(".")[:2])
sys.exit(0 if version >= (24, 4) else 1)
PY
}

detect_primary_ip() {
  local route_ip
  route_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' || true)"
  if [[ -n "${route_ip}" ]]; then
    PRIMARY_IP="${route_ip}"
    return
  fi
  route_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ -n "${route_ip}" ]]; then
    PRIMARY_IP="${route_ip}"
  fi
}

list_ip_addresses() {
  hostname -I 2>/dev/null | xargs || true
}

list_used_ports() {
  ss -ltnH 2>/dev/null | awk '{print $4}' | sed 's/.*://g' | sort -n | uniq | xargs || true
}

port_is_free() {
  local port="$1"
  ! ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"
}

find_recommended_port() {
  local candidate
  for candidate in 5173 3000 8080 8090 8181 9000; do
    if port_is_free "${candidate}"; then
      RECOMMENDED_FRONTEND_PORT="${candidate}"
      return
    fi
  done
  RECOMMENDED_FRONTEND_PORT="5173"
}

read_runtime_env_value() {
  local key="$1"
  sudo awk -v key="${key}" '
    index($0, key "=") == 1 {
      print substr($0, length(key) + 2)
      exit
    }
  ' "${ENV_FILE}"
}

load_existing_runtime_config() {
  local value

  sudo test -f "${ENV_FILE}" || return 0
  EXISTING_RUNTIME_CONFIG="true"

  value="$(read_runtime_env_value EASYSRT_FRONTEND_PORT)"
  [[ -z "${value}" ]] || FRONTEND_PORT="${value}"
  value="$(read_runtime_env_value EASYSRT_FRONTEND_HOST)"
  [[ -z "${value}" ]] || FRONTEND_HOST="${value}"
  value="$(read_runtime_env_value EASYSRT_BACKEND_HOST)"
  [[ -z "${value}" ]] || BACKEND_HOST="${value}"
  value="$(read_runtime_env_value EASYSRT_BACKEND_PORT)"
  [[ -z "${value}" ]] || BACKEND_PORT="${value}"
  value="$(read_runtime_env_value EASYSRT_UPDATER_PORT)"
  [[ -z "${value}" ]] || UPDATER_PORT="${value}"
  if [[ -z "${PUBLIC_ORIGIN}" ]]; then
    PUBLIC_ORIGIN="$(read_runtime_env_value EASYSRT_FRONTEND_ORIGIN)"
  fi
}

prompt_with_default() {
  local prompt="$1"
  local default="$2"
  local response=""
  if [[ -t 0 ]]; then
    read -r -p "${prompt} [${default}]: " response
  fi
  printf '%s' "${response:-$default}"
}

prompt_yes_no_default() {
  local prompt="$1"
  local default="$2"
  local response=""
  if [[ -t 0 ]]; then
    read -r -p "${prompt} [${default}]: " response
  fi
  response="${response:-$default}"
  [[ "${response}" =~ ^[Yy]$ ]]
}

ensure_sudo() {
  command -v sudo >/dev/null 2>&1 || die "sudo is not installed. Log into a sudo-capable account first."
  info "Checking sudo access for ${INSTALLING_USER}"
  if sudo -n true >/dev/null 2>&1; then
    ok "Passwordless sudo access confirmed."
    return
  fi
  if [[ -t 0 ]] && sudo -v; then
    ok "Sudo access confirmed."
    return
  fi
  die "${INSTALLING_USER} is not a sudoer. Log into a sudo-capable account or ask an administrator to grant sudo access."
}

apt_update_done=0
apt_install_if_missing() {
  local package
  local -a missing=()
  for package in "$@"; do
    if ! dpkg -s "${package}" >/dev/null 2>&1; then
      missing+=("${package}")
    fi
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "Base Ubuntu packages already present."
    return
  fi
  if [[ ${apt_update_done} -eq 0 ]]; then
    info "Refreshing apt package index"
    sudo apt-get update -y
    apt_update_done=1
  fi
  info "Installing packages: ${missing[*]}"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
}

node_runtime_supported() {
  command -v node >/dev/null 2>&1 || return 1
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 22 && minor >= 13) || major > 22 ? 0 : 1)'
}

ensure_node_runtime() {
  if node_runtime_supported; then
    ok "Node.js $(node --version) is suitable for the frontend build."
    return
  fi

  info "Installing Node.js 22.x (at least 22.13 is required)."
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  apt_update_done=1
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  node_runtime_supported || die "Node.js 22.13+ is required; Node 22 LTS is recommended."
  ok "Node.js upgraded."
}

ensure_uv() {
  # Keep deployment tooling outside the application environment so uv sync can
  # remove stale packages without removing its own executable.
  sudo install -d -o root -g root -m 0755 "${TOOLS_DIR}"
  if [[ ! -x "${TOOLS_DIR}/bin/python" ]]; then
    sudo python3 -m venv "${TOOLS_DIR}"
  fi
  sudo "${TOOLS_DIR}/bin/python" -m pip install "uv==${UV_VERSION}"
}

ensure_pnpm() {
  if ! command -v npm >/dev/null 2>&1; then
    die "npm is not available after Node.js installation."
  fi
  if command -v corepack >/dev/null 2>&1; then
    info "Enabling corepack and preparing pnpm"
    sudo corepack enable
    sudo corepack prepare pnpm@10.17.1 --activate
  fi
  if ! command -v pnpm >/dev/null 2>&1; then
    info "Installing pnpm globally"
    sudo npm install -g pnpm@10.17.1
  fi
  ok "pnpm is available."
}

assert_python_version() {
  python3 - <<'PY' || die "Python 3.12+ is required."
import sys
sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY
  ok "Python version is compatible."
}

ensure_user_and_group() {
  if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
    info "Creating group ${APP_GROUP}"
    sudo groupadd --system "${APP_GROUP}"
  else
    ok "Group ${APP_GROUP} already exists."
  fi

  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    info "Creating service user ${APP_USER}"
    sudo useradd --system --gid "${APP_GROUP}" --create-home --home-dir "/home/${APP_USER}" --shell /usr/sbin/nologin "${APP_USER}"
  else
    ok "User ${APP_USER} already exists."
  fi

  if [[ "${INSTALLING_USER}" != "root" ]]; then
    sudo usermod -aG "${APP_GROUP}" "${INSTALLING_USER}"
    ok "Added ${INSTALLING_USER} to ${APP_GROUP}."
  fi
}

clone_or_update_repo() {
  local clone_url
  ensure_repo_token_if_needed
  clone_url="$(build_clone_url)"
  sudo mkdir -p "$(dirname "${APP_DIR}")"
  if [[ ! -d "${APP_DIR}/.git" ]]; then
    info "Cloning ${REPO_URL} (${REPO_REF}) into ${APP_DIR}"
    sudo rm -rf "${APP_DIR}"
    sudo install -d -o "${APP_USER}" -g "${APP_GROUP}" "${APP_DIR}"
    sudo -u "${APP_USER}" git -C "${APP_DIR}" init --quiet
    sudo -u "${APP_USER}" git -C "${APP_DIR}" remote add origin "${REPO_URL}"
    sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch "${clone_url}" "${TRUSTED_COMMIT}" --depth 1
    sudo -u "${APP_USER}" git -C "${APP_DIR}" checkout --detach FETCH_HEAD
  else
    info "Updating existing repo in ${APP_DIR}"
    if [[ -n "$(sudo -u "${APP_USER}" git -C "${APP_DIR}" status --porcelain)" ]]; then
      die "Existing repo at ${APP_DIR} has uncommitted changes. Clean it before re-running the installer."
    fi
    sudo -u "${APP_USER}" git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
    sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch "${clone_url}" "${TRUSTED_COMMIT}" --depth 1
    sudo -u "${APP_USER}" git -C "${APP_DIR}" checkout --detach FETCH_HEAD
  fi
  sudo -u "${APP_USER}" git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  ok "Repo ready at ${APP_DIR}."
}

configure_runtime() {
  local allow_insecure_http
  local frontend_host_default="n"
  local origin_host
  local secret_key
  local session_cookie_secure

  load_existing_runtime_config
  if [[ "${EXISTING_RUNTIME_CONFIG}" == "true" ]]; then
    RECOMMENDED_FRONTEND_PORT="${FRONTEND_PORT}"
    info "Reusing runtime settings from ${ENV_FILE}"
  else
    find_recommended_port
  fi
  detect_primary_ip
  info "Detected IP addresses: $(list_ip_addresses)"
  [[ "${VERBOSE}" != "1" ]] || info "Currently used TCP ports: $(list_used_ports)"
  FRONTEND_PORT="$(prompt_with_default "Frontend port" "${RECOMMENDED_FRONTEND_PORT}")"
  if ! [[ "${FRONTEND_PORT}" =~ ^[0-9]+$ ]] || (( FRONTEND_PORT < 1 || FRONTEND_PORT > 65535 )); then
    die "Frontend port must be a valid TCP port."
  fi
  if [[ "${EXISTING_RUNTIME_CONFIG}" == "true" ]] && ! port_is_free "${FRONTEND_PORT}"; then
    info "Existing EasySRT frontend port ${FRONTEND_PORT} is currently in use."
  elif ! port_is_free "${FRONTEND_PORT}"; then
    warn "Port ${FRONTEND_PORT} is already in use."
  fi
  if [[ "${FRONTEND_HOST}" == "127.0.0.1" ]]; then
    frontend_host_default="y"
  fi
  if prompt_yes_no_default "Bind frontend to localhost only (good for tunnel-only installs)?" "${frontend_host_default}"; then
    FRONTEND_HOST="127.0.0.1"
  else
    FRONTEND_HOST="0.0.0.0"
  fi

  STATION_NAME="$(prompt_with_default "Station name" "${STATION_NAME}")"
  SUPPORT_CONTACT="$(prompt_with_default "Support contact" "${SUPPORT_CONTACT}")"

  sudo install -d -o root -g "${APP_GROUP}" -m 0750 "${CONFIG_DIR}"
  if sudo test -f "${ENV_FILE}" && sudo grep -q '^EASYSRT_SECRET_KEY=' "${ENV_FILE}"; then
    secret_key="$(sudo awk -F= '/^EASYSRT_SECRET_KEY=/{sub(/^EASYSRT_SECRET_KEY=/,""); print; exit}' "${ENV_FILE}")"
  else
    secret_key="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi

  if [[ -z "${PUBLIC_ORIGIN}" ]]; then
    if [[ "${FRONTEND_HOST}" == "127.0.0.1" ]]; then
      PUBLIC_ORIGIN="http://localhost:${FRONTEND_PORT}"
    else
      PUBLIC_ORIGIN="http://${PRIMARY_IP}:${FRONTEND_PORT}"
    fi
  fi
  origin_host="$(python3 - "${PUBLIC_ORIGIN}" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit("EASYSRT_PUBLIC_ORIGIN must be an absolute http:// or https:// URL")
print(parsed.hostname)
PY
)" || die "Invalid EASYSRT_PUBLIC_ORIGIN: ${PUBLIC_ORIGIN}"

  if [[ "${PUBLIC_ORIGIN}" == https://* ]]; then
    session_cookie_secure="true"
    allow_insecure_http="false"
  else
    session_cookie_secure="false"
    allow_insecure_http="true"
    warn "LAN HTTP mode selected. Put EasySRT behind HTTPS before exposing it beyond a trusted network."
  fi

  sudo tee "${ENV_FILE}" >/dev/null <<EOF
EASYSRT_ENVIRONMENT=production
EASYSRT_SECRET_KEY=${secret_key}
EASYSRT_SESSION_COOKIE_SECURE=${session_cookie_secure}
EASYSRT_ALLOW_INSECURE_HTTP=${allow_insecure_http}
EASYSRT_FRONTEND_HOST=${FRONTEND_HOST}
EASYSRT_FRONTEND_PORT=${FRONTEND_PORT}
EASYSRT_BACKEND_HOST=${BACKEND_HOST}
EASYSRT_BACKEND_PORT=${BACKEND_PORT}
EASYSRT_UPDATER_HOST=${FRONTEND_HOST}
EASYSRT_UPDATER_PORT=${UPDATER_PORT}
EASYSRT_FRONTEND_ORIGIN=${PUBLIC_ORIGIN}
EASYSRT_TRUSTED_HOSTS=${origin_host},${PRIMARY_IP},localhost,127.0.0.1
EASYSRT_SENDER_SERVICE_NAME=easysrt-sender
EASYSRT_HELPER_SOCKET_PATH=${HELPER_SOCKET_PATH}
EASYSRT_UPDATE_REPO_URL=${REPO_URL}
EASYSRT_UPDATE_REPO_REF=${REPO_REF}
EASYSRT_UPDATE_SCRIPT_PATH=${PRIVILEGED_DIR}/update-ubuntu.sh
EASYSRT_UPDATE_STATE_PATH=/var/lib/justso-easysrt-updates/update-job.json
EASYSRT_UPDATE_LOG_PATH=/var/lib/justso-easysrt-updates/update-job.log
EOF
  sudo chown root:"${APP_GROUP}" "${ENV_FILE}"
  sudo chmod 0640 "${ENV_FILE}"

  sudo python3 - "${CONFIG_DIR}/update-policy.json" "${REPO_URL}" "${REPO_REF}" <<'POLICY'
import json, sys
with open(sys.argv[1], "w") as handle:
    json.dump({"repo_url": sys.argv[2], "repo_ref": sys.argv[3]}, handle)
POLICY
  sudo chown root:root "${CONFIG_DIR}/update-policy.json"
  sudo chmod 0644 "${CONFIG_DIR}/update-policy.json"
  sudo install -d -o root -g root -m 0755 /var/lib/justso-easysrt-updates
  for filename in update-job.json update-job.log; do
    sudo test ! -L "/var/lib/justso-easysrt-updates/${filename}"
    if [[ ! -f "/var/lib/justso-easysrt-updates/${filename}" ]]; then
      printf '' | sudo tee "/var/lib/justso-easysrt-updates/${filename}" >/dev/null
    fi
    sudo chown root:"${APP_GROUP}" "/var/lib/justso-easysrt-updates/${filename}"
    sudo chmod 0660 "/var/lib/justso-easysrt-updates/${filename}"
  done

  sudo -u "${APP_USER}" mkdir -p "${BACKEND_DIR}/data"
  if [[ ! -f "${BACKEND_DIR}/data/app_config.json" ]]; then
    sudo -u "${APP_USER}" tee "${BACKEND_DIR}/data/app_config.json" >/dev/null <<EOF
{
  "station_name": "$(printf '%s' "${STATION_NAME}" | sed 's/"/\\"/g')",
  "support_contact": "$(printf '%s' "${SUPPORT_CONTACT}" | sed 's/"/\\"/g')"
}
EOF
  fi
  ok "Runtime configuration written."
}

install_backend() {
  info "Installing backend dependencies from uv.lock"
  [[ -f "${BACKEND_DIR}/uv.lock" ]] || die "Backend lockfile missing; refusing an unlocked production install."
  sudo -u "${APP_USER}" "${TOOLS_DIR}/bin/uv" sync --project "${BACKEND_DIR}" --locked --no-dev --no-editable --python /usr/bin/python3
  ok "Locked backend dependencies installed."
}

install_frontend() {
  info "Installing frontend dependencies"
  sudo -u "${APP_USER}" bash -lc "cd '${FRONTEND_DIR}' && pnpm install --frozen-lockfile"
  info "Building production frontend"
  sudo -u "${APP_USER}" bash -lc "cd '${FRONTEND_DIR}' && pnpm build"
  ok "Frontend production build ready."
}

prepare_privileged_source() {
  local clone_url
  ensure_repo_token_if_needed
  clone_url="$(build_clone_url)"
  TRUSTED_TMP="$(sudo mktemp -d /var/tmp/easysrt-trusted.XXXXXXXX)"
  # Never read root-executed code or Git configuration from the service user's
  # checkout. Resolve the administrator-approved remote in a private checkout.
  sudo env -i PATH=/usr/bin:/bin HOME="${TRUSTED_TMP}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    git -c core.hooksPath=/dev/null init --quiet "${TRUSTED_TMP}/repo"
  sudo env -i PATH=/usr/bin:/bin HOME="${TRUSTED_TMP}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    git -c core.hooksPath=/dev/null -C "${TRUSTED_TMP}/repo" fetch --depth 1 "${clone_url}" "${REPO_REF}"
  sudo env -i PATH=/usr/bin:/bin HOME="${TRUSTED_TMP}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    git -c core.hooksPath=/dev/null -C "${TRUSTED_TMP}/repo" checkout --detach FETCH_HEAD
  TRUSTED_COMMIT="$(sudo env -i PATH=/usr/bin:/bin HOME="${TRUSTED_TMP}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git -C "${TRUSTED_TMP}/repo" rev-parse HEAD)"
  PRIVILEGED_SOURCE="${TRUSTED_TMP}/repo/ops"
}

install_privileged_files() {
  local filename staging_file
  sudo install -d -o root -g root -m 0755 "${PRIVILEGED_DIR}"
  for filename in host-control-helper.py update-ubuntu.sh; do
    sudo test -f "${PRIVILEGED_SOURCE}/${filename}"
    sudo test ! -L "${PRIVILEGED_SOURCE}/${filename}"
    staging_file="$(sudo mktemp "${PRIVILEGED_DIR}/.install.XXXXXXXX")"
    sudo install -o root -g root -m 0755 "${PRIVILEGED_SOURCE}/${filename}" "${staging_file}"
    sudo mv -f "${staging_file}" "${PRIVILEGED_DIR}/${filename}"
  done
  for filename in justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service easysrt-sender.service; do
    sudo test -f "${PRIVILEGED_SOURCE}/${filename}"
    sudo test ! -L "${PRIVILEGED_SOURCE}/${filename}"
    sudo install -o root -g root -m 0644 "${PRIVILEGED_SOURCE}/${filename}" "/etc/systemd/system/${filename}"
  done
}

install_services() {
  info "Installing runtime scripts and service units"
  sudo -u "${APP_USER}" chmod +x "${APP_DIR}/ops/run-backend.sh" "${APP_DIR}/ops/run-frontend.sh" "${APP_DIR}/ops/run-updater.sh" "${APP_DIR}/ops/serve-frontend.py"
  install_privileged_files
  sudo rm -f /etc/sudoers.d/justso-easysrt-update
  sudo systemctl daemon-reload
  sudo systemctl enable justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service
  sudo systemctl disable easysrt-sender.service >/dev/null 2>&1 || true
  sudo systemctl reset-failed easysrt-sender.service >/dev/null 2>&1 || true
  sudo systemctl restart justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service
  ok "Systemd services installed."
}

health_check() {
  local backend_health="http://127.0.0.1:${BACKEND_PORT}/health"
  local updater_health="http://127.0.0.1:${UPDATER_PORT}/health"
  local helper_socket_identity

  info "Validating helper service"
  sudo systemctl is-active --quiet justso-easysrt-helper.service || die "Host control helper service is not active"
  for _ in {1..40}; do
    sudo test -S "${HELPER_SOCKET_PATH}" && break
    sleep 0.25
  done
  sudo test -S "${HELPER_SOCKET_PATH}" || die "Host control helper socket is missing at ${HELPER_SOCKET_PATH}"
  helper_socket_identity="$(sudo stat -c '%U:%G' "${HELPER_SOCKET_PATH}")"
  [[ "${helper_socket_identity}" == "root:${APP_GROUP}" ]] || die "Host control helper socket permissions are too broad: ${helper_socket_identity}"
  info "Validating backend service"
  for _ in {1..40}; do
    curl -fsS "${backend_health}" >/dev/null 2>&1 && break
    sleep 0.25
  done
  curl -fsS "${backend_health}" >/dev/null || die "Backend health check failed at ${backend_health}"
  info "Validating frontend service"
  for _ in {1..40}; do
    curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1 && break
    sleep 0.25
  done
  curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null || die "Frontend health check failed on port ${FRONTEND_PORT}"
  info "Validating updater service"
  sudo systemctl is-active --quiet justso-easysrt-updater.service || die "Updater service is not active"
  for _ in {1..40}; do
    curl -fsS "${updater_health}" >/dev/null 2>&1 && break
    sleep 0.25
  done
  curl -fsS "${updater_health}" >/dev/null || die "Updater health check failed at ${updater_health}"
  if curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" | grep -q "/@vite/client"; then
    die "Frontend still appears to be serving a Vite dev build."
  fi
  ok "Backend, frontend, and updater health checks passed."
}

show_next_steps() {
  printf '\nEasySRT is ready.\n\n'
  if [[ "${FRONTEND_HOST}" == "127.0.0.1" && "${PUBLIC_ORIGIN}" != https://* ]]; then
    printf 'From your computer, open an SSH tunnel (keep it running):\n'
    printf '  ssh -N -L %s:127.0.0.1:%s -L %s:127.0.0.1:%s %s@%s\n' \
      "${FRONTEND_PORT}" "${FRONTEND_PORT}" "${UPDATER_PORT}" "${UPDATER_PORT}" "${INSTALLING_USER}" "${PRIMARY_IP}"
    printf 'Then open: http://localhost:%s\n' "${FRONTEND_PORT}"
  else
    printf 'Open in your browser: %s\n' "${PUBLIC_ORIGIN}"
  fi
  if [[ "${PUBLIC_ORIGIN}" == https://* ]]; then
    printf 'Use your configured HTTPS reverse proxy for sign-in; TLS is not provisioned by this installer.\n'
  fi
  printf '\n1. Create your first owner account (or sign in if already configured).\n'
  printf '2. Configure your input and destination, then save.\n'
  printf '3. Start the sender from the Control tab when ready.\n'
  printf '\nInstalled ref: %s | Commit: %s\n' "${REPO_REF}" "${TRUSTED_COMMIT}"
  printf 'Installation log: %s\n' "${INSTALL_LOG}"
}

main() {
  print_banner
  init_logging

  step "Validating Ubuntu host"
  run_logged detect_host
  run_logged assert_supported_ubuntu
  run_logged detect_primary_ip
  run_logged find_recommended_port
  info "OS: ${OS_NAME} ${OS_VERSION}"

  step "Checking sudo access"
  run_interactive ensure_sudo

  step "Installing base packages"
  run_logged apt_install_if_missing git curl ca-certificates ffmpeg python3 python3-venv build-essential acl rsync
  run_logged ensure_node_runtime
  run_logged ensure_pnpm
  run_logged assert_python_version
  run_logged ensure_uv

  step "Creating service user and group"
  run_logged ensure_user_and_group

  step "Installing or updating the EasySRT repo"
  ensure_repo_token_if_needed
  run_logged prepare_privileged_source
  run_logged clone_or_update_repo

  step "Configuring runtime ports and local install settings"
  run_interactive configure_runtime

  step "Installing backend dependencies"
  run_logged install_backend

  step "Installing frontend dependencies and building production assets"
  run_logged install_frontend

  step "Installing systemd services"
  run_logged install_services

  step "Re-checking network state and selected frontend port"
  run_logged detect_primary_ip

  step "Running final health checks and showing next steps"
  run_logged health_check
  INSTALL_SUCCEEDED=true
  show_next_steps
}

trap 'record_error "$?" "$LINENO"' ERR
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
main "$@"
