#!/usr/bin/env bash
set -euo pipefail

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
BACKUP_ROOT="/var/backups/justso-easysrt"
UPDATE_STATE_FILE="/var/lib/justso-easysrt-updates/update-job.json"
UPDATE_LOG_FILE="/var/lib/justso-easysrt-updates/update-job.log"
INSTALLING_USER="${SUDO_USER:-${USER:-}}"
TOTAL_STEPS=9
CURRENT_STEP=0

OS_NAME=""
OS_VERSION=""
KERNEL_VERSION=""
BACKEND_PORT="8000"
FRONTEND_PORT="5173"
UPDATER_PORT="5174"
BACKUP_PATH=""
LOG_FILE=""
CURRENT_COMMIT=""
ORIGINAL_ORIGIN=""
TARGET_COMMIT=""
TARGET_RESET_REF=""
STASH_REF=""
JOB_STATUS="idle"
CURRENT_STEP_LABEL=""
UPDATE_ERROR=""
ROLLBACK_SUCCEEDED=""
INSTALLED_COMMIT_AFTER=""
STATE_STARTED_AT=""
STATE_FINISHED_AT=""
STATE_CHECKED_AT=""
STATE_PID=""

if [[ -z "${INSTALLING_USER}" ]]; then
  INSTALLING_USER="$(id -un 2>/dev/null || printf 'root')"
fi

# The host-control helper already runs as root. Avoid invoking the setuid
# sudo binary while still dropping privileges for repository and build work.
if [[ ${EUID} -eq 0 ]]; then
  sudo() {
    local run_as_home=""
    local run_as_user=""

    while (($# > 0)); do
      case "$1" in
        -n | -E)
          shift
          ;;
        -v)
          return 0
          ;;
        -u)
          [[ $# -ge 2 ]] || return 2
          run_as_user="$2"
          shift 2
          ;;
        --)
          shift
          break
          ;;
        *)
          break
          ;;
      esac
    done

    if [[ -n "${run_as_user}" ]]; then
      run_as_home="$(getent passwd "${run_as_user}" | cut -d: -f6)"
      [[ -n "${run_as_home}" ]] || run_as_home="/home/${run_as_user}"
      command setpriv --reuid="${run_as_user}" --regid="${run_as_user}" --init-groups \
        env HOME="${run_as_home}" USER="${run_as_user}" LOGNAME="${run_as_user}" "$@"
      return
    fi
    command env "$@"
  }
fi

print_banner() {
  cat <<'EOF'
==============================================
         JustSo.EasySRT Ubuntu Updater
==============================================
            _           _____ ____  _____
           | |         / ____|  _ \|_   _|
           | |  _   _ | (___ | |_) | | |
       _   | | | | | | \___ \|  _ <  | |
      | |__| | | |_| | ____) | |_) |_| |_
       \____/   \__,_| |_____/|____/|_____|

This updater refreshes an existing production EasySRT VM.
EOF
}

ensure_update_tracking() {
  [[ ${EUID} -eq 0 ]] || { printf 'Run the installed updater with sudo.\n' >&2; exit 1; }
  python3 - "${UPDATE_STATE_FILE}" "${UPDATE_LOG_FILE}" <<'TRACKING'
import os, stat, sys
for value in sys.argv[1:]:
    directory = os.path.dirname(value)
    entry = os.lstat(directory)
    if not stat.S_ISDIR(entry.st_mode) or entry.st_uid != 0 or entry.st_mode & 0o022:
        raise SystemExit("Unsafe update tracking directory")
    entry = os.lstat(value)
    if not stat.S_ISREG(entry.st_mode) or entry.st_uid != 0 or entry.st_nlink != 1:
        raise SystemExit("Unsafe update tracking file")
TRACKING
  exec 9>/var/lib/justso-easysrt-updates/update.lock
  flock -n 9 || { printf 'Another update is running.\n' >&2; exit 1; }
  : > "${UPDATE_LOG_FILE}"
}

append_update_log() {
  printf '%s\n' "$1" >> "${UPDATE_LOG_FILE}"
}

write_update_state() {
  REPO_URL="${REPO_URL}" \
  REPO_REF="${REPO_REF}" \
  JOB_STATUS="${JOB_STATUS}" \
  CURRENT_STEP_LABEL="${CURRENT_STEP_LABEL}" \
  STATE_CHECKED_AT="${STATE_CHECKED_AT}" \
  STATE_STARTED_AT="${STATE_STARTED_AT}" \
  STATE_FINISHED_AT="${STATE_FINISHED_AT}" \
  CURRENT_COMMIT="${CURRENT_COMMIT}" \
  INSTALLED_COMMIT_AFTER="${INSTALLED_COMMIT_AFTER}" \
  TARGET_COMMIT="${TARGET_COMMIT}" \
  UPDATE_ERROR="${UPDATE_ERROR}" \
  BACKUP_PATH="${BACKUP_PATH}" \
  STASH_REF="${STASH_REF}" \
  ROLLBACK_SUCCEEDED="${ROLLBACK_SUCCEEDED}" \
  STATE_PID="${STATE_PID}" \
  python3 - "${UPDATE_STATE_FILE}" <<'PY'
import json
import os
import sys

path = sys.argv[1]
payload = {
    "repo_url": os.environ.get("REPO_URL"),
    "repo_ref": os.environ.get("REPO_REF"),
    "job_status": os.environ.get("JOB_STATUS", "idle"),
    "current_step": os.environ.get("CURRENT_STEP_LABEL") or None,
    "checked_at": os.environ.get("STATE_CHECKED_AT") or None,
    "started_at": os.environ.get("STATE_STARTED_AT") or None,
    "finished_at": os.environ.get("STATE_FINISHED_AT") or None,
    "installed_commit_before": os.environ.get("CURRENT_COMMIT") or None,
    "installed_commit_after": os.environ.get("INSTALLED_COMMIT_AFTER") or None,
    "latest_commit": os.environ.get("TARGET_COMMIT") or None,
    "error": os.environ.get("UPDATE_ERROR") or None,
    "backup_path": os.environ.get("BACKUP_PATH") or None,
    "stash_ref": os.environ.get("STASH_REF") or None,
    "rollback_succeeded": None if os.environ.get("ROLLBACK_SUCCEEDED", "") == "" else os.environ.get("ROLLBACK_SUCCEEDED") == "true",
    "pid": int(os.environ["STATE_PID"]) if os.environ.get("STATE_PID") else None,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
PY
}

on_exit() {
  local exit_code=$?
  [[ -z "${TRUSTED_TMP}" ]] || sudo rm -rf -- "${TRUSTED_TMP}"
  if [[ ${exit_code} -ne 0 && "${JOB_STATUS}" == "running" ]]; then
    JOB_STATUS="failed"
    UPDATE_ERROR="${UPDATE_ERROR:-Update exited unexpectedly with code ${exit_code}}"
    STATE_FINISHED_AT="$(date --iso-8601=seconds)"
    INSTALLED_COMMIT_AFTER="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || true)"
    write_update_state
  fi
}

trap on_exit EXIT

step() {
  CURRENT_STEP=$((CURRENT_STEP + 1))
  CURRENT_STEP_LABEL="$1"
  write_update_state
  printf '\n[%d/%d] %s\n' "${CURRENT_STEP}" "${TOTAL_STEPS}" "$1"
  append_update_log "[$CURRENT_STEP/$TOTAL_STEPS] $1"
}

info() {
  printf '  -> %s\n' "$1"
  append_update_log "  -> $1"
}

ok() {
  printf '  [ok] %s\n' "$1"
  append_update_log "  [ok] $1"
}

warn() {
  printf '  [warn] %s\n' "$1"
  append_update_log "  [warn] $1"
}

die() {
  JOB_STATUS="failed"
  UPDATE_ERROR="$1"
  STATE_FINISHED_AT="$(date --iso-8601=seconds)"
  INSTALLED_COMMIT_AFTER="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || true)"
  write_update_state
  printf '  [fail] %s\n' "$1" >&2
  append_update_log "  [fail] $1"
  exit 1
}

record_log() {
  local message="$1"
  if [[ -n "${LOG_FILE}" ]]; then
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${message}" | sudo tee -a "${LOG_FILE}" >/dev/null
  fi
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

  info "GitHub authentication is required to fetch ${REPO_URL}"
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
  KERNEL_VERSION="$(uname -r)"
}

assert_supported_ubuntu() {
  [[ "${OS_NAME}" == "Ubuntu" ]] || die "This updater currently supports Ubuntu only. Detected: ${OS_NAME}"
  python3 - "${OS_VERSION}" <<'PY' || die "Ubuntu 24.04 or newer is required because EasySRT needs Python 3.12+."
import sys
version = tuple(int(part) for part in sys.argv[1].split(".")[:2])
sys.exit(0 if version >= (24, 4) else 1)
PY
}

ensure_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    require_command setpriv
    ok "Updater is already running with root privileges."
    return
  fi
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
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)'
}

ensure_node_runtime() {
  if node_runtime_supported; then
    ok "Node.js $(node --version) is suitable for the frontend build."
    return
  fi

  info "Installing Node.js 22.x (at least 22.12 is required)."
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  apt_update_done=1
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  node_runtime_supported || die "Node.js 20.19+ or 22.12+ is required (Node 21 is unsupported)."
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

read_env_value() {
  local key="$1"
  local fallback="$2"
  if [[ -f "${ENV_FILE}" ]]; then
    awk -F= -v key="${key}" '$1 == key {sub(/^[^=]+=*/, "", $0); print $0; found=1; exit} END {if (!found) print ""}' "${ENV_FILE}"
  else
    printf '%s' "${fallback}"
  fi
}

ensure_config_permissions() {
  sudo install -d -o root -g "${APP_GROUP}" -m 0750 "${CONFIG_DIR}" || return 1
  sudo chown root:"${APP_GROUP}" "${ENV_FILE}" || return 1
  sudo chmod 0640 "${ENV_FILE}" || return 1
}

load_runtime_ports() {
  BACKEND_PORT="$(read_env_value "EASYSRT_BACKEND_PORT" "8000")"
  FRONTEND_PORT="$(read_env_value "EASYSRT_FRONTEND_PORT" "5173")"
  UPDATER_PORT="$(read_env_value "EASYSRT_UPDATER_PORT" "5174")"
  [[ -n "${BACKEND_PORT}" ]] || BACKEND_PORT="8000"
  [[ -n "${FRONTEND_PORT}" ]] || FRONTEND_PORT="5173"
  [[ -n "${UPDATER_PORT}" ]] || UPDATER_PORT="5174"
}

load_repo_auth() {
  local configured_token=""
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    return
  fi

  configured_token="$(read_env_value "EASYSRT_GITHUB_TOKEN" "")"
  if [[ -z "${configured_token}" ]]; then
    return
  fi

  GITHUB_TOKEN="${configured_token}"
  export GITHUB_TOKEN
  ok "Using configured GitHub token for update checks."
}

ensure_repo_ownership() {
  sudo -u "${APP_USER}" test -w "${APP_DIR}" || die "Application checkout is not writable by ${APP_USER}; repair it as an administrator."
}

verify_existing_install() {
  [[ -d "${APP_DIR}" ]] || die "No EasySRT install found at ${APP_DIR}"
  [[ -d "${APP_DIR}/.git" ]] || die "${APP_DIR} is not a git checkout"
  [[ -d "${BACKEND_DIR}" ]] || die "Backend directory missing at ${BACKEND_DIR}"
  [[ -d "${FRONTEND_DIR}" ]] || die "Frontend directory missing at ${FRONTEND_DIR}"
  [[ -f "${ENV_FILE}" ]] || die "Environment file missing at ${ENV_FILE}"
  ensure_config_permissions
  ensure_repo_ownership
  CURRENT_COMMIT="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" rev-parse HEAD)"
  ORIGINAL_ORIGIN="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" remote get-url origin)"
  INSTALLED_COMMIT_AFTER="${CURRENT_COMMIT}"
  load_runtime_ports
  load_repo_auth
  local policy_url policy_ref
  policy_url="$(python3 -c 'import json; print(json.load(open("/etc/justso-easysrt/update-policy.json"))["repo_url"])')"
  policy_ref="$(python3 -c 'import json; print(json.load(open("/etc/justso-easysrt/update-policy.json"))["repo_ref"])')"
  REPO_URL="${EASYSRT_REPO_URL:-${policy_url}}"
  REPO_REF="${EASYSRT_REPO_REF:-${policy_ref}}"
  [[ "${REPO_URL}" == "${policy_url}" && "${REPO_REF}" == "${policy_ref}" ]] || die "Update target must match the administrator-owned update policy."
  ok "Existing EasySRT install detected."
}

create_data_backup() {
  local backend_was_active=false archive_status=0
  if sudo systemctl is-active --quiet justso-easysrt-backend.service; then
    backend_was_active=true
  fi
  # Quiesce configuration/SQLite writers so the archive is a consistent set.
  sudo systemctl stop justso-easysrt-backend.service || return 1
  sudo -u "${APP_USER}" tar -C "${BACKEND_DIR}/data" -cf - . | sudo tee "${BACKUP_PATH}/data.tar" >/dev/null || archive_status=$?
  if [[ "${backend_was_active}" == true ]]; then
    sudo systemctl start justso-easysrt-backend.service || return 1
  fi
  return "${archive_status}"
}

create_backup() {
  local timestamp
  timestamp="$(date '+%Y%m%d-%H%M%S')"
  BACKUP_PATH="${BACKUP_ROOT}/${timestamp}"
  LOG_FILE="${BACKUP_PATH}/update.log"

  info "Creating update backup at ${BACKUP_PATH}"
  sudo install -d -o root -g root -m 0700 "${BACKUP_PATH}" "${BACKUP_PATH}/data"
  sudo cp "${ENV_FILE}" "${BACKUP_PATH}/easysrt.env"
  sudo install -d -o root -g root -m 0700 "${BACKUP_PATH}/privileged"
  sudo cp "${PRIVILEGED_DIR}/host-control-helper.py" "${PRIVILEGED_DIR}/update-ubuntu.sh" "${BACKUP_PATH}/privileged/"
  local unit
  for unit in justso-easysrt-helper justso-easysrt-backend justso-easysrt-frontend justso-easysrt-updater easysrt-sender; do
    sudo cp "/etc/systemd/system/${unit}.service" "${BACKUP_PATH}/privileged/"
  done
  create_data_backup
  sudo tee "${BACKUP_PATH}/metadata.txt" >/dev/null <<EOF
timestamp=${timestamp}
repo_url=${REPO_URL}
repo_ref=${REPO_REF}
current_commit=${CURRENT_COMMIT}
EOF
  write_update_state
  record_log "Backup created at ${BACKUP_PATH}"
  ok "Backup captured."
}

prune_old_backups() {
  local -a backups=()
  local old_backup
  while IFS= read -r old_backup; do
    backups+=("${old_backup}")
  done < <(sudo find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | sort)

  if [[ ${#backups[@]} -le 5 ]]; then
    ok "Backup retention is within limit."
    return
  fi

  for old_backup in "${backups[@]:0:${#backups[@]}-5}"; do
    info "Pruning old backup ${old_backup}"
    sudo rm -rf "${old_backup}"
  done
  ok "Old backups pruned."
}

stash_local_changes() {
  local status_output
  status_output="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" status --porcelain)" || return 1
  if [[ -z "${status_output}" ]]; then
    record_log "No local repo changes detected."
    ok "Repo working tree is clean."
    return
  fi

  info "Stashing local changes before update"
  sudo -u "${APP_USER}" git -C "${APP_DIR}" stash push --include-untracked -m "easysrt-update-$(date '+%Y%m%d-%H%M%S')" >/dev/null || return 1
  STASH_REF="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" rev-parse --verify 'stash@{0}')" || return 1
  sudo tee -a "${BACKUP_PATH}/metadata.txt" >/dev/null <<EOF || return 1
stash_ref=${STASH_REF}
EOF
  write_update_state || return 1
  record_log "Local changes stashed at ${STASH_REF}" || return 1
  ok "Local changes stashed as ${STASH_REF}."
}

prepare_target_commit() {
  local clone_url

  ensure_repo_token_if_needed
  clone_url="$(build_clone_url)"

  # Resolve the target without changing the working tree or its origin. A failed
  # fetch must leave the running installation and local fixes intact.
  TARGET_RESET_REF=""
  sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch "${clone_url}" "${TRUSTED_COMMIT}" --depth 1
  TARGET_COMMIT="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" rev-parse FETCH_HEAD)"

  sudo tee -a "${BACKUP_PATH}/metadata.txt" >/dev/null <<EOF
target_commit=${TARGET_COMMIT}
EOF
  write_update_state
  record_log "Preparing update from ${CURRENT_COMMIT} to ${TARGET_COMMIT}"
  info "Current commit: ${CURRENT_COMMIT}"
  info "Target commit:  ${TARGET_COMMIT}"
  ok "Target update commit resolved."
}

apply_repo_update() {
  info "Updating repo in ${APP_DIR}"
  sudo -u "${APP_USER}" git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  if [[ -n "${TARGET_RESET_REF}" ]]; then
    sudo -u "${APP_USER}" git -C "${APP_DIR}" checkout "${REPO_REF}" >/dev/null 2>&1 || sudo -u "${APP_USER}" git -C "${APP_DIR}" checkout -B "${REPO_REF}" "${TARGET_RESET_REF}" >/dev/null 2>&1
    sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard "${TARGET_RESET_REF}" >/dev/null
  else
    sudo -u "${APP_USER}" git -C "${APP_DIR}" checkout --detach "${TARGET_COMMIT}" >/dev/null
    sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard "${TARGET_COMMIT}" >/dev/null
  fi
  INSTALLED_COMMIT_AFTER="${TARGET_COMMIT}"
  write_update_state
  record_log "Repo reset to ${TARGET_COMMIT}"
  ok "Repo updated."
}

install_backend() {
  info "Installing backend dependencies from uv.lock"
  [[ -f "${BACKEND_DIR}/uv.lock" ]] || die "Backend lockfile missing; refusing an unlocked production install."
  sudo -u "${APP_USER}" "${TOOLS_DIR}/bin/uv" sync --project "${BACKEND_DIR}" --locked --no-dev --no-editable --python /usr/bin/python3 || return 1
  ok "Locked backend dependencies installed."
}

ensure_security_env_defaults() {
  local allow_insecure_http
  local frontend_origin
  local origin_host
  local session_cookie_secure
  local updater_host

  frontend_origin="$(read_env_value EASYSRT_FRONTEND_ORIGIN "")"
  [[ -n "${frontend_origin}" ]] || die "EASYSRT_FRONTEND_ORIGIN is missing from ${ENV_FILE}"

  if [[ "${frontend_origin}" == https://* ]]; then
    session_cookie_secure="true"
    allow_insecure_http="false"
  else
    session_cookie_secure="false"
    allow_insecure_http="true"
    warn "Existing LAN HTTP deployment retained. Configure HTTPS before exposing EasySRT beyond a trusted network."
  fi

  origin_host="$(python3 - "${frontend_origin}" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit(1)
print(parsed.hostname)
PY
)" || die "Invalid EASYSRT_FRONTEND_ORIGIN in ${ENV_FILE}"

  if [[ -z "$(read_env_value EASYSRT_SESSION_COOKIE_SECURE "")" ]]; then
    printf 'EASYSRT_SESSION_COOKIE_SECURE=%s\n' "${session_cookie_secure}" | sudo tee -a "${ENV_FILE}" >/dev/null
  fi
  if [[ -z "$(read_env_value EASYSRT_ALLOW_INSECURE_HTTP "")" ]]; then
    printf 'EASYSRT_ALLOW_INSECURE_HTTP=%s\n' "${allow_insecure_http}" | sudo tee -a "${ENV_FILE}" >/dev/null
  fi
  if [[ -z "$(read_env_value EASYSRT_TRUSTED_HOSTS "")" ]]; then
    printf 'EASYSRT_TRUSTED_HOSTS=%s\n' "${origin_host},localhost,127.0.0.1" | sudo tee -a "${ENV_FILE}" >/dev/null
  fi
  if [[ -z "$(read_env_value EASYSRT_UPDATER_HOST "")" ]]; then
    updater_host="$(read_env_value EASYSRT_FRONTEND_HOST "127.0.0.1")"
    [[ -n "${updater_host}" ]] || updater_host="127.0.0.1"
    printf 'EASYSRT_UPDATER_HOST=%s\n' "${updater_host}" | sudo tee -a "${ENV_FILE}" >/dev/null
  fi
  if [[ -z "$(read_env_value EASYSRT_UPDATER_PORT "")" ]]; then
    printf 'EASYSRT_UPDATER_PORT=%s\n' "${UPDATER_PORT}" | sudo tee -a "${ENV_FILE}" >/dev/null
  fi
  sudo python3 - "${ENV_FILE}" <<'ENVUPDATE'
from pathlib import Path
import sys
path = Path(sys.argv[1])
updates = {
    "EASYSRT_UPDATE_SCRIPT_PATH": "/usr/local/lib/justso-easysrt/update-ubuntu.sh",
    "EASYSRT_UPDATE_STATE_PATH": "/var/lib/justso-easysrt-updates/update-job.json",
    "EASYSRT_UPDATE_LOG_PATH": "/var/lib/justso-easysrt-updates/update-job.log",
}
lines = [line for line in path.read_text().splitlines() if line.split("=", 1)[0] not in updates]
path.write_text("\n".join(lines + [f"{key}={value}" for key, value in updates.items()]) + "\n")
ENVUPDATE
  ok "Production security environment is explicit."
}

install_frontend() {
  info "Refreshing frontend dependencies"
  sudo -u "${APP_USER}" bash -lc "cd '${FRONTEND_DIR}' && pnpm install --frozen-lockfile" || return 1
  info "Building production frontend"
  sudo -u "${APP_USER}" bash -lc "cd '${FRONTEND_DIR}' && pnpm build" || return 1
  record_log "Frontend build refreshed."
  ok "Frontend build refreshed."
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
  sudo install -d -o root -g root -m 0755 "${PRIVILEGED_DIR}" || return 1
  for filename in host-control-helper.py update-ubuntu.sh; do
    sudo test -f "${PRIVILEGED_SOURCE}/${filename}" || return 1
    sudo test ! -L "${PRIVILEGED_SOURCE}/${filename}" || return 1
    staging_file="$(sudo mktemp "${PRIVILEGED_DIR}/.install.XXXXXXXX")" || return 1
    sudo install -o root -g root -m 0755 "${PRIVILEGED_SOURCE}/${filename}" "${staging_file}" || return 1
    sudo mv -f "${staging_file}" "${PRIVILEGED_DIR}/${filename}" || return 1
  done
  for filename in justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service easysrt-sender.service; do
    sudo test -f "${PRIVILEGED_SOURCE}/${filename}" || return 1
    sudo test ! -L "${PRIVILEGED_SOURCE}/${filename}" || return 1
    sudo install -o root -g root -m 0644 "${PRIVILEGED_SOURCE}/${filename}" "/etc/systemd/system/${filename}" || return 1
  done
}

install_services() {
  info "Reinstalling runtime scripts and service units"
  sudo -u "${APP_USER}" chmod +x "${APP_DIR}/ops/run-backend.sh" "${APP_DIR}/ops/run-frontend.sh" "${APP_DIR}/ops/run-updater.sh" "${APP_DIR}/ops/serve-frontend.py" || return 1
  install_privileged_files || return 1
  sudo rm -f /etc/sudoers.d/justso-easysrt-update || return 1
  sudo systemctl daemon-reload || return 1
  record_log "Service units reinstalled and daemon reloaded."
  ok "Service units refreshed."
}

restart_services() {
  info "Restarting backend, frontend, and updater services"
  sudo systemctl restart justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service
  record_log "Backend, frontend, and updater services restarted."
  ok "Services restarted."
}

wait_for_http() {
  local url="$1"
  local attempts="$2"
  local delay="$3"
  local attempt

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

health_check() {
  local backend_health="http://127.0.0.1:${BACKEND_PORT}/health"
  local frontend_root="http://127.0.0.1:${FRONTEND_PORT}/"
  local updater_health="http://127.0.0.1:${UPDATER_PORT}/health"
  local frontend_body

  info "Validating backend service"
  if ! wait_for_http "${backend_health}" 15 2; then
    record_log "Backend health check failed at ${backend_health}"
    return 1
  fi

  info "Validating frontend service"
  if ! wait_for_http "${frontend_root}" 15 2; then
    record_log "Frontend health check failed at ${frontend_root}"
    return 1
  fi

  frontend_body="$(curl -fsS "${frontend_root}")"
  if grep -q "/@vite/client" <<<"${frontend_body}"; then
    record_log "Frontend response still references Vite dev mode."
    return 1
  fi

  info "Validating updater service"
  if ! wait_for_http "${updater_health}" 15 2; then
    record_log "Updater health check failed at ${updater_health}"
    return 1
  fi

  record_log "Health checks passed for backend=${backend_health} frontend=${frontend_root} updater=${updater_health}"
  write_update_state
  ok "Backend and frontend health checks passed."
}

rollback_update() {
  warn "Update failed. Starting automatic rollback."
  record_log "Update failed. Starting rollback."

  sudo systemctl stop justso-easysrt-frontend.service justso-easysrt-backend.service >/dev/null 2>&1 || true

  if [[ -n "${CURRENT_COMMIT}" ]]; then
    sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard "${CURRENT_COMMIT}" >/dev/null || return 1
  else
    return 1
  fi
  if [[ -n "${ORIGINAL_ORIGIN}" ]]; then
    sudo -u "${APP_USER}" git -C "${APP_DIR}" remote set-url origin "${ORIGINAL_ORIGIN}" || return 1
  fi
  if [[ -n "${STASH_REF}" ]]; then
    # Rebuild the original installation with its local fixes and staged state.
    # Keep the stash as an additional recovery copy, including on conflicts.
    sudo -u "${APP_USER}" git -C "${APP_DIR}" stash apply --index "${STASH_REF}" || return 1
  fi

  sudo mkdir -p "${CONFIG_DIR}" || return 1
  sudo -u "${APP_USER}" mkdir -p "${BACKEND_DIR}/data" || return 1
  sudo cp "${BACKUP_PATH}/easysrt.env" "${ENV_FILE}" || return 1
  ensure_config_permissions || return 1
  sudo -u "${APP_USER}" find "${BACKEND_DIR}/data/" -mindepth 1 -delete || return 1
  sudo cat "${BACKUP_PATH}/data.tar" | sudo -u "${APP_USER}" tar -C "${BACKEND_DIR}/data" -xf - || return 1
  write_update_state

  install_backend >/dev/null || return 1
  install_frontend >/dev/null || return 1
  PRIVILEGED_SOURCE="${BACKUP_PATH}/privileged"
  install_services >/dev/null || return 1
  sudo systemctl restart justso-easysrt-helper.service justso-easysrt-backend.service justso-easysrt-frontend.service justso-easysrt-updater.service >/dev/null || return 1

  if ! health_check >/dev/null; then
    record_log "Rollback failed."
    ROLLBACK_SUCCEEDED="false"
    JOB_STATUS="failed"
    STATE_FINISHED_AT="$(date --iso-8601=seconds)"
    INSTALLED_COMMIT_AFTER="$(sudo -u "${APP_USER}" git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || true)"
    write_update_state
    return 1
  fi

  record_log "Rollback succeeded."
  ROLLBACK_SUCCEEDED="true"
  JOB_STATUS="rolled_back"
  STATE_FINISHED_AT="$(date --iso-8601=seconds)"
  INSTALLED_COMMIT_AFTER="${CURRENT_COMMIT}"
  write_update_state
  return 0
}

run_update_pipeline() {
  apply_repo_update
  ensure_security_env_defaults
  install_backend
  install_frontend
  install_services
  restart_services
  health_check
}

final_success() {
  record_log "Update completed successfully."
  JOB_STATUS="succeeded"
  STATE_FINISHED_AT="$(date --iso-8601=seconds)"
  INSTALLED_COMMIT_AFTER="${TARGET_COMMIT}"
  write_update_state
  printf '\nUpdate complete.\n\n'
  printf 'Installed ref:    %s\n' "${REPO_REF}"
  printf 'Current commit:   %s\n' "${CURRENT_COMMIT}"
  printf 'Updated commit:   %s\n' "${TARGET_COMMIT}"
  printf 'Backup path:      %s\n' "${BACKUP_PATH}"
  if [[ -n "${STASH_REF}" ]]; then
    printf 'Stash ref:        %s\n' "${STASH_REF}"
  else
    printf 'Stash ref:        none\n'
  fi
  printf 'Backend health:   ok (127.0.0.1:%s)\n' "${BACKEND_PORT}"
  printf 'Frontend health:  ok (127.0.0.1:%s)\n' "${FRONTEND_PORT}"
}

main() {
  print_banner
  ensure_update_tracking
  STATE_PID="$$"
  STATE_STARTED_AT="$(date --iso-8601=seconds)"
  STATE_FINISHED_AT=""
  STATE_CHECKED_AT="${STATE_STARTED_AT}"
  JOB_STATUS="running"
  write_update_state

  step "Validating Ubuntu host"
  detect_host
  assert_supported_ubuntu
  info "OS: ${OS_NAME} ${OS_VERSION}"
  info "Kernel: ${KERNEL_VERSION}"
  ok "Host validation passed."

  step "Checking sudo access"
  ensure_sudo

  step "Verifying the existing EasySRT install"
  verify_existing_install
  info "Installed ref: ${REPO_REF}"
  info "Installed commit: ${CURRENT_COMMIT}"

  step "Ensuring base runtime prerequisites"
  apt_install_if_missing git curl ca-certificates ffmpeg python3 python3-venv build-essential acl rsync
  ensure_node_runtime
  ensure_pnpm
  assert_python_version
  ensure_uv

  step "Creating an automatic backup"
  create_backup
  prune_old_backups

  step "Resolving the target update commit"
  prepare_privileged_source
  prepare_target_commit

  step "Stashing local repo changes if needed"
  set +e
  stash_local_changes
  pipeline_status=$?
  if [[ ${pipeline_status} -eq 0 ]]; then
    step "Applying the update and restarting services"
    (
      set -e
      run_update_pipeline
    )
    pipeline_status=$?
  fi
  set -e
  if [[ ${pipeline_status} -ne 0 ]]; then
    UPDATE_ERROR="${UPDATE_ERROR:-Update pipeline failed with code ${pipeline_status}}"
    if rollback_update; then
      printf '\n[fail] Update failed, but rollback succeeded.\n' >&2
      printf 'Backup path: %s\n' "${BACKUP_PATH}" >&2
      printf 'Stash ref:   %s\n' "${STASH_REF:-none}" >&2
      exit 1
    fi
    printf '\n[fail] Update failed and automatic rollback did not recover the app.\n' >&2
    printf 'Backup path: %s\n' "${BACKUP_PATH}" >&2
    printf 'Restore config from %s and data from %s/data.tar if you need manual recovery.\n' "${BACKUP_PATH}" "${BACKUP_PATH}" >&2
    printf 'Stash ref:   %s\n' "${STASH_REF:-none}" >&2
    exit 1
  fi

  step "Reporting final status"
  final_success
}

main "$@"
