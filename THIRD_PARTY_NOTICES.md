# Third-party software

EasySRT installs or interoperates with independent open-source projects,
including FFmpeg, FastAPI, SQLModel, Uvicorn, React, Vite, Tailwind CSS, and
TanStack Query. Those projects retain their own licences and copyrights.

FFmpeg is invoked as an external executable and is not vendored here. The
licence applying to an FFmpeg build depends on its configuration; see
https://ffmpeg.org/legal.html.

Exact dependency versions are in `backend/uv.lock` and
`frontend/pnpm-lock.yaml`. Distributors must preserve applicable third-party
notices and satisfy the licences of the artifacts they distribute.
