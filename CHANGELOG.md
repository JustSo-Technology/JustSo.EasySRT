# Changelog

This project follows Semantic Versioning and uses tags prefixed with `v`.

## Unreleased

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
