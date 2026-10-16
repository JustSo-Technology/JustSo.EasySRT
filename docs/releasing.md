# Releasing

Releases use Semantic Versioning. The first planned tag is
`v0.1.0-alpha.1`.

1. Update `CHANGELOG.md`, `backend/app/version.py`,
   `backend/pyproject.toml`, and `frontend/package.json`.
2. Run `bash tools/release-check.sh vX.Y.Z[-prerelease]`.
3. Run the full backend, frontend, operation, secret, installer, update, and
   rollback validation suite.
4. Merge through a reviewed pull request with required CI checks passing.
5. Create a signed annotated tag and push it:

```bash
git tag -s vX.Y.Z -m "JustSo.EasySRT vX.Y.Z"
git push origin vX.Y.Z
```

The release workflow validates version metadata, reruns tests and builds,
creates source archives, and publishes a GitHub release. Prerelease tags are
marked as prereleases automatically.

Do not move or reuse published tags.
