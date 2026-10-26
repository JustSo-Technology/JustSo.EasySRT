# Scoped API validation

Date: 25 October 2026 (Australia/Sydney). Baseline: merged PR #18, `00c29e3fe8e4916eab45b9ac3486b498ea3e7fff`.

The implementation adds EasySRT's scoped bearer API and Owner token-management UI. Standalone notifications/durable delivery from #15 remain separate work. No production sender, account, deployment or trust store was modified.

## Local results

- Full backend suite: **224 passed**, plus **43 subtests**. The focused scoped-API suite has **34 passing tests**. The existing Starlette TestClient/httpx deprecation warning remains.
- Frontend: **27 tests passed**, including six token-panel workflow tests. ESLint, TypeScript and production build passed using **Node 22.17.0** and the locked dependencies.
- Operations: **27 tests passed**, including untrusted/trusted proxy scheme handling and Authorization forwarding. Python compilation and diff whitespace checks passed.
- **Five real TLS lifecycle cases passed** using a temporary localhost uvicorn process with production security settings and no host-control socket. The test client explicitly trusts the fixture certificate with TLS verification enabled. No CA was installed. See [machine-readable results](issue-15-api-tls.json) and `ops/validate-scoped-api.py`.

The TLS rehearsal covers session/CSRF-protected issuance, bearer health/metrics/OpenAPI, denied legacy and unscoped control routes, secrets absent from metadata/SQLite/audit/access logs, rejection of query credentials, immediate rotation retirement and revocation over an actual TLS socket. Server/credentials/certificates are removed in cleanup. CI runs this rehearsal in the backend job.

The request tests additionally cover role downgrades, disabled owning accounts, wrong issuer/secret, expiry bounds, narrow resource lists before pagination, hidden-object responses, Apply-only versus Restart, sensitive source URL projection/preservation and independently granted secret write/read, scoped portable export, token-bound import preview/replay, atomic bulk revocation, revision conflicts, concurrent rotation, command replay, Stop capacity under exhausted monitoring quota, secure database permissions, body limits and endpoint policy coverage.

## UI validation

The integrated browser rendered the actual token panel with disposable preview data. Metadata, ownership, expiry, last use and lifecycle actions rendered correctly. An individual Apply grant was added, restricted to a single preset, and reviewed with its default-sender target and interruption/secret-access summary. The preview never issued a real credential and its temporary page/server were removed.

Automated UI tests cover review-before-create, one-time secret dismissal without recovery on refresh, resource selection, tri-state group controls, union of preset sets, removed permissions remaining removed, bounded rotation overlap, explicit bulk revoke confirmation and stale edits that retain the review without retrying. The UI stores bearer revelations only in transient component state.

## Limits

These checks establish authentication, authorisation, UI behaviour and localhost HTTPS transport; they are not a new production rollout or complete install/upgrade/restore certification. API auth uses SQLite and per-request validation. Incoming token hashes do not make credential database cloning safe: use the documented issuer/restore process. Successful-read last-use metadata is batched for at most 30 seconds; revocation is not cached. Transition history remains at most 20 events from the supervisor state, not a durable incident service.
