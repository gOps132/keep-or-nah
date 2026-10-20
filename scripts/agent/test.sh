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
run_rust=1
run_python=1

case "${1:-}" in
  --python) run_rust=0 ;;
  --rust) run_python=0 ;;
  "") ;;
  *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
esac

if [[ $run_rust -eq 1 ]]; then
  echo "=== rust tests ==="
  # The crate is built for CPython's stable ABI, so the test harness links
  # without libpython and needs no interpreter at all. See ADR-0006.
  PYO3_NO_PYTHON=1 cargo test --manifest-path "$CRATE_DIR/Cargo.toml" --no-default-features
fi

if [[ $run_python -eq 1 ]]; then
  if ! uv run python -c "import keep_or_nah_core" >/dev/null 2>&1; then
    echo "=== building the native module ==="
    scripts/agent/build.sh
  fi
  echo "=== python tests ==="
  uv run pytest -q
fi
