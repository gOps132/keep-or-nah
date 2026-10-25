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
TAURI_DIR="src-tauri"
FRONTEND_DIR="frontend"
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

if command -v node >/dev/null 2>&1; then
  report ok "node" "$(node --version 2>/dev/null)"
else
  report fail "node" "install: https://nodejs.org/"
fi

if command -v npm >/dev/null 2>&1; then
  report ok "npm" "$(npm --version 2>/dev/null)"
else
  report fail "npm" "install: https://nodejs.org/"
fi

echo
echo "project"
if [[ -f "$CRATE_DIR/Cargo.toml" ]]; then
  report ok "rust core crate" "$CRATE_DIR"
else
  report fail "rust core crate" "$CRATE_DIR/Cargo.toml is missing"
fi

if [[ -f "$TAURI_DIR/Cargo.toml" ]]; then
  report ok "tauri app crate" "$TAURI_DIR"
else
  report fail "tauri app crate" "$TAURI_DIR/Cargo.toml is missing"
fi

if [[ -f "$FRONTEND_DIR/package.json" ]]; then
  report ok "frontend package" "$FRONTEND_DIR"
else
  report fail "frontend package" "$FRONTEND_DIR/package.json is missing"
fi

echo
if [[ $failures -eq 0 ]]; then
  echo "environment is ready"
  exit 0
fi

echo "$failures blocking problem(s) found - fix the items marked [fail] above"
exit 1
