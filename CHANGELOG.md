# Changelog

This project follows Semantic Versioning and uses tags prefixed with `v`.

## Unreleased

- Added scoped integration API credentials and the API token management UI, with
  granular action/resource grants, expiry, rotation, immediate revocation and audit.
- Added HTTPS-only versioned health/control/configuration APIs, curated OpenAPI,
  bounded quotas/idempotency, and trusted-proxy enforcement for forwarded schemes.

- Separated preset Save/Open from explicit Apply, with revision conflicts,
  immutable selected/running snapshots, and independent apply/service permissions.
- Pinned Start/Restart to a reviewed selection; automatic recovery retains the
  current run after subsequent edits or application. Retired implicit activation
  through legacy Load and direct site writes; added database migration and
  recoverable generation publication.

- Added versioned configuration export, April-format migration and reviewed,
  transactional preset import without changing the active stream.
- Added explicit legacy SRT latency review, redacted previews and stale-preview
  protection, with API and configuration-screen regression tests.
- Included local privileged-helper, locked deployment, updater, bootstrap-owner,
  configuration validation and dependency fixes in the fresh-install candidate.

- Isolated tests from production data.
- Corrected FFmpeg argument ordering for black video frames.
- Hardened production authentication, cookies, CSRF, hosts, headers, and
  request sizes.
- Added tests, linting, builds, secret scanning, and release automation.
- Added installed version and commit reporting.
- Prepared AGPL-3.0-only public repository policies.

## 0.1.0-alpha.1 — Unreleased

Initial public alpha candidate.
