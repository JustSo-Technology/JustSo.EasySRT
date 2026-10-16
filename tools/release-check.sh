#!/usr/bin/env bash
set -euo pipefail

tag="${1:-}"
expected_tag="v0.1.0-alpha.1"

if [[ -z "${tag}" ]]; then
  printf 'Usage: %s <tag>\n' "$0" >&2
  exit 2
fi

if [[ ! "${tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  printf 'Invalid release tag: %s\n' "${tag}" >&2
  exit 1
fi

backend_version="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' backend/app/version.py)"
frontend_version="$(node -p "require('./frontend/package.json').version")"

if [[ "v${backend_version}" != "${tag}" ]]; then
  printf 'Backend display version %s does not match tag %s\n' "${backend_version}" "${tag}" >&2
  exit 1
fi
if [[ "v${frontend_version}" != "${tag}" ]]; then
  printf 'Frontend version %s does not match tag %s\n' "${frontend_version}" "${tag}" >&2
  exit 1
fi
python3 - "$tag" <<'PY'
import pathlib
import re
import sys
import tomllib

version = sys.argv[1][1:]
match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?", version)
if not match:
    sys.exit("Supported prerelease labels are alpha.N, beta.N and rc.N")
base, stage, number = match.groups()
python_version = base + ({"alpha": "a", "beta": "b", "rc": "rc"}[stage] + number if stage else "")
metadata = tomllib.loads(pathlib.Path("backend/pyproject.toml").read_text())
if metadata["project"]["version"] != python_version:
    sys.exit(f"Python package version must be {python_version} for this tag")
changelog = pathlib.Path("CHANGELOG.md").read_text()
if not re.search(r"^## " + re.escape(version) + r"(?:\s|$)", changelog, re.MULTILINE):
    sys.exit(f"CHANGELOG.md is missing a section for {version}")
PY
if [[ "${tag}" == "${expected_tag}" ]]; then
  printf 'Validated initial alpha tag %s\n' "${tag}"
else
  printf 'Validated release tag %s\n' "${tag}"
fi
