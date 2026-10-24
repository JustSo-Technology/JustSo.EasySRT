# Preset selection validation — issue #16

Date: 24 October 2026 (Australia/Sydney). Source: [issue #16](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/16). Implementation builds on issue #14's pinned recovery runtime (`0f2930e`).

## Result

Save, overwrite, rename, Open, delete and import are library operations. Apply selects an immutable reviewed revision, checks source/target permission and concurrency preconditions, and never dispatches a sender restart. Start/Restart require the exact selected identity and pin its runtime. The UI preserves drafts, reviews Apply and Restart separately, and shows selected/run provenance independently.

The [API and migration contract](../preset-api.md) describes endpoint deprecations, role mapping, conflict responses, generation storage and legacy activation. The existing portable v1 format is unchanged. Snapshot/history artifacts are retained without automatic garbage collection in this release.

## Real Ubuntu lifecycle evidence

[Ten passing scenarios](issue-16-preset-ubuntu24.json) ran on the existing disposable Ubuntu 24.04.4 x86-64 rehearsal VM with Ubuntu FFmpeg 6.1.1/libsrt. The harness uses loopback HTTP audio input, SRT output, independent decoded-audio receivers, uniquely named systemd units and a root-owned temporary helper/supervisor installation under `/run`.

1. Start the upgraded control plane while a legacy sender is live; Apply preserves its PID and pinned bytes, and its unverifiable run identity remains unknown.
2. Save and Open another preset without changing selection or the live sender.
3. Apply that preset: selection becomes pending without a sender restart.
4. Stop during retry despite failed preflight.
5. Kill the supervisor: systemd removes the old process group and restarts the pinned A runtime while B remains selected.
6. Explicit Restart launches the selected B snapshot and decodes audio at B's receiver (317,952 PCM bytes at the assertion).
7. Delete the source of a selected snapshot without mutating that snapshot or the live sender.
8. Restart the helper without interrupting the sender.
9. Direct systemd Stop stays stopped through control-plane migration/helper restart.
10. Stop during startup prevents later relaunch.

Temporary units/processes were cleaned up. The rehearsal VM was shut down and its original network bridge restored. Existing production sender services were not installed, restarted or deployed by this work.

Reproduce on a disposable Ubuntu 24.04 host with FFmpeg, passwordless sudo and the locked backend **development** dependencies (the harness uses FastAPI TestClient):

```bash
uv sync --project backend --locked
uv run --project backend python ops/validate-service-recovery.py --report /tmp/easysrt-presets.json
```

The existing CI media-recovery job already runs this harness, so it now includes the preset/lifecycle cases alongside #14's media fault matrix. Other source protocols and production receivers still need deployment-specific media acceptance.

## Automated regression coverage

Local checks: 163 backend tests, 21 frontend tests and 24 ops tests passed. Frontend lint/build/type checks, Python compilation, ShellCheck and diff checks passed.

Backend tests cover library-only artifacts/history, selected-source editing/deletion, revision and effective-review conflicts, exact selection checks, source/target grants, edit-only versus Apply-only principals, import revisions, idempotent Apply, invalid legacy data, Stop during failed artifact repair, simultaneous Apply and Start/Apply/Save races, and migration/private-backup idempotence.

Publication tests inject partial file writes, fsync failures, pointer-switch failures and failed database commits. A separate Python process is killed immediately after switching the filesystem pointer but before SQLite commit. On the next read, the pointer is restored from the committed selected-state journal and the previous configuration remains usable. This tests actual process death and SQLite rollback rather than only exception handling.

Frontend tests cover read-only Open, Save without Apply, revision-bearing Save, independent Apply review, dirty-draft preservation through refreshes, conflict preservation without retries, selected/run labels and separate Restart review. Ops tests retain installer/update/rollback packaging checks. Lint/build/type checks, Python compilation, ShellCheck and diff checks complete the local validation.

## Release limits

This is an implementation and isolated lifecycle acceptance, not a production rollout or a new certification of every installer/update rollback path. Existing ops rollback regressions pass; a full install/update/rollback deployment rehearsal for a release remains a release task. Legacy files may already differ from an old running process; the upgrade preserves them but cannot reconstruct historical on-air configuration. A deliberate Start/Restart establishes the verified new run pin. Scoped token issuance and management remain issue #15.
