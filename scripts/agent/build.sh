#!/usr/bin/env bash
#
# Agent hook: build.
#
# Builds the native Rust core and installs it into the project virtualenv so
# `import keep_or_nah_core` resolves. Must run before the Python test suite.
#
# Usage:
#   scripts/agent/build.sh            # debug build (fast, used by the test hook)
#   scripts/agent/build.sh --release  # release build (used by packaging)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CRATE_DIR="crates/keep_or_nah_core"

maturin_args=(--manifest-path "$CRATE_DIR/Cargo.toml")
if [[ "${1:-}" == "--release" ]]; then
  maturin_args+=(--release)
fi

echo "building keep_or_nah_core"
uv run maturin develop "${maturin_args[@]}"

echo "verifying the native module imports"
uv run python -c "import keep_or_nah_core as k; print('keep_or_nah_core', k.version())"
