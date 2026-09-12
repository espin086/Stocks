# Releasing

Releases are **version-gated pushes to `main`**. There is no release branch and
no manual upload step.

```
push to main
     │
     ▼
 decide ──── version in __about__.py already on PyPI? ──yes──► report "no release"
     │ no
     ▼
 verify ──── the full CI workflow, re-run on this exact commit
     │
     ▼
 build  ──── sdist + wheel, twine check, version assertion
     │
     ▼
 publish ─── Trusted Publishing (OIDC), PEP 740 attestations
     │
     ▼
 github-release ── tag v<version>, generated notes, artifacts attached
```

## Cutting a release

Three things in one PR:

1. Bump `__version__` in `src/sobres/__about__.py`.
2. Add a `## [<version>]` section to `CHANGELOG.md`.
3. Merge to `main`.

That's it. The pipeline notices the version is not on the index and publishes it.
If you merge anything else, `decide` reports "no release" and stops — pushing to
`main` ten times a day costs ten no-op runs, not ten failed uploads.

**Why version-gated and not "publish every push":** PyPI versions are immutable.
Re-uploading an existing version is a hard error, not an overwrite. "Publish on
push to main" can only mean "publish when the declared version is new" — any
other reading produces a red pipeline on every push that isn't a release.

## One-time setup

Until these are done, `decide` reports `publish=false` for PyPI and nothing is
uploaded. This is deliberate: merging the pipeline cannot fire a publish before
the pipeline can succeed.

### 1. Configure Trusted Publishing on PyPI

No API token is stored in this repository. PyPI verifies a short-lived OIDC
token issued by GitHub to this specific workflow.

Go to <https://pypi.org/manage/account/publishing/> and add a **pending
publisher**:

| Field | Value |
|---|---|
| PyPI project name | `sobres` |
| Owner | `AI-Solutions-Lab-LLC` |
| Repository name | `sobres` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

A *pending* publisher is the right kind — the project does not exist on PyPI
yet, and the first successful publish creates it.

Repeat at <https://test.pypi.org/manage/account/publishing/> with environment
name `testpypi` to enable rehearsals.

### 2. Create the GitHub environments

Settings → Environments → New environment, named exactly `pypi` and `testpypi`.

On `pypi`, add yourself under **Required reviewers**. Every publish then waits
for a one-click approval, which is the cheapest possible safeguard against an
accidental release. Optionally restrict the environment to the `main` branch.

### 3. Arm the pipeline

Settings → Secrets and variables → Actions → **Variables** → New variable:

| Name | Value |
|---|---|
| `RELEASE_ENABLED` | `true` |

This is the kill switch. Set it to anything else to stop all PyPI publishing
without touching a workflow file.

### 4. Protect `main`

Settings → Branches → Add rule for `main`:

- Require a pull request before merging
- Require status checks to pass → select **`All checks passed`**
- Require branches to be up to date before merging
- Do not allow bypassing the above settings

Select only `All checks passed`. It is an aggregator job that fails if any CI
job failed, was cancelled, *or was skipped* — so the test matrix can grow or
shrink without ever editing the protection rule.

## Rehearsing on TestPyPI

Actions → Release → **Run workflow** → target `testpypi`.

This runs the same build and publish path against TestPyPI. It works before
`RELEASE_ENABLED` is set, so you can prove the whole pipeline end to end without
touching real PyPI. Verify with:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ sobres
sobres --version
```

## Versioning

[Semantic Versioning](https://semver.org/). Pre-1.0, the CLI surface is not
stable and minor bumps may break commands.

`check_release.py` accepts `1.2.3`, `1.2.3rc1`, `1.2.3a1`, `1.2.3b1`, and
`1.2.3.dev0`. Anything else fails the run before a build happens.

Two places assert this format — `.github/scripts/check_release.py` and
`tests/test_packaging.py`. Keep them in step; the test exists so a bad version
fails `pytest` rather than a release run.

## What blocks a release

The release calls the CI workflow rather than duplicating it, so everything that
blocks a PR blocks a release:

| Gate | Failure mode |
|---|---|
| `ruff check` / `ruff format` | Lint or formatting drift |
| `mypy --strict` | Type error |
| `pytest` on 3.11–3.13 + macOS + Windows | Test failure, or coverage under 90% |
| Wheel smoke test | The built artifact does not import or run |
| sdist build | The source distribution cannot produce a wheel |
| `pip-audit --strict` | A known vulnerability in the dependency tree |
| `CHANGELOG.md` section | The version being shipped is undocumented |
| Version assertion in `build` | The built artifact's version is not the one authorized |

### Unfixable advisories

`pip-audit` blocking a release on a transitive advisory with no fixed version is
the one gate you may need to route around. Add the ID to the audit step in
`.github/workflows/ci.yml` with a comment saying why and when to revisit:

```yaml
# PYSEC-XXXX-NN: <package> has no fixed release as of <date>; not reachable
# from our code path because <reason>. Revisit when <package> ships a fix.
run: >-
  pip-audit --strict --progress-spinner=off
  -r requirements-audit.txt
  --ignore-vuln PYSEC-XXXX-NN
```

The audit runs against `pip freeze --exclude-editable`, not the ambient
environment. That covers every extra this project declares while excluding the
local editable install (not on any index, so never auditable) and the runner's
own `pip` and `setuptools`, whose advisories are the image's problem and would
otherwise fail CI for reasons unrelated to this codebase.

Never delete the audit step, and never make it `continue-on-error` — an ignored
advisory is a decision with a name on it; a disabled scanner is not.

## If a release goes wrong

**Published a broken version.** You cannot replace it. Yank it on PyPI (which
hides it from new installs without breaking existing pins), then ship a patch
version. Yanking is reversible; deleting is not, and a deleted version's number
can never be reused.

**Publish failed after a partial upload.** Re-running is safe: PyPI rejects
files it already has, and `decide` re-checks the index first.

**Need to stop everything.** Set `RELEASE_ENABLED` to `false`.
