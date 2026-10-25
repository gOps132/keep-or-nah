#!/usr/bin/env bash
#
# Agent hook: build.
#
# Builds the frontend assets and the native standalone desktop application.
#
# Usage:
#   scripts/agent/build.sh            # debug / standalone app build
#   scripts/agent/build.sh --release  # release package bundle
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "building frontend"
npm --prefix frontend run build

if [[ "${1:-}" == "--release" ]]; then
  echo "building release bundle"
  npx --prefix frontend tauri build
else
  echo "building standalone binary"
  npx --prefix frontend tauri build --no-bundle
fi
