# Public repository publication checklist

Keep the repository private until this checklist is completed.

- Review documentation and fixtures for customer, site and internal infrastructure identifiers. Use generic names and synthetic data in public examples.
- Scan every published branch and tag, including historical file versions and commit messages. A current-file edit does not remove earlier versions.
- After any history rewrite, verify remote branch/tag tips, rerun CI and secret scanning, and tell collaborators to make fresh clones rather than merge old history back in.
- Check GitHub pull-request refs, old diffs, comments, attachments, Actions logs/artifacts and cached commit views separately. These are not removed by rewriting ordinary branches. Resolve retained private references with GitHub Support where necessary before changing visibility.
- Keep any pre-cleanup recovery bundle outside the repository with restricted access. Never publish or push it.
- Confirm publication approval for licensing/contribution policies and support ownership, then enable branch protection, required checks, secret scanning and private vulnerability reporting as available.

Source publication does not certify a production deployment. Keep the documented alpha status and deployment-validation limits until the selected release has passed the Ubuntu and receiver acceptance checks.
