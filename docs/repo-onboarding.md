# JustSo.EasySRT Repo Onboarding

## 1. Repo Purpose And Product Shape

JustSo.EasySRT is a Linux-first control plane for configuring and running an audio contribution sender. The product couples:

- a FastAPI backend for auth, config persistence, diagnostics, service control, and update orchestration
- a React WebUI for login, control, configuration, diagnostics, admin, and updater entrypoints
- a root-owned local helper that performs privileged host actions through a Unix socket
- Ubuntu-oriented `systemd` services that run the backend, frontend, updater, and the `ffmpeg` sender process

The deployment model is opinionated. Production assumes Ubuntu Server, a service user named `easysrt`, a repo checkout at `/opt/justso-easysrt`, and runtime state under `/etc/justso-easysrt` plus `backend/data/`.

## 2. Directory Map

```
JustSo.EasySRT/
|-- backend/
|   |-- app/
|   |   |-- api/            # FastAPI route modules grouped by concern
|   |   |-- core/           # settings and database bootstrap
|   |   |-- models/         # SQLModel records and enums
|   |   |-- schemas/        # API request/response models
|   |   `-- services/       # config, diagnostics, service control, updates
|   |-- tests/              # backend API and service-flow tests
|   `-- pyproject.toml      # Python package and test dependencies
|-- frontend/
|   |-- src/
|   |   |-- components/     # shell and shared UI primitives
|   |   |-- features/       # auth, config, dashboard, diagnostics, admin, update
|   |   `-- lib/            # typed API client and helpers
|   `-- package.json        # Vite, React, Tailwind toolchain
|-- ops/                    # installer, updater, helper, runtime scripts, systemd units
|-- docs/
|   |-- development.md
|   `-- repo-onboarding.md
`-- README.md
```

First-read files:

- Backend: `backend/app/main.py`, `backend/app/core/settings.py`, `backend/app/core/db.py`, `backend/app/api/*.py`, `backend/app/services/*.py`, `backend/tests/test_api.py`
- Frontend: `frontend/src/main.tsx`, `frontend/src/app.tsx`, `frontend/src/lib/api.ts`, `frontend/src/components/layout/app-shell.tsx`, `frontend/src/features/*`
- Ops: `README.md`, `ops/install-ubuntu.sh`, `ops/update-ubuntu.sh`, `ops/host-control-helper.py`, `ops/run-backend.sh`, `ops/run-frontend.sh`, `ops/*.service`

## 3. Backend Architecture And Request Flow

### Entry Point

`backend/app/main.py` is the control-plane HTTP entrypoint.

- FastAPI lifespan calls `init_db()`
- CORS allows exactly `settings.frontend_origin`
- routers are mounted under `settings.api_prefix`, default `/api`
- `/health` is the unauthenticated probe used by install/update checks

### Core Runtime

`backend/app/core/settings.py` defines the deployment contract:

- app root defaults to `/opt/justso-easysrt`
- data and SQLite paths default to `backend/data/*` in development and `/opt/justso-easysrt/backend/data/*` in production-style installs
- sender service name defaults to `easysrt-sender`
- privileged helper socket defaults to `/run/justso-easysrt/helper.sock`
- frontend origin defaults to `http://localhost:5173`
- updater runs on a separate port, default `5174`

`backend/app/core/db.py` creates a SQLite engine on demand and ensures the data directory exists before opening the database.

### Router Groups

`backend/app/api/auth.py`

- bootstrap flow for the first owner
- login/logout and session cookie issuance
- current-user lookup
- password change
- owner-only user listing, creation, and role/disabled-state updates

`backend/app/api/config.py`

- returns the current app/site/runtime bundle
- persists app metadata and site config
- manages saved named site configs
- manages saved inputs and saved destinations

`backend/app/api/service.py`

- exposes sender service status
- exposes `start`, `stop`, and `restart`
- wraps helper failures in a structured `ServiceStatus` payload

`backend/app/api/diagnostics.py` and `backend/app/api/system.py`

- report diagnostic checks and basic host/runtime metadata

`backend/app/api/logs.py`

- returns the most recent sender logs via the helper

`backend/app/api/update.py`

- owner-only status and remote-check endpoints
- updater handoff launch endpoint
- install/job status endpoints

### Service Layer Boundaries

`backend/app/services/config_service.py`

- treats the config bundle as the source of truth for the sender command
- builds the `ffmpeg` command from site config and stream profile
- writes `app_config.json`, `site_config.json`, `runtime_config.json`, and `sender.env`
- persists saved site configs, inputs, and destinations in SQLite

`backend/app/services/service_control.py`

- converts diagnostics into preflight gating for start/restart
- reads sender state through the helper
- performs sender actions only after validating state transitions
- returns a single `ServiceStatus` contract the UI can render directly

`backend/app/services/host_control.py`

- is the backend-to-root boundary
- sends JSON requests over the Unix socket to the root-owned helper
- fails closed on missing socket, bad responses, timeouts, or helper errors

`backend/app/services/diagnostics.py`

- aggregates system metadata and diagnostic checks
- depends on `health_checks.py` for the actual check set

`backend/app/services/update_manager.py`

- checks the remote repo for newer commits
- stores update state and log lines under the backend data directory
- treats update status as a persisted job, not only an in-memory process
- explicitly documents that sender restarts are not expected during control-plane updates

`backend/app/services/update_handoff.py`

- creates and validates signed updater tokens
- isolates the owner-authenticated WebUI from the separate updater process/UI

### End-To-End Data Flow

Startup flow:

1. Backend process starts `app.main:app`
2. lifespan calls `init_db()`
3. SQLite tables are created if missing
4. routers begin serving under `/api`

Auth flow:

1. WebUI checks `/api/auth/bootstrap-status`
2. if no user exists, the first owner is created with `/api/auth/bootstrap-owner`
3. later logins use `/api/auth/login`
4. backend stores a session record and returns an HTTP-only session cookie
5. protected routes use dependency guards from `app/api/deps.py`

Config flow:

1. frontend loads `/api/config`
2. user edits site config or loads a saved config
3. backend validates via Pydantic schemas
4. `config_service.save_bundle()` regenerates runtime artifacts
5. the sender command in `sender.env` becomes the execution source for the `systemd` sender unit

Service control flow:

1. frontend requests `/api/service/status`
2. backend runs preflight checks plus helper-backed service inspection
3. allowed actions are derived from current service state and blocking failures
4. `start` or `restart` calls go through the helper socket to `systemctl`

Update flow:

1. owners check `/api/update/status` or `/api/update/check`
2. launch calls `/api/update/launch`
3. backend signs a short-lived handoff token for the separate updater UI
4. updater UI talks to the updater app and backend update endpoints
5. `update_manager` tracks state and logs while `ops/update-ubuntu.sh` performs the control-plane update

Diagnostics flow:

1. frontend polls diagnostics, logs, and system info separately
2. backend reports check metadata and blocking/warning distinctions
3. dashboard and diagnostics UI use that data to gate sender actions and show operator-facing health

## 4. Frontend Architecture And Screen Module Map

### Entry Point

`frontend/src/main.tsx`

- creates a single TanStack Query client
- mounts `App` under React strict mode

### App Composition

`frontend/src/app.tsx` is the real composition root.

- determines whether bootstrap or login should be shown
- fetches config, saved configs, saved endpoints, service status, diagnostics, logs, system info, users, update state, and update job state
- owns all mutations for auth, config save/load, service actions, user management, and updates
- gates admin and updater flows to owners

### Main UI Modules

`frontend/src/components/layout/app-shell.tsx`

- defines the main authenticated frame
- current top-level tabs are `control`, `config`, and `diagnostics`
- shows owner-only admin and update affordances in the header

`frontend/src/features/auth/auth-page.tsx`

- renders either initial owner bootstrap or standard login

`frontend/src/features/dashboard/dashboard.tsx`

- primary control tab
- shows active config summary, sender status, runtime preview, and start/stop/restart actions

`frontend/src/features/config/config-panel.tsx`

- most state-heavy UI module
- edits input, destination, transport profile, video options, and saved config entities
- saves via backend bundle regeneration, not client-side-only state

`frontend/src/features/diagnostics/diagnostics-panel.tsx`

- renders health summaries, categorized checks, system info, and logs

`frontend/src/features/admin/admin-modal.tsx`

- owner-only user and role management

`frontend/src/features/update/update-modal.tsx`

- owner-only control-plane update launch and progress view

`frontend/src/features/onboarding/onboarding-panel.tsx`

- exists in the repo as an onboarding-style guided flow
- not currently wired into `app.tsx`, so treat it as dormant or future-facing UI unless you see new imports introducing it

### API Contract

`frontend/src/lib/api.ts` is the frontend boundary with the backend.

- all fetches use `credentials: "include"`
- typed request/response contracts mirror the backend schemas closely
- the app expects grouped endpoints under `/api/auth`, `/api/config`, `/api/service`, `/api/logs`, `/api/diagnostics`, `/api/system`, and `/api/update`

This file is the fastest way to understand what the UI expects from the backend.

## 5. Runtime And Ops Model

The app is designed around Ubuntu plus `systemd`, even though development notes mention MacBook-friendly local work.

### Production Service Topology

`ops/justso-easysrt-helper.service`

- runs as `root`
- owns the Unix socket at `/run/justso-easysrt/helper.sock`
- is the only component allowed to execute privileged host actions

`ops/justso-easysrt-backend.service`

- runs as user/group `easysrt`
- loads `/etc/justso-easysrt/easysrt.env`
- starts `ops/run-backend.sh`

`ops/justso-easysrt-frontend.service`

- runs as user/group `easysrt`
- serves the built frontend bundle through `ops/run-frontend.sh`

`ops/easysrt-sender.service`

- runs the generated `FFMPEG_CMD` from `backend/data/sender.env`
- is the live sender process the control tab starts and stops

### Privileged Host Boundary

`ops/host-control-helper.py` is critical infrastructure.

- validates peer credentials on the Unix socket
- only allows `root` or the configured app group to connect
- supports helper actions for sender status, sender logs, sender start/stop/restart, and control-plane updates
- launches the updater in a detached process when requested

The backend never shells out to `systemctl` directly for sender control. It talks to the helper.

### Installer And Updater

`ops/install-ubuntu.sh`

- provisions packages, the `easysrt` user/group, repo checkout, backend venv, frontend build, helper/backend/frontend/update services, and sender unit
- prompts for frontend port, bind scope, station name, and support contact

`ops/update-ubuntu.sh`

- updates an existing install in place
- records progress into a JSON state file and a log file
- preserves backup and rollback metadata
- restarts the control plane and leaves the sender untouched by default

## 6. Local Run And Validation Commands

These are the repo-supported commands currently documented or directly implied by scripts and manifests.

### Local development

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
corepack enable
corepack prepare pnpm@latest --activate
pnpm install
pnpm dev:host
```

The frontend expects `/api` to proxy to `http://localhost:8000`.

### Backend test entrypoint

If the backend venv already exists:

```bash
cd backend
.venv/bin/pytest
```

If you are following the README-local-dev path instead:

```bash
cd backend
uv run pytest
```

### Production-style scripts

Backend service command:

```bash
ops/run-backend.sh
```

Frontend service command:

```bash
ops/run-frontend.sh
```

Updater service command:

```bash
ops/run-updater.sh
```

### Minimal validation checks

- backend health should return `{"ok": true}` from `/health`
- frontend should serve on the configured frontend port
- authenticated UI flows depend on cookies, so direct API calls from separate tools should preserve session state
- service control and sender logs require the local helper socket to exist and accept connections

## 7. Validation and limits

Backend regression tests live under `backend/tests/`; frontend API and import-workflow tests live alongside frontend code. Deployment regression tests are in `ops/test_deployment.py`. CI runs these suites, frontend lint/build, dependency audits, shell validation and secret scanning.

Isolated tests do not establish actual receiver lock, reboot recovery, service installation or partner failover. Validate those on Ubuntu before operational deployment. See [development instructions](development.md) and [readiness status](public-readiness-report.md).

## 8. Repository history

This repository starts with a cleaned initial source snapshot. Earlier internal development history is intentionally not included. Use the current code, tests and documentation as the implementation reference.

## 9. Immediate Next-Step Recommendations

If you are starting backend work:

1. Read `backend/app/main.py`
2. Read the relevant router in `backend/app/api/`
3. Read the backing service in `backend/app/services/`
4. Check `backend/tests/test_api.py` for the current behavioral contract

If you are starting frontend work:

1. Read `frontend/src/app.tsx`
2. Read `frontend/src/lib/api.ts`
3. Read the feature module you plan to change
4. Confirm whether the feature already has an owner-only or authenticated-state dependency in `app.tsx`

If you are starting ops or update work:

1. Read `ops/host-control-helper.py`
2. Read `ops/install-ubuntu.sh` and `ops/update-ubuntu.sh`
3. Read the relevant `systemd` unit files
4. Treat Ubuntu, `systemd`, and helper-socket assumptions as hard dependencies until proven otherwise

## Notes On Inference

Everything in this document is grounded in the checked-in README, manifests, scripts, and source files unless explicitly labeled otherwise. The only forward-looking inference called out here is that `frontend/src/features/onboarding/onboarding-panel.tsx` appears future-facing because it exists but is not currently mounted from `frontend/src/app.tsx`.
