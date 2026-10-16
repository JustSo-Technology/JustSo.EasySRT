# Build EasySRT from source

[Documentation home](../README.md) · [Ubuntu production installation](installation.md) · [Platform support](platform-support.md)

## Prerequisites

- Git.
- Python 3.12+ and uv. The production installer pins its uv tool version; local development should use a uv version that supports the committed lock.
- Node.js 22 LTS (22.13+) and pnpm 10.17.1, as declared in `frontend/package.json`. Node 20 and 21 are unsupported. CI validates the minimum and current Node 22 versions; newer majors accepted by the installer are not fully validated.
- FFmpeg with SRT and the required encoders for media checks. Full service and streaming validation requires the Ubuntu runtime.

## Clone and install locked dependencies

```bash
git clone https://github.com/JustSo-Technology/JustSo.EasySRT.git
cd JustSo.EasySRT
cd backend
uv sync --locked
cd ../frontend
corepack enable
corepack prepare pnpm@10.17.1 --activate
pnpm install --frozen-lockfile
```

If your Node installation does not include Corepack, install the pinned pnpm version using your Node package tooling before running the final command. To inspect a release, check out its existing tag before installing dependencies.

## Run locally

Terminal 1, from `backend/`:

```bash
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, from `frontend/`:

```bash
pnpm dev --host 127.0.0.1
```

Open the frontend URL printed by Vite (normally `http://localhost:5173`). Vite proxies `/api` to port 8000. Create an owner using the first-run flow. Keep development services local; production requires explicit security settings.

Local UI/API development on macOS is separate from production streaming. Missing systemd/helper services or media dependencies will limit status, diagnostics, sender control and updates. Development commands do not install those services. Do not treat a successful UI build as proof of native macOS/Windows compatibility.

## Validate and build

From `backend/`:

```bash
uv run pytest -q
uv audit --frozen
```

From `frontend/`:

```bash
pnpm lint
pnpm test
pnpm build
pnpm audit
```

The production frontend is generated in `frontend/dist/`. The backend runs from its Python environment; there is no native desktop executable produced by this build. Tests isolate data in temporary directories; do not point development settings at production data.

For production services, paths, environment files, least-privilege helper and deployment from the lock, follow [Ubuntu source installation](installation.md#manual-production-build-from-source-advanced). The guided Ubuntu installer also builds from source. It fetches the configured remote ref rather than deploying your uncommitted working tree.
