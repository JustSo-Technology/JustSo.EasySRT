# Contributing to JustSo.EasySRT

Open an issue before beginning large changes so maintainers and contributors
can align on scope.

Run `uv sync --locked && uv run pytest` in `backend/`. Run
`pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm test`, and `pnpm build`
in `frontend/`. From the repository root, validate operation helpers with
`bash -n ops/*.sh`, `shellcheck ops/*.sh`, and
`python3 -m py_compile ops/*.py`.

Keep pull requests focused, add tests for changed behaviour, update relevant
documentation, and never commit credentials or production data.

Contributions require acceptance of [CLA.md](CLA.md). By participating, you
also agree to [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md).
