# Scoped integration API

EasySRT now has a versioned external API and an Owner-only API token panel under **Administration → API tokens**. This implements the EasySRT authentication/token portion of [issue #15](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/15), on top of #14's media observations and #16's explicit preset application. The standalone notification service, its event ingestion and delivery channels remain separate work; EasySRT tokens cannot authenticate to another service or installation.

## Create and manage tokens

Open EasySRT over HTTPS, sign in as an Owner, open user management and select **API tokens**. Name the token, identify the integration and owning account, select a preset, then customise individual actions and resources. Review access and expiry, confirm your current Owner password and copy the secret once. Incoming credentials are 256-bit random secrets stored as SHA-256 hashes. List/detail/audit responses cannot recover them. Neither passwords nor new bearer secrets enter persistent frontend storage or query caches. Access logs omit query strings, and query-based credential submissions are rejected.

Presets: Monitor, Troubleshooting, Stream operator, Preset librarian, Configuration engineer, Configuration backup, Configuration transfer and Custom. Additional preset sets can be added as a union; any action can then be removed. Presets are expanded into explicit grants when saved. Future preset or endpoint additions do not expand an existing token.

A grant binds a capability, resource kind, resource ID and (for Apply) target together:

```json
{"scope":"presets:apply","kind":"preset","resource_id":"a-preset-uuid","target":"default"}
```

The initial release has one instance and path `default`. Instance grants use the actual installation identity shown in the catalogue. `*` is an explicit collection selection meaning **all current and future resources of that kind**, never a scope wildcard. A specific preset grant cannot become permission over another preset, instance settings or a different path. Create operations require collection access; no capabilities are inherited merely because a token created an item. When the catalogue exceeds 1,000 objects, use the authenticated API and resource IDs to manage larger collections.

Role ceilings are checked again on use: Operator can read operational state/presets and control the selected sender; Engineer additionally manages configuration, presets, troubleshooting and secret access; Owner additionally reads audit/update state. Apply remains Engineer/Owner, matching #16. Role changes cannot invent token grants; disabling/deleting the owning identity denies its tokens. A role downgrade blocks grants above its ceiling immediately. Re-enabling/promoting the identity restores only previously explicit grants that remain unexpired/unrevoked. Changing ownership requires creating a replacement token in this release.

The list shows ownership, integration, prefix, effective grants, expiry, last authenticated use and rotation metadata. It supports filtering, resource edits, renewal, rotation, single/bulk revocation and audit history. Editing uses a revision precondition; stale changes conflict. Grant/expiry edits and rotation require a fresh Owner password. Revoked/expired token IDs cannot be revived.

Lifetime defaults to 90 days in the UI, with 7/30/90/365-day choices or a custom timestamp; the maximum is 365 days from the current time. Rotation retires the old credential immediately unless an overlap of at most 24 hours is explicitly chosen. A second rotation retires the oldest credential. Both valid rotation credentials share current grants, expiry and revocation. Revoke affects all credentials immediately for subsequent operations. A completed or already-dispatched external action cannot be undone by revocation.

If a creation/rotation response is lost, refresh metadata and rotate again. Secrets are deliberately not cached for response replay. The metadata response lists the most recent 20 credential records, with aggregate last use across all credentials; rotation events remain in the bounded audit history.

## Connect an integration

Use `Authorization: Bearer ...` over HTTPS. Never put a token in a URL, cookie, notification payload or log. Ordinary integration tokens cannot manage other tokens, mint browser sessions, access the root helper, obtain updater handoffs, or call legacy browser `/api/*` routes. Combining a session cookie and Authorization is rejected; an invalid token never falls back to a session. Bearer requests do not need CSRF tokens because they do not authenticate from cookies.

```bash
# Set EASYSRT_TOKEN in the integration's secret store/environment first.
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${EASYSRT_TOKEN}" \
  https://sender.example/api/v1/health
```

The API root and `GET /auth/token` reveal version/features and the calling token's effective grants. `GET /scopes`, `/scope-presets` and `/openapi.json` describe the supported contract. The [checked-in OpenAPI](api/openapi.json) contains bearer security and `x-required-scope`/`x-resource-kind` for each operation. Paths below are relative to `/api/v1`.

| Group | Endpoints | Capabilities |
| --- | --- | --- |
| Monitoring | `GET /service/status`, `/health`, `/paths`, `/paths/default/health`, `/metrics` | `service:read`, `health:read`, `metrics:read` |
| Recent transitions | `GET /health/events`, `/paths/default/events` | `health-events:read` |
| Sender control | `POST /service/start`, `/service/stop`, `/service/restart` | Separate `service:start`, `service:stop`, `service:restart` |
| Troubleshooting | `GET /diagnostics`, `/logs`; `POST /diagnostics/run` | Separate `diagnostics:read`, `logs:read`, `diagnostics:run` |
| Identity | `GET /system` | `system:read` |
| Selected/config metadata | `GET /config`, `PATCH /config/app`, `POST /config/validate` | `config:read`, `config-app:update`, `config:validate` |
| Presets | `GET/POST /presets`, `GET/PATCH/DELETE /presets/{id}`, `POST /presets/{id}/apply` | Separate `presets:read/create/update/delete/apply` |
| Saved sources | `GET/POST /inputs`, `GET/PATCH/DELETE /inputs/{id}` | Separate `inputs:read/create/update/delete` |
| Saved outputs | `GET/POST /destinations`, `GET/PATCH/DELETE /destinations/{id}` | Separate `destinations:read/create/update/delete` |
| Transfer | `GET /config/export`, `POST /config/import/preview`, `POST /config/import` | `config:export`, `config-import:preview`, `config:import`, plus relevant library grants |
| Redundancy visibility | `GET /redundancy/status`, `/redundancy/config-sync` | `redundancy:read`, `config-sync:read` |
| Updates | `GET /updates/status`, `POST /updates/check` | `updates:read`, `updates:check`; Owner ceiling |
| Audit | `GET /audit-events` | `audit:read`; Owner ceiling |

`read/create/update/delete` in the table denotes separate scope keys. Token management endpoints (`GET/POST /tokens`, `GET/PATCH /tokens/{id}`, `POST /tokens/{id}/rotate`, `POST /tokens/{id}/revoke`, `POST /tokens/revoke`, `GET /tokens/{id}/audit-events`) and `GET /token-catalogue` require an Owner browser session; mutations also require the existing X-CSRF-Token. Token delegation, update installation, arbitrary host actions, partner acknowledgements and direct site writes are intentionally unavailable to integration credentials. They cannot be enabled by submitting an unknown scope.

## Operational contracts

Health keeps process status separate from source/local-output progress and receiver verification. Missing, stale or foreign supervisor evidence is unknown; it cannot turn a running process into healthy media. Receiver receipt/playback remains unverified. Monitoring reads do not run reachability/preflight probes. `GET /diagnostics` gives passive evidence; `POST /diagnostics/run` is an independently scoped active probe. The transition endpoint exposes at most 20 records from the current supervisor state and explicitly reports `durable:false`; it is not persistent incident history.

Lists are filtered by resource permission before pagination. `offset` is non-negative and `limit` is 1–100. A token cannot distinguish an invisible item from a missing item. JSON errors include a stable `code`, safe `detail` and `request_id`, also returned as X-Request-ID. Invalid/expired/revoked credentials return 401 with WWW-Authenticate; insufficient scope returns 403, invisible resources 404, stale revision/idempotency conflicts 409, malformed payloads 422, missing command preconditions 428, and quotas 429 with Retry-After. Credential-storage outages fail closed. All v1 responses use Cache-Control: no-store; validation errors never echo input values.

Every sender command requires an Idempotency-Key (1–100 characters). Start/Restart additionally require `expected_selection_id` from a reviewed selection (`GET /service/status` supplies `selected_id` without needing configuration-read access). Stop accepts `{}` and never needs configuration Apply permission. The stored key is bound to the logical token, action, body and default sender. A successful replay returns the prior result without dispatching again and must still pass current authentication/permission checks. A pending/unknown result returns a conflict: inspect status and reconcile before sending a new command. Keys are retained for at least 24 hours and swept daily; do not rely on replay suppression indefinitely. Apply has its own token-bound request_id and #16 revision, selection and effective-runtime checks.

Save/Open and library changes never select a preset. Apply needs one grant authorising both its source preset and default target; Restart is separate. There is no direct site-update API that bypasses #16. `PATCH /config/app` changes station metadata for a later Apply and requires the `app_digest` returned by `/config`; it does not mutate an immutable selected/running snapshot. Preset mutations use `expected_revision`; input/destination edits and deletion use `expected_digest` from their detail response. `POST /config/validate` performs schema validation without writes or network probes.

Full source URLs are treated as sensitive, including opaque path segments as well as user-info, query and fragment values. Ordinary config/preset/input reads return a host-level projection and `url_has_secret:true`; `secrets:read` for that same resource permits the full URL. `secrets:update` permits replacing sensitive URLs without granting secret read. An omitted URL or unchanged redacted projection preserves the stored URL during an update. To deliberately replace the projection itself, supply the replacement URL and `clear_url_secret:true`; that requires secret-update permission. Raw runtime commands/arguments and stderr are never a side channel to secret access. No secrets are returned by successful mutation responses.

Export returns `{document, secrets_redacted}`. The document remains portable v1 and contains only authorised resources; exporting current configuration also requires config:read. Redacted exports omit URL credentials/paths, so a redacted backup is not a complete credential backup. When replacing an existing source/preset, a matching redacted projection preserves its existing URL. An import cannot change a sensitive URL without secret-update permission. Import previews need collection-wide read access to presets, inputs and destinations because conflict previews inspect those collections; individual create/update permissions are rechecked for affected objects inside the commit transaction. A preview is bound to its user, logical token, document, decisions and current library state. Another token, even for the same user, cannot commit it. Imports cannot activate a configuration or import token databases. The preview and commit remain separate capabilities.

## Deployment and retention

Publish through maintained HTTPS ingress, keep backend/helper ports private, and configure the public origin and secure cookies as described in [deployment security](deployment-security.md). Browser LAN HTTP opt-in does not waive HTTPS for these APIs or credential revelation. The backend trusts only the scheme supplied by its configured uvicorn proxy policy; the application never accepts an arbitrary forwarded-proto header itself.

The production frontend proxy now trusts forwarded scheme/client headers only from `EASYSRT_FRONTEND_TRUSTED_PROXY_CIDRS`, default `127.0.0.1/32,::1/128`. Configure the actual ingress CIDRs if the TLS proxy is on another machine. Untrusted direct HTTP clients cannot spoof HTTPS by supplying those headers. The existing forwarded Host allowlist remains in place, and Authorization is forwarded unchanged. Cross-origin browser bearer access remains disabled by default; server-side clients do not need CORS.

Default limits (all configurable with EASYSRT_ prefixes):

| Setting | Default |
| --- | --- |
| `API_REQUESTS_PER_MINUTE` | 120 per token |
| `API_COMMANDS_PER_MINUTE` | 6 disruptive commands per token |
| `API_INSTANCE_REQUESTS_PER_MINUTE` | 1,200 across integration tokens |
| `API_INSTANCE_COMMANDS_PER_MINUTE` | 60 across integration tokens |
| `API_AUDIT_RETENTION_DAYS` | 90 |
| `API_COMMAND_RETENTION_HOURS` | 24 minimum before daily sweep |

Quotas share SQLite state across local workers. Stop has its own command capacity and is excluded from exhausted monitoring/read quotas. Active diagnostics, logs, update checks and token administration have additional lower limits. A bounded per-process pre-authentication limiter restricts failed/random credential traffic without creating database rows for attacker-supplied identities. Request bodies are capped at 1 MiB. Last authenticated use may lag by up to 30 seconds; validity, revocation and role checks never use that batching window. Admin changes, relevant API mutations and denials are audited; routine successful reads use aggregate last-use metadata. Command dispatch intent and result are separate audit events so a timeout does not pretend the external action never happened.

The migration adds separate token, credential, instance-identity, quota/command and audit tables without changing existing presets. It is idempotent and records schema version 2. The SQLite file is private (0600). Token records are never part of portable exports or partner configuration replication. Restore the original instance only through a controlled credential recovery process: an old database backup can contain previously valid tokens, so block API ingress and revoke restored tokens before reopening access. For a new/cloned installation, initialise fresh data and import portable stream configuration instead of copying its credential database. Never run two installations with a copied issuer identity and bearer credential store.

## Verification and remaining scope

The implementation includes request-level credential/role/resource/lifecycle tests, a route-to-scope coverage check, UI permission/reveal/rotation/revocation tests, proxy trust tests and an isolated verified-TLS rehearsal. Run the latter with locked development dependencies:

```bash
uv run --project backend python ops/validate-scoped-api.py --report /tmp/easysrt-api-tls.json
```

It generates a disposable localhost certificate, trusts it only in that test client (verification remains enabled), starts a temporary production-configured backend with no host-control socket, checks issuance/read/scope denial/rotation/revocation/log secrecy, and removes its server and credentials. It does not install a trust root or touch a sender. See [validation results](validation/issue-15-scoped-api.md).

No standalone notification service, durable incident/delivery history, new notification channel, fleet service-account system or production deployment is included. Those #15 requirements remain open. Scope ownership and contracts for that separate service are recorded in the [design plan](plans/issue-15-scoped-api-authentication.md); it must issue its own differently prefixed credentials.
