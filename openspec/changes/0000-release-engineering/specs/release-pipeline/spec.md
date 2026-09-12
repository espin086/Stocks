# release-pipeline — spec delta (0000)

## ADDED Requirements

### Requirement: One definition of green

The release gate SHALL be the same workflow as the pull-request gate, not a copy.

#### Scenario: Release reuses CI
- **WHEN** the release workflow verifies a commit
- **THEN** it SHALL invoke `ci.yml` via `workflow_call`
- **AND** SHALL NOT restate any lint, type, test, or audit step of its own

#### Scenario: Single required status check
- **WHEN** branch protection is configured for `main`
- **THEN** exactly one check, `All checks passed`, SHALL be required
- **AND** that job SHALL fail if any dependency failed, was cancelled, **or was
  skipped**, so a skipped required job never reads as a pass

### Requirement: Version-gated publishing

Publishing SHALL be driven by the version declared in
`src/quantfolio/__about__.py`, because index versions are immutable.

#### Scenario: New version on main
- **WHEN** a push to `main` declares a version absent from the target index
- **THEN** the pipeline SHALL build, verify, and publish it

#### Scenario: Unchanged version on main
- **WHEN** a push to `main` declares a version already on the index
- **THEN** the pipeline SHALL publish nothing and exit successfully
- **AND** the run summary SHALL state the version and what to bump to release

#### Scenario: First ever release
- **WHEN** the distribution does not exist on the index at all
- **THEN** the pipeline SHALL treat the declared version as publishable

#### Scenario: Malformed version
- **WHEN** the declared version does not match the accepted PEP 440 subset
- **THEN** the run SHALL fail before any artifact is built

#### Scenario: Index unreachable
- **WHEN** the index returns any error other than 404
- **THEN** the run SHALL fail
- **AND** SHALL NOT treat the failure as "no versions published", which would
  attempt to re-publish an existing version

### Requirement: Publishing is armed explicitly

#### Scenario: Disarmed by default
- **WHEN** the repository variable `RELEASE_ENABLED` is not `true`
- **THEN** no publish to PyPI SHALL occur
- **AND** the run SHALL succeed, reporting that releases are not armed

#### Scenario: Rehearsal is always available
- **WHEN** the workflow is dispatched manually with target `testpypi`
- **THEN** it SHALL publish to TestPyPI regardless of `RELEASE_ENABLED`

### Requirement: No long-lived publishing credential

#### Scenario: Trusted Publishing
- **WHEN** the pipeline uploads to an index
- **THEN** it SHALL authenticate via OIDC with `id-token: write`
- **AND** no PyPI API token SHALL exist in repository secrets

#### Scenario: Attested artifacts
- **WHEN** a distribution is published
- **THEN** PEP 740 attestations SHALL be generated, binding the artifact to the
  workflow and repository that built it

#### Scenario: Least privilege
- **WHEN** any workflow runs
- **THEN** the workflow-level default permission SHALL be `contents: read`
- **AND** any broader permission SHALL be granted on the single job needing it

### Requirement: Artifacts are verified before upload

#### Scenario: The built wheel actually works
- **WHEN** distributions are built
- **THEN** the wheel SHALL be installed into a clean virtual environment and
  both console scripts executed, before any upload
- **AND** the sdist SHALL be proven to build a wheel

#### Scenario: Built version matches the authorization
- **WHEN** the build completes
- **THEN** the artifact filenames SHALL be asserted against the version whose
  absence from the index authorized the publish
- **AND** a mismatch SHALL fail the run

#### Scenario: Metadata is valid
- **WHEN** distributions are built
- **THEN** `twine check --strict` SHALL pass

### Requirement: A shipped version is a documented version

#### Scenario: Changelog gate
- **WHEN** a publish is about to be authorized
- **THEN** `CHANGELOG.md` SHALL contain a section heading for that version
- **AND** the run SHALL fail with that instruction if it does not

#### Scenario: Enforced from the test suite too
- **WHEN** `pytest` runs
- **THEN** a test SHALL assert the changelog documents the current version, so
  the omission is caught locally rather than in a release run

### Requirement: Releases are recorded on GitHub

#### Scenario: Tag and release
- **WHEN** a publish to PyPI succeeds
- **THEN** a `v<version>` tag and a GitHub release with generated notes SHALL be
  created, with the distributions attached

#### Scenario: Idempotent
- **WHEN** a release for that tag already exists
- **THEN** the step SHALL succeed without creating a duplicate

### Requirement: Supply-chain scanning

#### Scenario: Dependency audit gates merges
- **WHEN** CI runs
- **THEN** `pip-audit --strict` SHALL run and a known vulnerability SHALL fail it
- **AND** an unfixable advisory SHALL be handled by a named `--ignore-vuln` with
  a written justification, never by removing or soft-failing the step

#### Scenario: Static analysis
- **WHEN** code is pushed to `main` or proposed in a pull request
- **THEN** CodeQL SHALL analyze it, and SHALL also run weekly on a schedule

#### Scenario: Dependency updates
- **WHEN** dependencies or actions fall behind
- **THEN** Dependabot SHALL open grouped weekly pull requests
- **AND** runtime major-version bumps SHALL be excluded, as deliberate decisions

### Requirement: Local parity

#### Scenario: Same checks before commit
- **WHEN** a contributor installs the pre-commit hooks
- **THEN** the ruff, format, and mypy checks they run SHALL be the ones CI runs

#### Scenario: The release decision is inspectable
- **WHEN** a contributor runs `python .github/scripts/check_release.py`
- **THEN** it SHALL print what the next push to `main` would do
