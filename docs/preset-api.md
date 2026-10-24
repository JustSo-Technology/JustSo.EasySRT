# Preset workflow and API migration

Preset library operations and selecting a route are separate. Save and Open never write selected/run runtime artifacts or replicate an activation. Apply selects exactly a reviewed revision; it does not restart the sender. Start/Restart launch that selected snapshot. Automatic retries and supervisor crash restarts keep the pinned run snapshot.

All routes below require an authenticated browser session; mutations retain CSRF protection. API-token issuance and authentication remain separate issue-15 work. Full configuration responses are private and use `Cache-Control: no-store`.

## Presets

- `GET /api/config/saved` returns accessible IDs, names and integer revisions.
- `POST /api/config/saved` accepts `{name, site}` and returns `{saved_config}`. No live bundle is returned.
- `GET /api/config/saved/{id}` opens the current revision without writing. Optional `?expected_revision=N` rejects a race between Save and review instead of opening a different revision. It returns `saved_config`, a preview `bundle`, `app_digest`, `runtime_digest`, `runtime_version`, and `expected_selection_id`.
- `PUT /api/config/saved/{id}` accepts `{site, expected_revision}`. Rename (`PATCH`) accepts `{name, expected_revision}`. Delete uses `?expected_revision=N`. Each successful update/rename increments the revision.
- `POST /api/config/saved/{id}/apply` accepts the exact reviewed `expected_revision`, `expected_selection_id` (including explicit null before first selection), `app_digest`, `runtime_digest`, `runtime_version: 1`, `target: "default"`, and a fresh `request_id`. Repeat the same request identity/body to recover its original result after a lost response; it cannot repeat publication or replication. Reusing an identity for different content conflicts. A replay returns its original selection result; fetch `/api/config` for the current selection.

Apply copies the complete effective app/site/runtime into a new immutable snapshot. Editing, renaming, deleting or importing over its source preset cannot change that copy. The source name/revision remains available as provenance even after deletion. Runtime policy and app settings are covered by review digests; changes require a fresh review.

Missing revision/review preconditions return 428. Changed preset, selection or effective settings return 409. Review again explicitly; do not silently retry against a newer revision. Duplicate names also return 409 and require opening the intended existing preset before overwrite. Unknown target IDs return 404. Permission failures return 403.

## Selected and running state

`GET /api/config` returns the selected bundle with `selected` snapshot metadata and session capabilities. Before initial Apply, `selected` is null and the form receives defaults. `GET /api/service/status` includes `selected`, a separately verified `running_config`, and `pending_configuration`. Unknown/stale run evidence yields null running identity/pending comparison rather than inferring an on-air route from current disk files. Stopped senders have no current running configuration.

`POST /api/service/start` and `/restart` require `{expected_selection_id}`. A changed selection conflicts before dispatch. Stop requires no configuration precondition. Restart stops the old sender before pinning/starting its replacement; failures/timeouts retain truthful observed status and never imply media delivery. Stop remains available when selected settings fail preflight.

## Permissions

The central principal policy checks `presets:read/create/update/delete/apply`, independent `service:read/start/stop/restart`, app-settings writes and reusable-entry writes. Apply grants bind source preset and destination target together. Existing session roles map as follows: Owner/Engineer manage and Apply presets and control the service; Operator reads presets and controls the already selected service. Existing owner-only account administration remains owner-only. Future scoped credentials must use these checks; no bearer/token-management surface is added here.

`PUT /api/config/app` saves app metadata only; it cannot select configuration. Import remains library-only, increments local revisions on replacement, and uses the existing signed preview transaction checks. Portable v1 excludes local revisions, snapshot IDs, service state and launch artifacts.

## Legacy routes and clients

`POST /api/config/saved/{id}/load` and `PUT /api/config/site` return 410 with upgrade guidance. They cannot activate configuration. Reload cached browser clients after updating. The deprecated `overwrite:true` create shape requires `target_id` and `expected_revision`; a name alone never authorizes or identifies an overwrite. Prefer `PUT /saved/{id}`. `is_active` and `last_loaded_at` no longer describe the client contract; use explicit selected/run snapshot metadata.

## Persistence and recovery

The SQLite migration adds preset revision 1 and creates the snapshot/selection tables. Existing databases receive a private `.pre-preset-revisions.db` backup and available legacy configuration files receive private `.pre-preset-revisions` copies before schema changes. Migrations are idempotent. Backups and exports can contain stream credentials; preserve their existing restricted data-directory access.

SQLite's committed selected-state row is the durable publication journal. Apply stages and fsyncs a complete generation, updates snapshot/replication records in one transaction, switches one filesystem pointer, then commits. All application configuration readers and service dispatches share the target lock. After an interrupted publication, recovery uses the committed row to restore the pointer before reading or launching. An uncommitted generation cannot become the selected route; failed commits restore the previous selection. Referenced generations are retained; this release performs no automatic snapshot/history garbage collection.

The live sender uses `applied_sender.json`, copied from the reviewed selection by the local helper. Systemd/supervisor retries reuse it. Apply never changes that file. Privileged code validates a fixed local snapshot identity and copies artifacts as the service account; clients cannot supply a filesystem path or command.

Upgrade captures legacy disk selection without claiming it identifies the existing process. New Apply preserves legacy launch files. Until an explicit Start/Restart establishes a verified pin, the UI reports unknown running identity. Pre-upgrade disk files may already differ from the old process; exact legacy retry identity cannot be reconstructed retroactively. Application rollback restores the updater's consistent data backup with its matching release. The sender is not interrupted by a control-plane update; schedule the explicit activation separately.
