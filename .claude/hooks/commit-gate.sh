#!/usr/bin/env bash
# Claude Code PreToolUse hook: before any `git commit` runs from a Bash tool call, run the
# same gate CI runs (ruff check, ruff format --check, mypy --strict). Exit 2 blocks the
# commit and hands the output back to the agent, so a red PR is caught before it exists.
#
# Reads the tool call as JSON on stdin; only acts when the command contains "git commit".
set -uo pipefail
payload=$(cat)
command=$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))' 2>/dev/null || true)
case "$command" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac
root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$root" || exit 0
fail=0
run() {
  local name=$1; shift
  if ! output=$("$@" 2>&1); then
    printf '\n[commit gate] %s failed:\n%s\n' "$name" "$output" >&2
    fail=1
  fi
}
run "ruff check" ruff check .
run "ruff format --check" ruff format --check .
run "mypy --strict" python -m mypy
if [ "$fail" -ne 0 ]; then
  printf '\n[commit gate] fix the findings above (ruff format . fixes formatting), then commit again.\n' >&2
  exit 2
fi
exit 0
