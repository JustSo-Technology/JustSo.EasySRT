# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JustSo.EasySRT is a web-based SRT streaming management tool for Ubuntu Server. It provides a React frontend and FastAPI backend that configure and control an ffmpeg-based SRT sender via systemd services. Deployed to `/opt/justso-easysrt` on target machines.

## Development Commands

### Backend (Python 3.12+ / FastAPI / uv)

```bash
cd backend
uv sync                    # Install/update dependencies
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  # Dev server
uv run pytest              # Run all tests
uv run pytest tests/test_api.py::test_name  # Run single test
```

### Frontend (React 19 / TypeScript / Vite / pnpm)

```bash
cd frontend
pnpm install               # Install dependencies
pnpm dev                   # Dev server (localhost:5173)
pnpm dev:host              # Dev server (0.0.0.0:5173, for VM access)
pnpm build                 # Production build (runs tsc -b first)
pnpm lint                  # ESLint
```

The Vite dev server proxies `/api` requests to `http://localhost:8000`.

## Architecture

### Backend (`backend/app/`)

Layered FastAPI application with SQLite (via SQLModel):

- **`api/`** — Route modules mounted in `main.py`: auth, config, service, logs, diagnostics, system
- **`api/deps.py`** — Dependency injection: session auth middleware, DB session provider
- **`services/`** — Business logic: `config_service.py` (config persistence + runtime generation), `service_control.py` (systemctl wrapper), `health_checks.py`, `security.py` (password hashing, session tokens)
- **`models/`** — SQLModel ORM models (User, SessionRecord, SiteConfig)
- **`schemas/`** — Pydantic request/response schemas
- **`core/settings.py`** — Pydantic Settings with env/secrets support; `core/db.py` — SQLite init

Auth is session-cookie-based with a bootstrap flow (first user creation).

Config pipeline: user edits → `site_config.json` → `config_service.py` generates `runtime_config.json` + `sender.env` → consumed by ffmpeg sender service.

### Frontend (`frontend/src/`)

- **`app.tsx`** — Root component: TanStack Query provider, auth state, tab routing
- **`features/`** — Feature modules: auth, dashboard, config, diagnostics, onboarding, admin
- **`components/ui/`** — Reusable UI primitives (button, card, input)
- **`lib/api.ts`** — Typed fetch wrapper for all backend endpoints
- **`@` path alias** maps to `./src`

Styling: Tailwind CSS 4.1 with utility classes. Icons: lucide-react.

### Ops (`ops/`)

- `install-ubuntu.sh` — Production installer (creates `easysrt` user, installs to `/opt/justso-easysrt`, configures systemd)
- systemd units: `justso-easysrt-backend.service`, `justso-easysrt-frontend.service`, `easysrt-sender.service`
- `serve-frontend.py` — Production static file server for the built frontend

### Companion Repo

Planning docs and specs live in the sibling `JustSo.EasySRT_Local/` directory (not version-controlled with this repo). Key files: `EasySRT-Codex-Handover.md`, `JS-EasySRT-V1-Technical-Architecture.md`.
