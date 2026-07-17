# Releasing baseltest

Releases are published to [PyPI](https://pypi.org/project/baseltest/) by the
`.github/workflows/release.yml` workflow, which fires on a version tag
(`vX.Y.Z`). It uses **Trusted Publishing** (OIDC) — no API token is stored in
the repository or in GitHub secrets.

## One-time setup (before the first automated publish)

The `baseltest` project must already exist on PyPI (the initial name-reserving
upload is a manual `twine`/`uv publish` with an account-scoped token). Once it
exists, register the trusted publisher so the workflow can publish without a
token:

1. On PyPI: **Your projects → baseltest → Publishing → Add a new publisher**
   (GitHub Actions).
2. Fill in exactly:
   - **Owner**: `mavai-org`
   - **Repository**: `baseltest`
   - **Workflow name**: `release.yml`
   - **Environment**: `pypi`
3. In the GitHub repo, create the **`pypi`** environment
   (**Settings → Environments → New environment**). Optionally add protection
   rules (required reviewers, tag restrictions) — the workflow references this
   environment by name, and it is where you gate who can cut a release.

For a brand-new project you may instead configure a **pending publisher** on
PyPI (same four fields) *before* the project exists; the first workflow run
then both creates the project and publishes. Because the name is already
reserved by the placeholder release, use the ordinary "Add a new publisher"
path above.

## Cutting a release

1. Update `version` in `pyproject.toml` to the release version (drop any
   `.devN` suffix) and land it on `main` (e.g. a `Release X.Y.Z` commit).
2. Tag the release commit and push the tag:
   ```
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
3. The workflow runs the test suite, verifies the tag matches the packaged
   version, builds the sdist and wheel, and publishes to PyPI.
4. Bump `version` to the next `X.Y.Z.devN` on `main` (back-to-development).

Verify the tag reached origin (`git ls-remote --tags origin`) — a local-only
tag does not trigger the workflow.

## Notes

- The tag-matches-version check fails the build if `vX.Y.Z` is placed on a
  commit whose `pyproject.toml` version is not `X.Y.Z`. Tag the release commit,
  not a later back-to-development commit.
- PyPI versions are immutable: a version can be yanked but never re-uploaded.
  Rehearse against [TestPyPI](https://test.pypi.org) if in doubt (a separate
  trusted-publisher registration and a workflow variant pointing at the
  TestPyPI index are required — not wired by default).
