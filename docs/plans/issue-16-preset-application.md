# Preset editing and explicit application — implementation plan

Date: 24 October 2026
Issue: [#16 — Separate preset editing and saving from applying the active configuration](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/16)
Baseline: public `main`, `dcdfba48e33a5e23624b7474a632d7b264d6d65c`; verified against the remote on 24 October 2026. The inspected `JustSo.EasySRT-Clean` checkout matches that commit. Its existing issue-14 plan is separate, unimplemented work.

Status: implemented on `justsojustin/preset-application`, building on issue #14 commit `0f2930e`. The original planning baseline below is retained for context. See [implementation validation](../validation/issue-16-presets.md) for the final design, test evidence and release limits.

## Outcome and scope

An engineer can prepare tomorrow's preset while today's sender continues using its existing configuration, including after an automatic retry. Saving, opening, renaming, deleting and importing presets are library operations. Only **Apply** selects a configuration for a subsequent deliberate **Start/Restart**. Apply itself never restarts the sender.

Implement this for the existing single sender, with an internal target identity of the local instance and path `default`. Do not introduce multi-path streaming, a recovery supervisor, notifications or token-management UI. Provide the capability/resource authorization boundary that [#15](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/15) will use, and the immutable runtime contract needed by [#14](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/14).

Recommended initial UX: separate Save, Open for editing, Apply, and Start/Restart actions. Omit a combined Apply and Restart action in this release. Unsaved editor changes must be saved and reviewed before Apply.

## Findings from the current code

| Area | Current behavior | Required change |
| --- | --- | --- |
| `backend/app/services/config_service.py` | `save_named_site_config()` and `load_saved_site_config()` call `save_bundle()` and set `active_saved_config_id` | Split library persistence, preview and explicit selection |
| `backend/app/api/config.py` | Save and load record replicated activation; direct `PUT /site` also publishes runtime; `PUT /app` regenerates the bundle | Remove implicit activation and close alternate write routes |
| `backend/app/models/site_config.py` | Mutable preset payload and a foreign key identify what is called active; no revision field | Add revisioned presets and independent immutable selection/run snapshots |
| `backend/app/api/deps.py` | Most config/service routes require any signed-in user; `config_write_session()` uses SQLite `BEGIN IMMEDIATE` | Introduce granular authorization and preserve transaction ownership |
| `config_service.py`, `replicated_config.py` | Sequential per-file replacements and several internal commits | Publish one complete generation and coordinate it with database/history state |
| `backend/app/services/service_control.py` | Start/Restart use current disk preflight and call the helper without a configuration/run identity | Start exactly the selected snapshot and report the actual run |
| `ops/easysrt-sender.service` | `Restart=always`; each launch reads mutable `sender.env` | Automatic launches must reuse a pinned run manifest |
| `backend/app/services/config_transfer.py` | Import is save-only; replaces records directly and blocks replacement of the active preset | Make import revision-aware without changing selected/running snapshots |
| `frontend/src/app.tsx`, config panel, dashboard | Save/load invalidate live config; editor resets from query data; dashboard uses selected data as the live route | Separate editor, preset, selected and running state |
| `backend/app/core/db.py` | `create_all()` only | Add a real, idempotent migration for existing installations |

## 1. Define identities, revisions and lifecycle

Use distinct identities rather than extending the ambiguous `is_active` flag:

| State | Stored contents | Changes when |
| --- | --- | --- |
| Editor draft | Local form and base preset ID/revision | Operator edits or opens a preset |
| Saved preset | Stable ID, name, monotonic revision, validated site payload, attribution | Explicit create/update/rename/import; delete removes library availability |
| Selected configuration | Immutable snapshot ID, complete effective app/site/runtime payload, source preset ID/revision/name, target, digest, actor/time | Explicit successful Apply |
| Run configuration | Pinned snapshot ID and service invocation identity, startup outcome, observed process status | Deliberate Start/Restart and verified sender lifecycle observations |

Give each preset an initial revision of 1. Content changes and renames increment it. Updates, renames, deletes and overwrites require the revision the caller read; overwrite-by-name must resolve to an explicit authorized target ID and expected revision. Apply requires an exact preset revision and the expected current selection ID. Missing preconditions return `428`; stale preconditions return `409` with safe conflict metadata. Never automatically resubmit a stale Apply against the latest revision.

An immutable selection copies values, including source name and effective app settings; it is not a foreign key lookup of the latest preset. Keep its provenance when the source is renamed/deleted, without a cascading delete. Updating a library revision does not mutate the selected or running snapshot. Retain snapshots referenced by selected state, an active/retrying run, or required history; collect unreferenced artifacts only under a defined retention policy.

Expose selected and running identities, source revisions, provenance and an explicit state such as stopped/starting/running/failed/unknown. Compare snapshot identities for pending application; show editor unsaved changes and a newer library revision separately. If selected and running identities differ, show “Selected for next Start/Restart.” A known stopped service has no current on-air configuration; last-run information is historical. Unknown running identity must remain unknown rather than be inferred from disk.

Review must cover the effective configuration. Return the effective app-settings revision/digest and runtime-format version with the preset preview, and require these review preconditions on Apply. If they changed, require another review. Station/support settings currently live separately: keep those edits behind app-settings authorization, and prevent `PUT /app` from silently regenerating or replacing selected/run artifacts. A later Apply captures their current reviewed values.

## 2. Separate the service layer and API

Refactor `config_service.py` into library operations, pure runtime generation and one explicit selection/publication operation. Library helpers must not call `save_bundle()`, change selected state, invoke systemd or record replicated selection changes. Remove internal commits from helpers participating in a larger transaction; let the operation coordinator commit once.

Proposed API contract, retaining the existing `/api/config/saved` collection:

| Endpoint | Contract |
| --- | --- |
| `GET /api/config/saved` | List accessible preset metadata and current revisions |
| `GET /api/config/saved/{id}` | Read/open a preset and reviewed runtime preview; no writes or activation |
| `POST /api/config/saved` | Create a preset only; return preset identity/revision, without a misleading live bundle |
| `PUT /api/config/saved/{id}` | Save reviewed changes with expected revision; return the new revision |
| `PATCH /api/config/saved/{id}` | Rename with expected revision |
| `DELETE /api/config/saved/{id}` | Delete with expected revision; retain selection/run snapshots |
| `POST /api/config/saved/{id}/apply` | Require preset revision, target, expected selection and effective-review preconditions; validate and publish a selection; return selection/status |
| `GET /api/config` | Return authoritative selected configuration and identity; no generated persistence side effects |
| `GET /api/service/status` | Return run identity/status, selected identity, pending state and authorized actions |
| `POST /api/service/start` or `/restart` | Require expected selection identity; pin and launch that exact snapshot |

Compatibility strategy for the same release as the UI update:

- Change existing `POST /saved` to save-only immediately. During a documented deprecation window, accept `overwrite=true` only with explicit target ID and expected revision and route it through revision-aware update authorization. An old request missing these preconditions must fail without writes.
- Retire `POST /saved/{id}/load` with `410 Gone` and actionable guidance to Open or Apply. Do not redirect a load call into Apply.
- Retire `PUT /config/site` with `410 Gone`; replace its uses with create/update then Apply. Do not keep a second raw-payload activation path.
- Remove `is_active` and `last_loaded_at` from the new client contract; preserve old database fields only for migration/history. Document the API behavior/response changes and show a reload message for stale cached clients.
- Preserve session CSRF protection. Preview responses containing full configuration are private and `Cache-Control: no-store`; audit messages/errors must not disclose credential-bearing URLs.

Apply validates the exact saved payload and builds the complete runtime before publication. Reachability preflight remains a separate, bounded check and Start/Restart rechecks the pinned selected snapshot. Stop remains available when selected configuration is invalid or unreachable. Repeating Apply with the same request identity is idempotent and does not create duplicate replication/history entries.

## 3. Enforce capabilities at the operation boundary

Add an authenticated principal abstraction with capability checks and optional resource restrictions; map existing session users to it now. Future #15 tokens must enter through the same checks, with their effective grants restricted to token scopes and resource bounds. Token issuance, storage, rotation and management remain #15 work.

Capabilities: `presets:read`, `presets:create`, `presets:update`, `presets:delete`, `presets:apply`, plus separate `service:read`, `service:start`, `service:stop`, `service:restart` and an app-settings write capability.

Recommended initial role mapping: owners/engineers can manage and apply presets and control the sender; operators can read presets/status and Start/Stop/Restart an already selected configuration. Only owners manage account permissions. Treat this as an explicit release behavior change because most existing config endpoints currently accept all authenticated roles. Review this mapping before implementation if operators are intended to edit presets.

Apply checks both source preset access and permission to select configuration on the resolved local target. Reject unsupported target identifiers rather than falling back to `default`. A preset-scoped edit grant cannot acquire Apply through overwrite-by-name, imports, direct site/app writes or legacy load. Start/Restart checks the target's service capability independently; Apply does not confer it. Server-side `allowed_actions` and frontend controls use the same effective grants; disabled buttons alone do not enforce access.

Import requires create/update permission on every affected preset/resource and commits all or nothing. Export/preview require suitable read permissions and must not expose inaccessible entries. Reusable input/destination writes receive equivalent library authorization and remain unable to select configuration.

Keep the helper's existing local peer-credential boundary. API authorization happens before helper dispatch; caller-supplied display roles are not proof of authority. Pass a resolved snapshot/run identity for dispatch, not an arbitrary client filesystem path or command.

## 4. Make selection publication and service actions coherent

The existing `_atomic_write()` protects one file only. It cannot make app/site/runtime/environment writes atomic together with SQLite and replication history. Use immutable generation directories containing the complete validated snapshot and launch manifest, plus one atomically replaced selected-generation pointer. All readers resolve one generation once per operation; do not independently resolve a pointer for each file.

Use an interprocess lock per sender target to serialize Apply, explicit Start/Stop/Restart and publication recovery. Establish one lock order: target lock, then SQLite write transaction. Preset-only edits/imports use SQLite's writer transaction without touching generation pointers. Apply rechecks preset and selection preconditions under the transaction, so a racing edit either precedes Apply and produces a conflict, or follows it and leaves the copied selection unchanged. Do not rely on a Python thread lock or the current helper's process shape.

Publication protocol:

1. Authorize, acquire the target lock, reconcile unfinished operations, check revisions, and validate/build the reviewed snapshot.
2. Write a complete new generation privately on the same filesystem. Flush files and directory metadata before publication. Record a durable prepared operation containing previous/new generation IDs; never expose this as a successful selection.
3. Atomically switch the selected pointer. Finalize the selected database record, replicated configuration version and audit result together. Acknowledge success only after this finalization.
4. On failure, preserve/restore the previous usable selected pointer and reconcile the prepared operation. After a crash between steps, reconcile before serving configuration reads or executing service commands. Either finalize the verified complete generation or restore the prior generation; never launch from partial files or return conflicting file/database state as successful.

Record the exact journal states, recovery rules and fault-injection checkpoints in the implementation. SQLite and filesystem renames are not one transaction; test that boundary explicitly. Failure after an irreversible service action must be reported as a service-action outcome, not disguised as an Apply rollback. Bound helper subprocess waits and reconcile systemd invocation state after timeouts; the command may have succeeded after the caller stopped waiting.

Replication history advances only for successful explicit selection, with accurate actor and source revision, not library Save/Open/import. Initialize replication from the authoritative selected generation. Refactor `replicated_config.py` helpers that currently commit internally so finalization owns the transaction. This issue changes existing replication metadata, not partner transport/takeover implementation.

## 5. Pin what the sender actually launches

Extend the helper/service launch contract and `ServiceStatus` together:

- Explicit Start/Restart verifies the expected selection, runs preflight against that immutable generation, and pins it as a new run intent. A racing Apply cannot change the run after this point.
- Restart stops and reaps the old invocation before launching the new one. Apply never calls this operation. If stop fails, do not launch a duplicate sender. If launch fails, retain the selected snapshot, record the failure, and do not report the new configuration as running.
- Add a minimal launcher/run-manifest boundary to `ops/easysrt-sender.service`. Automatic systemd launches read the pinned run manifest, never the selected pointer or mutable library. Use generated argument arrays rather than adding another shell-command evaluation path.
- Associate launch acknowledgment/status with systemd invocation ID and the snapshot ID. Distinguish launch intent from observed running process identity; `systemctl` success alone does not prove media or receiver playback. Refresh status through bounded polling and reject stale run observations.
- Stop cancels the run intent as well as stopping systemd. A backend/helper restart does not select or launch a different configuration. Define boot behavior explicitly: a previously enabled sender resumes its pinned run; a new selection still awaits explicit Start/Restart. A fresh installation without a run pin requires initial deliberate activation.
- Keep selected artifacts and run artifacts separate, including any compatibility `sender.env`. Preflight and diagnostics must compare artifacts from the same snapshot rather than recomputing from an editable preset.

This is the minimum lifecycle work required by #16, even before #14's supervisor exists. Reconcile the terminology in `issue-14-stream-recovery.md`: its candidate manifest corresponds to **selected**, and its applied manifest corresponds to the **run snapshot**. Recovery reuses that run snapshot; it never implicitly adopts later selected or saved changes. Reuse this contract when #14 lands rather than creating a second set of runtime identities/locks.

## 6. Keep the UI editor separate from selected and running state

Update `frontend/src/lib/api.ts`, `app.tsx`, `features/config/config-panel.tsx`, and `features/dashboard/dashboard.tsx`:

- Save/overwrite updates preset metadata/revision only, preserving the draft and current run display. Success copy: “Preset saved. Apply it to select it for the next Start/Restart.”
- Open fetches the preset into the editor with its base revision. Replace “Load Saved Config” with “Open preset.” Opening has no selected-state or runtime side effects.
- Show unsaved changes. Confirm replacing a dirty draft when opening another preset. Avoid overwriting it when background queries refresh selected configuration or the preset list.
- Apply is available for a saved, reviewed revision. Show its route/profile and target, explain “Does not restart the sender,” and refresh selected/status/diagnostics after success. When the draft differs from its saved revision, require Save and review before Apply.
- A conflict keeps the draft intact and offers explicit reload/review. Name collision and stale revision are distinct errors; do not treat every `409` as an instruction to overwrite.
- Show “Selected for next Start/Restart” and “Running configuration” separately, using immutable snapshot data. Dashboard input/destination/profile for the live sender come from run data, not the mutable selected bundle. Show legacy/unknown identity honestly.
- Before Restart, show the exact selected revision and the stream interruption. Include its expected selection ID in the request; if it changes, require another review. Start uses the same identity check.
- Show selected/run provenance when the source preset has been renamed/deleted; do not imply the stream stopped or changed. Poll status so direct service changes and pending state are visible without reloading.

## 7. Migrate existing data, imports and deployments safely

Add a versioned, idempotent SQLite migration rather than relying on `create_all()` to modify existing tables. Back up the database and configuration files, assign preset revision 1, create snapshot/state tables, and migrate the existing on-disk selection as a distinct legacy selected snapshot. Preserve attribution and history. Use `active_saved_config_id` only as provenance when its payload matches the migrated snapshot; do not assert that its current mutable payload was selected.

An already-running legacy process cannot be identified from current files reliably. Mark its run identity unknown until a deliberate Start/Restart establishes the new launch contract. Upgrading must not restart that sender to discover its configuration. Capture and preserve legacy launch artifacts separately; new Apply must not rewrite anything a legacy automatic launch consumes. Do not claim exact old-route retry preservation if the pre-upgrade files were already different from the running process. Document this legacy limitation and the explicit restart needed to establish a verifiable run pin; rehearse the transition before rollout.

Install the launcher, generation paths/permissions and unit changes together. Handle a sender crash during upgrade without falling back to the newly selected snapshot. Preserve any old pinned fallback privately and label it unverified, or report migration activation required when no safe launch artifact exists. Verify boot, auto-restart and rollback behavior on Ubuntu before shipping. Retain the updater's current control-plane-only restart policy.

Make `config_transfer.py` use the same preset revision/write helpers. Preserve signed-preview conflict checks and save-only behavior. Once immutable snapshots are in place, replacing a selected preset through import may create a new library revision without changing selected/run snapshots; update the existing prohibition and regression tests together. Keep portable v1 unchanged if its payload shape is unchanged: local revision IDs, run state and launch manifests are not portable configuration. Imported records receive local revisions and never trust source revision identities.

Update `docs/configuration.md`, `docs/configuration-transfer.md`, API migration/release notes, and installation first-run instructions. Track the homepage's copied documentation in the parent workspace for an intentional follow-up refresh when the application release is ready; avoid prematurely advertising unreleased behavior.

## 8. Validation and delivery sequence

Add backend tests around state transitions and invariants, not just response labels:

| Scenario | Required evidence |
| --- | --- |
| Create/overwrite/rename/open/delete/import | Selected and pinned artifacts, pointers, replication version and service calls remain unchanged |
| Edit/delete source of selected or running snapshot | Snapshot content/provenance remains available; no shared-reference mutation |
| Apply exact reviewed revision | New complete selected snapshot and one replication event; no sender restart |
| Stale Save/Apply/delete or changed effective settings/selection | Conflict before publication, draft retained in UI, no partial writes |
| Edit-only principal versus every current/legacy route | Cannot select/apply; imports and name overwrites cannot bypass scope |
| Apply-only principal | Can apply to authorized source/target, cannot Start/Restart without separate grant |
| Wrong source resource or wrong target | Denied without falling back to local default |
| Concurrent Save/Apply/Start/Restart/import across processes | Deterministic revision outcomes; each run launches exactly its pinned selection |
| Validation/write/fsync/rename/DB commit failure | Previous usable selection preserved; no false replication success |
| Process crash at each publication checkpoint | Reconciliation restores one coherent selected generation before commands/reads |
| Helper timeout or failed stop/start | Reconciled invocation status; no false running identity or duplicate sender |
| Service crash after Apply while old run is live | Automatic launch uses the old pinned runtime; deliberate Restart uses selection |
| Upgrade with a live legacy sender | No interruption, unknown run identity shown, no automatic adoption of new selection |

Replace the existing tests that assert Save/Load activation in `backend/tests/test_api.py`. Extend `test_config_transfer.py`, helper tests and ops deployment/installer tests. Add focused React tests for draft preservation, save-only behavior, preview, conflict handling, Apply controls/permissions and dashboard selected/running labels. Keep URL credentials out of rendered summaries and test logs.

Use an isolated Ubuntu sender/receiver rehearsal to prove A keeps transmitting after saving/opening/applying B; force a sender exit to verify its automatic restart remains on A; then explicitly Restart and verify B's destination/profile and run identity. Recheck editing/deleting B and importing an overwrite. Fake helper tests alone cannot establish which configuration a real systemd launch consumed.

Implementation sequence:

1. **State and authorization foundation:** migrations, revision checks, immutable snapshot models, principal/capability policy, and regression fixtures.
2. **Backend publication and lifecycle:** save-only library operations, explicit Apply, generation journal/locks, replication finalization, helper/launcher run pins and truthful status. Close legacy/direct activation routes together.
3. **Client and compatibility:** API types, separate draft/open/save/apply controls, selected/run dashboard, permissions, imports and documentation. Ship the backend and client behavior changes in the same release.
4. **Release proof:** concurrency/crash matrix, real Ubuntu launch/retry rehearsal, fresh install, upgrade and rollback, then refresh public documentation for the released behavior.

Required checks after implementation: backend `uv run pytest`; frontend `pnpm test`, `pnpm lint`, `pnpm build`; ops installer/deployment/helper regression suites, plus the Ubuntu lifecycle rehearsal. Completion requires all issue acceptance criteria, including the permission and publication-failure cases, not merely removing `save_bundle()` from Save.
