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
TAURI_DIR="src-tauri"
FRONTEND_DIR="frontend"

echo "=== rust format ==="
cargo fmt --manifest-path "$CRATE_DIR/Cargo.toml" --check
cargo fmt --manifest-path "$TAURI_DIR/Cargo.toml" --check

echo "=== rust clippy ==="
cargo clippy --manifest-path "$CRATE_DIR/Cargo.toml" --all-targets -- -D warnings
cargo clippy --manifest-path "$TAURI_DIR/Cargo.toml" --all-targets -- -D warnings

echo "=== frontend check ==="
npm --prefix "$FRONTEND_DIR" run build

echo "all lint checks passed"
