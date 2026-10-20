#!/usr/bin/env bash
#
# Agent hook: artifact check.
#
# Verifies that the repository's ignore rules still match the artifacts this
# project actually produces. Build output, caches, and the native crate's
# target directory all appear during a normal build cycle; if one of them
# ever becomes tracked, that is a packaging or tooling change that needs to
# be deliberate rather than accidental.
#
# Usage: scripts/agent/check-artifacts.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

failures=0

fail() {
  printf '  [fail] %s\n' "$1" >&2
  failures=$(( failures + 1 ))
}

pass() {
  printf '  [ ok ] %s\n' "$1"
}

echo "Keep or Nah - artifact check"

# 1. No tracked file may live inside a build or cache directory.
tracked_junk=$(git ls-files | grep -E \
  '(^|/)(__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.pyinstaller|node_modules|target|build|dist)(/|$)|\.py[co]$|\.so$|\.dylib$|\.pyd$|\.DS_Store$' || true)

if [[ -n "$tracked_junk" ]]; then
  fail "tracked files inside build/cache directories:"
  printf '%s\n' "$tracked_junk" | sed 's/^/         /' >&2
else
  pass "no tracked files inside build/cache directories"
fi

# 2. The ignore rules must still cover every artifact directory the project
#    produces. Each entry is checked by asking git whether the path is
#    ignored, so this asserts the rule exists rather than the directory.
ignore_required=(
  ".DS_Store"
  ".venv/"
  "__pycache__/"
  ".pytest_cache/"
  ".ruff_cache/"
  ".pyinstaller/"
  "build/"
  "dist/"
  "crates/keep_or_nah_core/target/"
  "*.so"
  "*.dylib"
  "*.pyd"
  "freebuff-chat-*.md"
)

for pattern in "${ignore_required[@]}"; do
  probe="$(mktemp -u)/probe"
  mkdir -p "$(dirname "$probe")" 2>/dev/null || true
  # Use a path that matches the pattern so the ignore rule is exercised.
  case "$pattern" in
    "*.so") probe="$REPO_ROOT/probe.so" ;;
    "*.dylib") probe="$REPO_ROOT/probe.dylib" ;;
    "*.pyd") probe="$REPO_ROOT/probe.pyd" ;;
    ".DS_Store") probe="$REPO_ROOT/.DS_Store" ;;
    "freebuff-chat-*.md") probe="$REPO_ROOT/freebuff-chat-probe.md" ;;
    */) probe="$REPO_ROOT/${pattern%/}/probe" ;;
    *) probe="$REPO_ROOT/$pattern" ;;
  esac

  if git check-ignore -q "$probe" 2>/dev/null; then
    pass "ignore rule covers $pattern"
  else
    fail "no ignore rule covers $pattern"
  fi
done

# 3. The working tree must not be carrying a stray session transcript.
if [[ -f "freebuff-chat-2026-10-17T17-04-00.880Z.md" ]]; then
  fail "stray agent session transcript in the repository root"
else
  pass "no stray agent session transcript in the repository root"
fi

echo
if [[ $failures -eq 0 ]]; then
  echo "artifact check passed"
  exit 0
fi

echo "$failures artifact problem(s) found" >&2
exit 1
