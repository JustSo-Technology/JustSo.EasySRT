# Configuration export and compatibility

Owners and engineers can use **Config → Import and export configurations** to move presets between installations. Operators cannot use these endpoints. Exported files may contain credentials in input URLs; store them privately. Previews redact URL user information, query strings and fragments, but exports retain the settings needed to reconnect.

Importing only creates or explicitly replaces saved presets, saved inputs and saved destinations. It does not load a preset, change the active station, write runtime files, synchronize a partner or start/restart a sender. After import, deliberately load the chosen preset through the existing configuration controls and verify it before starting the sender.

## Supported documents

- Portable JSON with `format: "justso.easysrt.configuration"` and integer `schema_version: 1`.
- The April 2026 unversioned EasySRT site object (`input`, `destination`, `profile`).
- The older EasySRT bundle (`app`, `site`, `runtime`); its runtime command is discarded.
- The read-only database extraction format `justso.easysrt.legacy-extraction`, `extraction_version: 1`, captured during the legacy installation backup. Its record IDs, attribution, active selection and runtime observations are excluded from the operational import. The current snapshot is offered as a separate inactive preset.

The distinct flat legacy controller format is recognized as unsupported. It has fields (including MPEG-TS IDs and buffer settings) that this EasySRT schema cannot represent. It is rejected rather than silently losing them. Unknown fields, incomplete profiles and unsupported future schema versions are also rejected. Fix the source document using a supported exporter or add a reviewed migration adapter; changing a version number alone is not a migration.

Schema versions describe the portable format independently of application versions. The current explicit adapters normalize known older formats to canonical settings. Future changes must add deterministic adapters and fixtures to `services/config_transfer.py`, or reject the version before any writes. Portable configuration compatibility does not migrate an application's database schema or restore users/sessions.

## Portable v1 shape

```json
{
  "format": "justso.easysrt.configuration",
  "schema_version": 1,
  "source": {"app_version": "0.1.0-alpha.1", "commit": "source-sha"},
  "exported_at": "2026-10-15T00:00:00+00:00",
  "station": {"station_name": "Example", "support_contact": "support@example.test"},
  "presets": [],
  "inputs": [],
  "destinations": [],
  "current": null
}
```

`presets` and optional `current` entries contain `name` and a complete `site` object. Inputs and destinations use the existing complete configuration models, including their names. The exporter includes all profile fields and explicit units. Station metadata is reference only. A document must contain 1–500 total entries to import, including the optional current snapshot; the request limit is 1 MiB. Exports reserve space for import decisions and the preview token. Generated runtime commands, executable content, accounts, sessions, host secrets, service definitions and installation paths are not part of portable v1.

## Preview and commit

1. Choose a supported JSON file. The first preview validates every entry and shows redacted settings, warnings and conflicts; it does not persist anything.
2. Select Add, Skip or Replace existing for each entry. Existing names default to Skip. Rename to add a distinct preset; replacement is explicit. An active preset cannot be replaced through import. Duplicate target names within one import block the entire operation.
3. For older SRT presets, enter a reviewed latency in milliseconds. Older code used the millisecond-labelled value directly as FFmpeg microseconds. No automatic interpretation is safe. In current EasySRT, a reviewed 80 ms renders `latency=80000` and 120 ms renders `latency=120000`; the appropriate receiver value still needs operational verification.
4. Click **Review import**. Editing a choice invalidates that review. Resolve every error before **Import saved entries** becomes available.
5. Import adds the reviewed records in one transaction, assigning new IDs and the importing user's attribution. A cancelled or failed import leaves records and runtime files unchanged. Source user/record IDs are never reused as foreign keys.

The signed preview token expires after 15 minutes and is bound to the authenticated user, exact document/decisions, normalized plan and saved/active configuration snapshot. The commit repeats validation while holding SQLite's writer lock, rejecting stale or changed previews. Normal local configuration writes acquire the same lock before writing runtime files. An imported change invalidates that preview for replay. Tokens contain hashes, not the source document or URL secrets; no server-side preview staging files are created.

Authenticated API endpoints (all under `/api/config/transfer`):

- `GET /export`: portable document; attachment disposition and `Cache-Control: no-store`.
- `POST /preview`: `{"document": {...}, "decisions": [...]}`.
- `POST /import`: the same document/decisions plus `preview_token`.

POST requests use the existing CSRF protection. A decision has `key` from the preview, `action` (`add`, `skip`, `replace`), optional destination `name`, and optional positive integer `latency_ms`. Parsing and validation errors never echo raw document values. Unknown JSON/decision fields and duplicate JSON keys are rejected.

## Legacy extraction and rehearsal

Use the protected `configuration-extraction.json` inside the verified backup; do not copy a production SQLite database into a new install merely to recover presets. The importer understands that extraction directly. No live VM access is needed for this PR: the sanitized regression fixture reproduces its five presets, one input, three destinations, audio/video profiles and distinct current-state snapshot.

Before deployment, rehearse fresh owner creation, import with reviewed latency, configuration loading and transmission to an isolated receiver on Ubuntu. Tests cover parsing/migrations, redaction, authorization, CSRF, token expiry/user binding/replay, conflicts, rollback and absence of runtime/replication side effects. Those checks do not establish receiver lock or authorize changing an existing installation.
