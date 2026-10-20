#!/usr/bin/env bash
#
# Agent hook: lint.
#
# The canonical lint command. Runs every static check the project enforces:
# Python lint, Python format, Rust format, and Rust clippy.
#
# Usage: scripts/agent/lint.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CRATE_DIR="crates/keep_or_nah_core"

echo "=== python lint ==="
uv run ruff check .

echo "=== python format ==="
uv run ruff format --check .

echo "=== rust format ==="
cargo fmt --manifest-path "$CRATE_DIR/Cargo.toml" --check

echo "=== rust clippy ==="
cargo clippy --manifest-path "$CRATE_DIR/Cargo.toml" --all-targets -- -D warnings

echo "all lint checks passed"
