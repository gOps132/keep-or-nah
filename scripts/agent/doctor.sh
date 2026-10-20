#!/usr/bin/env bash
#
# Agent hook: environment doctor.
#
# Diagnoses whether this machine can build and test Keep or Nah, and reports
# the specific fix for anything that is wrong. Run this first when something
# behaves unexpectedly - it distinguishes "the code is broken" from "the
# environment is not ready".
#
# Usage: scripts/agent/doctor.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CRATE_DIR="crates/keep_or_nah_core"
failures=0

report() {
  local status="$1" label="$2" detail="${3:-}"
  if [[ "$status" == "ok" ]]; then
    printf '  [ ok ] %-28s %s\n' "$label" "$detail"
  elif [[ "$status" == "warn" ]]; then
    printf '  [warn] %-28s %s\n' "$label" "$detail"
  else
    printf '  [fail] %-28s %s\n' "$label" "$detail"
    failures=$(( failures + 1 ))
  fi
}

echo "Keep or Nah - environment doctor"
echo

echo "toolchain"
if command -v uv >/dev/null 2>&1; then
  report ok "uv" "$(uv --version 2>/dev/null | head -1)"
else
  report fail "uv" "install: https://docs.astral.sh/uv/getting-started/installation/"
fi

if command -v cargo >/dev/null 2>&1; then
  report ok "cargo" "$(cargo --version 2>/dev/null)"
else
  report fail "cargo" "install: https://rustup.rs/"
fi

if command -v rustfmt >/dev/null 2>&1; then
  report ok "rustfmt" "$(rustfmt --version 2>/dev/null)"
else
  report warn "rustfmt" "run: rustup component add rustfmt"
fi

if command -v cargo-clippy >/dev/null 2>&1; then
  report ok "clippy" "$(cargo clippy --version 2>/dev/null)"
else
  report warn "clippy" "run: rustup component add clippy"
fi

echo
echo "project"
if [[ -f "$CRATE_DIR/Cargo.toml" ]]; then
  report ok "rust crate" "$CRATE_DIR"
else
  report fail "rust crate" "$CRATE_DIR/Cargo.toml is missing"
fi

if uv run python -c "import keep_or_nah_core" >/dev/null 2>&1; then
  version=$(uv run python -c "import keep_or_nah_core as k; print(k.version())" 2>/dev/null || echo "unknown")
  report ok "native module" "keep_or_nah_core $version"
else
  report warn "native module" "not built - run: scripts/agent/build.sh"
fi

if uv run python -c "import pytest" >/dev/null 2>&1; then
  report ok "pytest" "$(uv run python -c "import pytest; print(pytest.__version__)" 2>/dev/null)"
else
  report fail "pytest" "run: uv sync"
fi

if uv run python -c "import ruff" >/dev/null 2>&1 || uv run ruff --version >/dev/null 2>&1; then
  report ok "ruff" "$(uv run ruff --version 2>/dev/null)"
else
  report fail "ruff" "run: uv sync"
fi

echo
if [[ $failures -eq 0 ]]; then
  echo "environment is ready"
  exit 0
fi

echo "$failures blocking problem(s) found - fix the items marked [fail] above"
exit 1
