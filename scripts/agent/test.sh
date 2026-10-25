#!/usr/bin/env bash
#
# Agent hook: test.
#
# The canonical test command. This is the ONLY test command an agent should
# run, so that local runs and CI runs exercise the same thing.
#
# It runs the Rust unit suite and the Python suite. The native module is
# rebuilt first when it is missing, because a stale or absent native module
# makes the Python suite fail in ways that look like application bugs.
#
# Usage:
#   scripts/agent/test.sh          # Rust tests + Python tests
#   scripts/agent/test.sh --python # Python tests only
#   scripts/agent/test.sh --rust   # Rust tests only
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CRATE_DIR="crates/keep_or_nah_core"
TAURI_DIR="src-tauri"
FRONTEND_DIR="frontend"
run_rust=1
run_frontend=1

case "${1:-}" in
  --frontend) run_rust=0 ;;
  --rust) run_frontend=0 ;;
  "") ;;
  *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
esac

if [[ $run_rust -eq 1 ]]; then
  echo "=== rust core tests ==="
  cargo test --manifest-path "$CRATE_DIR/Cargo.toml"
  echo "=== tauri tests ==="
  cargo test --manifest-path "$TAURI_DIR/Cargo.toml"
fi

if [[ $run_frontend -eq 1 ]]; then
  echo "=== frontend tests ==="
  npm --prefix "$FRONTEND_DIR" test
fi
