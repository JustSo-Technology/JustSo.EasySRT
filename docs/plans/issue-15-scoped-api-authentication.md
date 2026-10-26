# Scoped API authentication and token management — implementation plan

Date: 24 October 2026
Source: [issue #15](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/15) and its linked [health/recovery issue #14](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/14).
Dependency: [issue #16 — separate preset editing from applying configuration](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/16).
Baseline: public `main`, `dcdfba48e33a5e23624b7474a632d7b264d6d65c`. The local checkout has an additional password-confirmation commit; inspected backend code matches public main. Issue #15 had no comments when reviewed.

Status: design record written on 24 October. The EasySRT scoped API and token UI were implemented on 25 October from merged PR #18; see [the implementation guide](../scoped-api.md) for shipped endpoints, adjusted role rules and remaining standalone-service scope. Endpoint names below retain the original proposed contract.

## Outcome

Let an operator create a named token for one integration, choose a useful permission preset, then customise every action and resource. A monitoring token must never acquire stream-control, configuration, secret-reading or administrative powers simply because those routes share a router or user account.

Deliver EasySRT's own API/token surface first. The standalone notification service described in #15 gets its own issuer, credential store, API origin and lifecycle. An EasySRT token is valid only for the issuing EasySRT instance; a notification token is valid only for the issuing notification service. Share the scope vocabulary conventions, UI patterns and conformance tests, without sharing bearer secrets or requiring either service to run the other.

An external monitor uses an EasySRT health-read token to poll the sender and a separate notification-service event-submit token to report transitions. EasySRT may also submit events directly. No notification component gains stream-restart rights by default; #14 owns path recovery.

## Current code and consequences

| Evidence | Design consequence |
| --- | --- |
| `api/deps.py` authenticates a signed session cookie and checks a stored session hash; `models/auth.py` defines Owner, Engineer, Operator | Add a separate opaque API credential type and an explicit principal/permission layer; preserve browser sessions |
| Many config/service routes use only `require_user`; transfer routes additionally check Owner/Engineer; updates and user administration check Owner | Establish and test a shared capability policy for sessions and tokens. Existing role names alone do not prove granular enforcement |
| `main.py` applies cookie-based CSRF checks; CORS currently permits Content-Type and X-CSRF-Token | Resolve the authentication mode before applying CSRF; bearer access must not accidentally fall back to cookies |
| Config responses include source URLs; service status, logs, diagnostics and updates may include detailed paths, commands or stderr | Build deliberately sanitised external response schemas, including error responses; do not expose internal objects unchanged |
| Saving a named preset rewrites runtime files and selects it | Complete #16 before exposing independently scoped preset-write and apply actions |
| One sender/input/output exists per instance | Use stable instance and path identifiers, initially path `default`; do not invent multi-path controls |
| Current status proves process/preflight state, not sustained media flow | Media-health/history endpoints depend on #14's verified evidence. Until available, report `unknown`/`unsupported`, never infer healthy media from systemd active |
| Production OpenAPI/docs are currently disabled; frontend proxies `/api` | Publish a curated versioned API specification and verify proxy routing/header forwarding; keep raw backend/helper ports private |
| Database initialisation uses `create_all()` | Introduce explicit, versioned schema migration/upgrade/rollback handling for tokens and audit records |

## 1. Authorisation model

Use readable action keys such as `health:read`, `service:restart`, `presets:update`. Read, create, update, delete, apply, import, export and secret access are independent capabilities where meaningful. Do not offer a single `write`, `admin` or runtime wildcard as a substitute for granular scopes.

Each grant binds an action to its allowed resources. Avoid separately storing a global list of actions and a global list of resources, which could inadvertently grant every combination.

```json
{
  "name": "Studio monitoring",
  "integration": "external-monitor",
  "expires_at": "2027-01-22T00:00:00Z",
  "grants": [
    {"scope": "health:read", "resource": {"instance_id": "inst-123", "path_id": "default"}},
    {"scope": "system:read", "resource": {"instance_id": "inst-123"}}
  ]
}
```

Every request must satisfy credential validity, issuer/instance binding, enabled owning identity, current role ceiling, the exact action, every affected resource and service-state constraints. Fail closed for unknown scopes, resource types, IDs and newly introduced actions. Role upgrades must not add token grants; role downgrades remove effective access immediately. Disabled owners invalidate their tokens. Ownership transfer requires an explicit audited owner operation and credential rotation.

Use resource IDs, never mutable names, caller-supplied ownership fields or URL prefixes. Filter list results, counts, pagination and references to authorised objects before serialisation. Return 404 for objects outside a token's resource visibility. An Apply grant must bind both the allowed source preset(s) and target path; authorisation must not independently combine two unrelated grants. Import/export must check every affected collection/item. A saved input/destination permission cannot authorise changing the active site config.

Support explicit selection and an explicit “all current and future resources in this collection” option, clearly labelled. New actions are always excluded from existing tokens. A collection-create grant can create items inside that collection and operate on its own created items only if those further actions were explicitly granted; creating an item must not expand permission over existing items. Restrict instance-wide settings to instance-wide grants. Do not pretend a path restriction can safely narrow a global setting.

Proposed role ceiling: Operator can read sanitised operational state, view approved presets and start/stop/restart or apply approved presets; Engineer additionally manages configuration/presets and diagnostics; Owner additionally manages users, updates, tokens and audit access. Secret reading is a separate explicit capability for Engineer/Owner, excluded from ordinary operational presets. Implement this policy centrally, document any change from current session behaviour, and enforce it in the API as well as UI. Initial token issuance/administration is Owner-only; an Owner may issue a token associated with an enabled lower-role account, bounded by that account's ceiling.

## 2. EasySRT endpoint and scope catalogue

Expose a curated `/api/v1` API. Existing browser `/api/*` routes remain session-only until explicitly migrated; bearer credentials must never work on a legacy route solely because it calls `require_user`. Reuse service-layer logic rather than making external API handlers call browser endpoints.

Each semicolon-separated operation below has the corresponding separately selectable scope. `{id}` denotes a stable resource ID. The initial service endpoints address the instance's sole sender; per-path health reads use `default`. Multi-path writes need a later capability/version review.

| Group | Proposed endpoints under `/api/v1` | Granular scopes | Delivery / notes |
| --- | --- | --- | --- |
| Discovery | `GET /`; `GET /auth/token`; `GET /scopes`; `GET /scope-presets` | Authenticated baseline; own credential only | Version/features, effective grants, expiry and supported scope catalogue; no other-token metadata or secret |
| Process state | `GET /service/status` | `service:read` | First release; sanitised state and permitted actions, clearly separate from media health |
| Media health | `GET /health`; `GET /paths`; `GET /paths/{id}/health` | `health:read` | #14-dependent data: input/output progress, retry state, intentional stop, freshness, evidence and receiver-verification status |
| Metrics | `GET /metrics` | `metrics:read` | Bounded Prometheus text; same filtering as JSON; no credentials, URLs or unbounded labels |
| Transition history | `GET /health/events`; `GET /paths/{id}/events` | `health-events:read` | Cursor/time-bounded events; availability depends on persistent history implementation |
| Stream control | `POST /service/start`; `POST /service/stop`; `POST /service/restart` | `service:start`; `service:stop`; `service:restart` | Each independent. Stop honours #14 intentional-stop semantics. Never accept arbitrary service names/commands |
| Troubleshooting | `GET /diagnostics`; `GET /logs` | `diagnostics:read`; `logs:read` | Sanitised, bounded results; no unauthorised probing or raw runtime commands |
| Instance information | `GET /system` | `system:read` | Version/instance identity/platform summary; omit private filesystem paths by default |
| Active configuration | `GET /config`; `PATCH /config/app`; `PATCH /config/site` | `config:read`; `config-app:update`; `config-site:update` | Read omits secrets; site changes select configuration, never implicitly restart; revision/If-Match protection |
| Configuration validation | `POST /config/validate` | `config:validate` | Static validation only, no state changes/network probes. Active network checks stay separately authorised diagnostics |
| Preset library | `GET /presets`; `GET /presets/{id}`; `POST /presets`; `PATCH /presets/{id}`; `DELETE /presets/{id}` | `presets:read`; `presets:create`; `presets:update`; `presets:delete` | #16: reads/edits/save never activate; list/detail share read capability |
| Preset activation | `POST /presets/{id}/apply` | `presets:apply` | #16: exact revision + target instance/path; changes selected snapshot only. Restart requires `service:restart` separately |
| Saved sources | `GET /inputs`; `GET /inputs/{id}`; `POST /inputs`; `PATCH /inputs/{id}`; `DELETE /inputs/{id}` | `inputs:read`; `inputs:create`; `inputs:update`; `inputs:delete` | List/create backed by current library; detail/edit/delete are extensions; source credentials redacted |
| Saved output destinations | `GET /destinations`; `GET /destinations/{id}`; `POST /destinations`; `PATCH /destinations/{id}`; `DELETE /destinations/{id}` | `destinations:read`; `destinations:create`; `destinations:update`; `destinations:delete` | Stream destinations, distinct from notification delivery destinations |
| Transfer | `GET /config/export`; `POST /config/import/preview`; `POST /config/import` | `config:export`; `config-import:preview`; `config:import` | Require affected-object read/create/update grants too. Preview alone cannot commit; import never applies. Bind preview to actor, token, decisions and revisions |
| Secret handling | Conditional secret fields on authorised config/library reads, exports and writes | `secrets:read`; `secrets:update` | Additional resource-bound gates, never standalone access. Ordinary update preserves omitted secrets; replacing/clearing needs secret-update. No raw-secret logs endpoint |
| Redundancy visibility | `GET /redundancy/status`; `GET /redundancy/config-sync` | `redundancy:read`; `config-sync:read` | Read views only; does not enable takeover or forge partner acknowledgements |
| Updates | `GET /updates/status`; `POST /updates/check`; `POST /updates/install`; `GET /updates/jobs/{id}` | `updates:read`; `updates:check`; `updates:install` | Later, Owner ceiling; install returns a bounded job reference. Preserve root-managed update allowlist and helper boundary |
| Audit | `GET /audit-events` | `audit:read` | Later, Owner ceiling, filtered/paginated. Never includes credential material or secret-bearing request/response bodies |

Implementation notes:

- A GET must not trigger network probes, update checks or state changes merely to populate a response. Cache observations and expose explicit authorised commands for expensive/active work.
- Status responses and control responses must use sanitised schemas. Filtering only GET /config is insufficient: mutation responses, validation errors, journal messages, URLs, headers, query strings and stderr can leak secrets too.
- Secret fields use explicit omitted/present/clear semantics; a redacted placeholder must never overwrite the real secret. Presets containing credentials can be applied by reference without revealing them. Secret access does not confer Apply or Restart rights.
- A redacted export declares which secrets were excluded. Importing it cannot clear existing secrets accidentally. Full exports require `config:export`, relevant resource reads and `secrets:read`; secret-bearing imports need `secrets:update` as well as ordinary write grants.
- Redundancy partner acknowledgements stay on a distinct partner protocol/identity. General integration tokens cannot claim a remote node acknowledged a config. Defer takeover/failover endpoints until their controller and authority rules exist.
- User/password/bootstrap/session administration, shell execution, host reboot and updater handoff URLs are excluded from ordinary integration access. The API must not issue a session cookie or higher-privilege updater credential in exchange for a narrow token.

## 3. Scope presets and granular customisation

Presets are versioned templates expanded into explicit grants at token creation. Store template ID/version as provenance, but authorise only the stored grants. Changing a template or adding routes never changes an existing token. Never persist `monitoring:*`, `write:*` or `admin:*` as a future-expanding authority.

| Preset | Initial selected scopes | Typical use |
| --- | --- | --- |
| Monitor | `service:read`, `health:read`, `metrics:read`, `system:read`, `redundancy:read` | External monitoring and dashboards; no configuration/secret/log access |
| Troubleshooting | Monitor + `health-events:read`, `diagnostics:read`, `logs:read`, `config-sync:read` | Support integration; sanitised logs may still contain operational details |
| Stream operator | `service:read`, `health:read`, `presets:read`, `presets:apply`, `service:start`, `service:stop`, `service:restart` | Automation deck/scheduler restricted to approved presets and one sender |
| Preset librarian | `presets:read/create/update`, `inputs:read/create/update`, `destinations:read/create/update`, `config:validate` | Prepare configurations without activation, deletion or secret disclosure |
| Configuration engineer | Librarian + `config:read`, `config-app:update`, `config-site:update`, `presets:apply` | Deliberately change selected config; stream start/restart still opt-in |
| Configuration backup | `presets:read`, `inputs:read`, `destinations:read`, `config:export` | Portable library backup; secrets excluded unless added explicitly |
| Configuration transfer | Backup + `config-import:preview`, `config:import`, applicable library create/update actions | Import/export libraries without applying them; deletion/secret access excluded |
| Update automation | `system:read`, `updates:read`, `updates:check`, `updates:install` | Later; Owner-only capability with explicit install warning |
| Custom | No initial grants | Select any supported combination within the role/resource ceiling |

The slash lists in this table expand to individual keys, e.g. `presets:read`, `presets:create`, `presets:update`. Group headings in the UI are organisational only. Secrets, deletion, software installation and token administration require deliberate selection; they are never inferred from the word “Engineer.” Do not offer an unrestricted default “Full access” preset.

UI flow: Administration → API tokens → Create token → name/integration/owning account → preset → allowed resources → optional customisation → expiry → review effective access → create → copy secret once.

Group the editor into Monitoring, Stream control, Active configuration, Preset library, Sources and destinations, Transfer, Secrets, Redundancy, Updates and Audit. Each has tri-state group checkboxes and one checkbox per action, explanatory text, endpoint examples and resource selectors. Show “Customised from Monitor” after an edit. Search by endpoint/action; allow multiple presets as the union of their explicit grants, then let the user remove any individual grant. Do not silently re-add a removed scope because another preset includes it.

Dependencies remain visible: a workflow may need multiple scopes, but an API caller may legitimately need only one. For example, a stop-only emergency token need not read configuration, and `presets:apply` need not grant preset payload read. Warn about a nonfunctional UI workflow without secretly adding permissions. Review states exactly what can be changed, whether streaming can be interrupted, what secrets can be read and whether future resources are included.

For existing tokens show name, integration, owning identity, prefix/ID, status, issue/expiry times, last authenticated use, effective grants, resource limits, creator and rotation status. Filter by integration, owner, preset/custom and expiry. Provide rename, narrow/change grants, shorten/extend expiry, rotate, revoke, bulk revoke and audit history. Widening grants or extending lifetime requires fresh Owner reauthentication and an audit diff. Revoked/expired token IDs cannot be revived; issue a new credential instead.

## 4. Credential lifecycle and management endpoints

Create opaque random credentials with a service-specific format such as `esrt_<public-id>_<secret>`, with at least 32 cryptographically random secret bytes. Notification credentials use a different prefix and issuer. Store the public lookup ID and a SHA-256 digest of the high-entropy secret; verify with constant-time comparison. Password hashing remains separate. A database lookup/check on each request gives straightforward immediate revocation; avoid self-contained long-lived JWT permissions or worker-local validity caches initially.

Require HTTPS for bearer requests, even where browser LAN HTTP is explicitly enabled. Trust forwarded scheme/client address only from configured proxies; test the production frontend proxy and ingress chain. Never accept a token in a URL, cookie or request payload. API-only routes use `Authorization: Bearer ...`; browser routes use sessions. Reject ambiguous session-plus-bearer requests, and reject invalid bearer credentials rather than falling back to a session. Apply CSRF to session-authenticated mutations; bearer-only routes never authenticate via cookies. Cross-origin browser API access is disabled by default; if enabled later, allowlist origins and the required Authorization/Idempotency-Key/If-Match headers explicitly.

Initial management API, under `/api/v1`, requires an Owner browser session, CSRF protection for mutations and fresh password confirmation for issuance, rotation, widening grants and extending expiry. These are authenticated API workflows usable by the UI; ordinary integration bearer tokens cannot manage tokens.

| Endpoint | Purpose |
| --- | --- |
| `GET /tokens` | Paginated metadata only, optionally filter by integration/owner/status |
| `POST /tokens` | Validate grants/resources/expiry/ceiling; create record and initial credential; return secret once |
| `GET /tokens/{id}` | Metadata and effective/blocked grants; never recover secret |
| `PATCH /tokens/{id}` | Rename, change grants/expiry/resource limits with revision checking and audit diff |
| `POST /tokens/{id}/rotate` | Create one replacement credential, optional bounded old-credential overlap |
| `POST /tokens/{id}/revoke` | Immediately revoke every credential for the logical token; idempotent |
| `POST /tokens/revoke` | Atomic or explicitly reported bulk revocation, with audited IDs/results |
| `GET /tokens/{id}/audit-events` | Filtered administrative and relevant usage history |

Data model: `ApiToken` (logical ID, issuer instance, name, integration, owner ID, creator ID, explicit grants, template provenance, created/updated/expiry/revoked times, revision); `ApiTokenCredential` (public lookup ID, token ID, digest, created/last-used/retire/revoked times, replaced-credential ID); `AuditEvent` (actor type/user/token ID, action, non-secret resource IDs, outcome, request ID, time and safe change metadata). Use relational grant rows or strictly validated canonical JSON; do not use unchecked free-form scope strings.

Proposed lifetime defaults: 90 days, choices of 7/30/90/365 days or a shorter custom timestamp, maximum 365 days. No never-expiring token in the initial release. Reject expiry beyond the ceiling and consistently handle UTC/SQLite timestamp normalisation. Surface upcoming expiry in the UI; later notification-service reminders can be optional, without making token validity depend on that service.

Rotation creates a new credential under the same logical token; both credentials obey the same current grants/expiry/revocation state. Default old-credential retirement is immediate; operator can request up to 24 hours overlap to update a remote integration. Display the retirement deadline and identify which credential was last used. Allow at most two valid credentials; a second rotation explicitly retires the older credential. Revoke invalidates both. Never log either secret, including during creation errors. If a creation response is lost, metadata may be retrieved but the secret cannot; revoke/rotate and create a replacement. Do not cache secret responses to support retries.

Return token secrets only in no-store creation/rotation responses, never URL parameters or analytics. Keep the transient reveal out of persistent frontend/query storage; clear it on dismissal. Protect the token database and backups as credential/security data even though bearer secrets are hashed. Never export API token records with portable stream configurations, replicate them to a partner or accept them in config imports. A cloned/restored installation needs explicit identity/credential recovery handling; do not accidentally clone an issuer's working credentials onto another instance.

Programmatic token administration can be added later with individual `tokens:read/create/update/rotate/revoke` management scopes. It must be Owner-bound, explicitly enabled, resource-limited and unable to issue/change grants or lifetimes beyond its own delegable authority. Do not ship a generic token-admin bearer scope before these delegation rules and tests exist. This keeps initial integration credentials unable to mint more credentials while preserving an authenticated management API.

## 5. Notification-service API boundary from issue #15

These endpoints belong to the independently deployable notification service, with its own `/api/v1`. They are a second delivery track, not extra routes bolted into the EasySRT sender API.

| Group | Useful endpoints | Independent scopes |
| --- | --- | --- |
| Ingestion | `POST /events`; `GET /events/{id}` | `events:submit`; `events:read` |
| Delivery visibility | `GET /deliveries`; `GET /deliveries/{id}` | `deliveries:read` |
| Delivery control | `POST /deliveries/{id}/retry` | `deliveries:retry` |
| Incidents | `GET /incidents`; `GET /incidents/{id}`; `POST /incidents/{id}/acknowledge` | `incidents:read`; `incidents:acknowledge` |
| Integration identities | `GET/POST /integrations`; `PATCH/DELETE /integrations/{id}` | `integrations:read/create/update/delete`, separately selectable |
| Delivery destinations | `GET/POST /destinations`; `PATCH/DELETE /destinations/{id}`; `POST /destinations/{id}/test` | `destinations:read/create/update/delete/test`, separately selectable |
| Alert policies | `GET/POST /rules`; `PATCH/DELETE /rules/{id}` | `rules:read/create/update/delete`, separately selectable |
| Maintenance suppression | `GET/POST /maintenance-windows`; `PATCH/DELETE /maintenance-windows/{id}` | `maintenance:read/create/update/delete`, separately selectable |
| Service operations | `GET /health`; `GET /metrics`; `GET /audit-events` | `health:read`; `metrics:read`; `audit:read` |
| Credentials | Same token metadata/create/rotate/revoke workflow as above | Owner/admin session only initially |

Notification presets: **Event producer** = `events:submit`; **Producer with receipts** = add `events:read`, `deliveries:read` for that integration's own events; **Incident desk** = `incidents:read/acknowledge`, `deliveries:read`; **Delivery operator** = delivery read/retry and destination read/test; **Notification administrator** = explicitly chosen integration, destination, rule and maintenance CRUD, excluding token administration and secret disclosure. Every preset remains fully editable. Destination credentials are write-only where possible; destination read/test permissions cannot reveal or override stored secrets/addresses.

Scope every event, delivery and incident to its integration; validate producer-supplied instance/path identifiers against registration. An event producer cannot choose arbitrary delivery destinations or bypass routing/maintenance policy. Scope delivery reads/retries through the originating event/integration as well as the destination. Events and destination requests must be bounded and schema-validated; delivery connectors need a controlled network/egress policy so destination administration or tests cannot probe protected internal services.

Accept a versioned event envelope with event ID, integration/source, instance/path, observed time, type/severity, reason and structured non-secret evidence. Deduplicate by integration + producer event ID or idempotency key + payload hash: same content returns the same receipt; changed content using that ID conflicts. Persist the receipt and enqueue work transactionally before returning 202. Event receipt permission does not imply delivery visibility. Retry a delivery only through a separately authorised action; ordinary event retransmission must not force another notification. Bounded retry/backoff, incident state, cooldowns, maintenance and receiver-channel adapters remain the notification implementation work in #15. First channel selection is still a separate design decision; auth can be built without assuming a particular provider.

## 6. Reliability, limits, errors and auditing

- **Errors:** structured stable `code`, safe message and request ID; 401 invalid/expired/revoked credential, 403 known visible capability denied, 404 invisible/missing resource, 409 revision/idempotency conflict, 422 invalid payload, 429 rate limit with Retry-After, 503 transient/unavailable capability. Include WWW-Authenticate on bearer 401s. Do not reveal another integration's IDs, grants or stored values in errors.
- **Limits:** configurable per-token and per-instance quotas, request/body/pagination bounds and stricter command/destination-test limits. Initial load-test targets: ten monitors polling every five seconds, 120 reads/minute/token with burst 20; at most six disruptive service commands/minute/token with burst two; separate low-volume diagnostic probes and stricter token-creation limits. Validate these provisional values against real operations; do not let API floods starve Stop or streaming. Notification ingestion needs separate per-integration/global queue limits and capacity tests.
- **Commands:** serialise Start/Stop/Restart with the existing helper and #14 controller; add revision/state preconditions. Support an idempotency key for disruptive commands, scoped to token/operation/resource/body, with a bounded persistent retention window (proposed 24 hours). Replays cannot repeat a restart, and must pass current auth before returning even a prior result. Timeouts after a side effect need reconciliation, never blind retries.
- **Revocation:** check database validity before each authorised operation and immediately before a queued privileged action executes. Revocation blocks new work once committed; it cannot undo a completed/in-flight sender action. Reauthorise queued work; bound any later long-lived streams and reconnect/terminate them on revocation. Fail closed if credential storage is unavailable.
- **Usage:** last-used records successful authentication, even when a later scope/resource check denies the operation. Record outcome separately; batch last-used timestamp persistence within a documented short lag to avoid a SQLite write for every metric scrape. Validity/revocation checks are never batched. Audit all token administration, denied privileged actions and successful mutations; aggregate routine successful reads with counters/last-used metadata. Apply bounded retention and per-token denial sampling to prevent log/DB flooding while preserving critical administration records.
- **Audit integrity:** persist administrative change plus audit event in one transaction. External helper actions record intent, dispatch and observed outcome with request ID, including unknown results after timeouts. Pass explicit user/token identity into services/helper audit context; do not impersonate an Owner to reuse a User-only function. Respect the existing root helper's allowlist/socket and root-controlled update policy.
- **Persistence:** SQLite is appropriate for a single-instance first release with short transactions, bounded indexes/history and concurrency tests. Do not introduce Redis or an identity server solely for token validation. Revisit a shared limiter/store, partitioned audit retention and delegated administration if multiple API replicas or central fleet management are introduced. No claim of exactly-once external notification delivery: connectors need provider idempotency where supported, and otherwise document residual duplicate risk after a crash.

## 7. Implementation sequence

1. **Contract and policy:** settle scope registry, role ceiling, resource grammar and API schemas. Freeze operation-to-scope mapping; mark #14-dependent capabilities in discovery. Finish #16's save/apply boundary before enabling those permissions. Record issuer/standalone-service boundary as an architecture decision.
2. **Authentication foundation:** new models/migrations, opaque credential verifier, explicit session/bearer principal resolution, central permission dependency, secret-redaction utilities, audit schema and HTTPS/proxy checks. Adapt the helper actor context without adding arbitrary privileged commands.
3. **Token management:** Owner session/CSRF/reauth management endpoints and Administration UI; versioned preset templates, granular resource/action selector, one-time reveal, expiry/rotation/revoke and permission review. Test simultaneous rotate/revoke/update requests.
4. **Useful external API:** discovery, sanitised process/system status, then #14-backed health/metrics/history; independently scoped service controls; #16-backed preset/config/library/transfer routes. Treat update automation as a later explicit feature gate. Keep unsupported future scopes unissuable.
5. **Standalone notification integration:** implement the notification service's own token issuer/management and event/receipt API, then destination/rule/history surfaces. Ship an external-monitor example with two tokens and an EasySRT producer example. Persist producer event IDs/outbox if delivery must survive restarts. Store outbound notification credentials separately with service-account file permissions or encryption backed by a separately protected key; they must be retrievable for outbound use, unlike incoming token hashes.
6. **Release:** curated OpenAPI with security schemes and per-operation required scopes/resource semantics; curl examples, expiry/rotation recipes, errors/idempotency/rate-limit documentation. Test real HTTPS ingress and fresh install/upgrade/rollback without restarting the live sender. Update deployment documentation and retain independent notification-service deployment.

Likely code areas: new `models/api_token.py`, `models/audit.py`, `schemas/api_token.py`, `services/api_tokens.py`, `services/authorization.py`, `services/redaction.py`, versioned API routers, `api/deps.py`, `main.py`, `core/db.py`, host-control actor plumbing; frontend `features/admin/api-tokens`, `lib/api.ts`; proxy/installer/update compatibility tests and curated API docs. Follow the repository's existing layered FastAPI/SQLModel/React structure rather than introducing a second application framework.

## 8. Acceptance and verification

| Test area | Required result |
| --- | --- |
| Credential lifecycle | Valid token works; malformed/wrong-issuer/expired/revoked/disabled-owner credentials fail; no plaintext credential in database/list/audit/errors/logs |
| Authentication boundary | Invalid bearer never falls back to cookie; ambiguous auth rejected; cookies retain CSRF; unauthorised legacy/browser/updater routes reject bearer tokens |
| Full scope matrix | Every method/operation declares its exact action/resource policy; enumerate routes in a coverage test so a new unclassified endpoint fails CI |
| Granularity | Stop-only token cannot start/restart; preset-edit cannot Apply; Apply cannot Restart; read cannot mutate; destination-test cannot edit; ingestion cannot administer routing/tokens |
| Resource isolation | Different instances, paths, presets/integrations and cross-resource actions remain isolated; list counts/cursors/errors cannot leak hidden records |
| Preset evolution | Custom edits survive; template changes/new actions do not broaden old tokens; deliberate future-resource option behaves exactly as labelled |
| Owner/role changes | Disabled owner and role downgrade take effect immediately; tokens never gain scopes on role upgrade; widening/expiry extension requires Owner reauthentication |
| Secret handling | Redacted read/write/export/errors preserve secrets without disclosure; explicit secret changes require correct extra grant; portable import/export cannot copy token credentials |
| Rotation/concurrency | One-time reveal; bounded overlap; simultaneous rotation/revoke cannot leave an unintended credential valid; resource/grant edits apply to both rotation credentials |
| Command safety | Current authorisation rechecked for queued/replayed work; idempotent restart replay performs one action; Stop remains available under bounded read load |
| Health truthfulness | Fresh input/output evidence distinguished from process status and receiver receipt; missing/stale/unimplemented telemetry reports unknown; silent progressing media remains valid |
| Notifications | External app submits with its own token and obtains an authorised receipt/status; duplicates/conflicts/rate limits behave as documented across restarts |
| Runtime independence | Monitor and notifications operate with UI closed; no competing restart controller; expiry/revocation fails visibly without interrupting streaming |
| Deployment | HTTPS required even with LAN HTTP UI; trusted proxy scheme handling proven; Authorization forwarded; private backend/helper ports stay private; DB upgrade/restore rules tested |

Run focused backend authorisation/migration/API tests, frontend token-editor/lifecycle tests, the existing backend/frontend suites and affected ops regression tests. Rehearse on supported Ubuntu through the production proxy; mocked FastAPI tests alone do not establish HTTPS/header/privileged-action behaviour. Do not mark all of #15 complete merely because EasySRT token management ships: standalone event ingestion, monitoring transitions and durable notification delivery remain its separate acceptance requirements.
