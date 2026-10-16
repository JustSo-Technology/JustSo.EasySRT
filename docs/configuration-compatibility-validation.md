# Configuration compatibility candidate validation

Validated locally on 15 October 2026. This candidate combines the earlier public-alpha preparation, the existing local deployment/authentication/updater/configuration fixes, and the versioned configuration transfer system.

| Check | Result |
|---|---|
| Backend suite (`uv run --frozen pytest -q`) | 115 passed; one dependency deprecation warning |
| Configuration transfer coverage | 34 tests, including sanitized April-format fixtures, auth/CSRF, redaction, review, conflicts, rollback, stale/user-bound/expired/replayed previews, strict embedded JSON, request limits, writer serialization and concurrent health requests |
| Frontend tests | 11 passed, including five import workflow tests |
| Frontend lint and production/type build | Passed |
| Locked backend dependency audit | No known vulnerabilities/adverse statuses in 34 packages |
| Full frontend dependency audit | No known vulnerabilities, after patched brace-expansion/source-map-js overrides |
| Deployment regression tests | 8 passed, including local-fix/index restoration, failed fetch preservation, backup writer quiescence and rollback build/service error propagation |
| ShellCheck, actionlint and candidate release metadata | Passed |
| Staged source secret scan | Passed; no leaks found |

## PR review corrections

The review added regression cases that reproduced missing local-fix restoration during rollback, working-tree changes before a failed fetch, masked build failures in Bash conditional calls, blocking import operations on the ASGI event loop, permissive duplicate fields inside encoded legacy payloads, changed original latency labels, and misleading import failure messages after a successful commit followed by a list-refresh failure. These paths are corrected and covered by the suites above. The data archive now stops the backend writer and restores its prior running state, including when archiving fails; the sender is not stopped by that backup operation.

## Protected-backup rehearsal

Using the existing protected backup on the Mac, a temporary isolated application/database was bootstrapped with a new synthetic owner. The actual older extraction document was previewed, latency was explicitly chosen for the rehearsal, and all entries imported: five saved site presets plus a distinct current-state snapshot, one input, and three destinations. Export returned the same imported collection plus the new installation's own current snapshot. Active JSON/runtime/environment files remained byte-for-byte unchanged.

Customer URLs, credentials, account IDs and configuration documents are not committed to this repository. The regression fixture is sanitized. Rehearsal latency choices are not operational approval of those values for an operational installation.

## Limits and next acceptance

No VM installation was removed, updated or restarted for this implementation and review, and no release was published. The local ASGI/database rehearsal and isolated shell-function tests do not prove Ubuntu systemd/helper deployment, reboot recovery, partner failover, receiver lock or received programme audio. Those require the separate deployment rehearsal and receiver acceptance before changing the legacy installation. GitHub records the PR merge and hosted CI results.

The older raw controller's flat configuration remains explicitly unsupported because some transport settings cannot be represented; the importer rejects it without writes. Portable schemas do not migrate a restored database or authentication state. See [configuration transfer](configuration-transfer.md) for supported formats and operator steps.
