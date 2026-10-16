# Public alpha readiness

Status date: 16 October 2026. This repository starts from a cleaned source snapshot with a new Git history. Earlier development commits, pull requests and internal deployment records are not included. Existing licence, copyright, attribution and third-party notices are preserved.

## Validation status

The source snapshot passed automated validation before transfer: 115 backend tests, 11 frontend tests, eight deployment regression tests, frontend lint/build, dependency audits, operations validation and secret scanning. The fresh repository must pass its own CI before publication; consult its Actions results for current evidence.

These automated checks are not a new production deployment certification. Fresh Ubuntu installation, SRT receiver/audio acceptance, reboot, failed-update rollback and partner failover must be rehearsed for the selected release before operational rollout. Prior internal rehearsals do not certify this new snapshot.

## Remaining publication gates

- Keep the repository private until final content/security review and fresh CI are complete.
- Confirm licensing/contribution-policy review, CLA acceptance handling and security/release ownership.
- Enable required reviews/status checks and repository security features when supported by the GitHub plan. Do not publish a release tag until its protection and signature requirements can pass.
- Verify website DNS and public links when the website launches; an undeployed landing page does not block source preparation.
- Follow [the publication checklist](publication-checklist.md) and [release procedure](releasing.md).
