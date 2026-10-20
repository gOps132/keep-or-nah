#!/usr/bin/env bash
#
# Agent hook: verify.
#
# Thin wrapper around the canonical gate so that every role has a stable
# entrypoint. The full stage list lives in scripts/verify.sh - this script
# exists so the agent pipeline has one command per role and one command total.
#
# Usage:
#   scripts/agent/verify.sh          # full gate
#   scripts/agent/verify.sh --fast   # skip the Rust stages and the native rebuild
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

exec "$REPO_ROOT/scripts/verify.sh" "$@"
