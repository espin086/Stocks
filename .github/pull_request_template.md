## What

<!-- One or two sentences. What does this change do? -->

## OpenSpec change

<!-- Which change under openspec/changes/ does this implement? Which tasks? -->
- Change: `openspec/changes/____`
- Tasks completed: <!-- e.g. B1, B2, B3 -->

## Scenarios covered

<!-- List the spec scenarios this PR implements, and the test proving each. -->
| Scenario | Test |
|---|---|
|  |  |

## Checklist

- [ ] Every new behavior has a scenario in a spec delta
- [ ] Every scenario has a test that references it
- [ ] `pytest -m "not network"` passes offline
- [ ] `ruff check`, `ruff format --check`, and `mypy` are clean
- [ ] No business logic added to `cli/`; no I/O added to `core/`
- [ ] No bare periods-per-year literals (use `core/conventions.py`)
- [ ] Task boxes checked off in the change's `tasks.md`
