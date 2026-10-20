#!/usr/bin/env bash
#
# The canonical verification gate for Keep or Nah.
#
# Every agent and every human must run this before claiming that work is
# complete. It is the single source of truth for "does this change pass?".
# CI calls this exact script so a local green run and a CI green run are
# byte-for-byte the same set of commands.
#
# Usage:
#   scripts/verify.sh              # full gate
#   scripts/verify.sh --fast       # skip the Rust stages and the native rebuild
#   scripts/verify.sh --stage NAME # run one stage (see STAGES below)
#   scripts/verify.sh --list       # list the stages
#
# Exit codes:
#   0  every stage passed
#   1  a stage failed
#   2  the script was misused (unknown stage, missing tool)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CRATE_DIR="crates/keep_or_nah_core"
FAST=0
ONLY_STAGE=""
LIST_ONLY=0

STAGES=(
  "doctor"
  "lint-python"
  "format-python"
  "format-rust"
  "lint-rust"
  "test-rust"
  "build"
  "test-python"
)

# Stages that `--fast` skips: the ones that need a Rust toolchain round trip.
FAST_SKIPPED=("format-rust" "lint-rust" "test-rust" "build")

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --stage) ONLY_STAGE="${2:-}"; shift 2 ;;
    --list) LIST_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $LIST_ONLY -eq 1 ]]; then
  printf '%s\n' "${STAGES[@]}"
  exit 0
fi

if [[ -n "$ONLY_STAGE" ]]; then
  known=0
  for stage in "${STAGES[@]}"; do
    [[ "$stage" == "$ONLY_STAGE" ]] && known=1
  done
  if [[ $known -eq 0 ]]; then
    echo "error: unknown stage '$ONLY_STAGE'" >&2
    echo "known stages: ${STAGES[*]}" >&2
    exit 2
  fi
  STAGES=("$ONLY_STAGE")
  FAST=0
fi

# --- output helpers -------------------------------------------------------

BOLD=""
RED=""
GREEN=""
YELLOW=""
RESET=""
if [[ -t 1 ]]; then
  BOLD="$(tput bold 2>/dev/null || true)"
  RED="$(tput setaf 1 2>/dev/null || true)"
  GREEN="$(tput setaf 2 2>/dev/null || true)"
  YELLOW="$(tput setaf 3 2>/dev/null || true)"
  RESET="$(tput sgr0 2>/dev/null || true)"
fi

CURRENT_STAGE=""
FAILURES=()

banner() {
  printf '\n%s=== %s ===%s\n' "$BOLD" "$1" "$RESET"
}

stage_begin() {
  CURRENT_STAGE="$1"
  banner "$1"
}

stage_skip() {
  printf '%s--- skipped: %s%s\n' "$YELLOW" "$1" "$RESET"
}

stage_fail() {
  FAILURES+=("$1")
  printf '%s!!! FAILED: %s%s\n' "$RED" "$1" "$RESET" >&2
}

should_run() {
  local candidate="$1"
  [[ $FAST -eq 1 ]] || return 0
  local skipped
  for skipped in "${FAST_SKIPPED[@]}"; do
    [[ "$skipped" == "$candidate" ]] && return 1
  done
  return 0
}

# --- stages ----------------------------------------------------------------

stage_doctor() {
  stage_begin "doctor"
  local problems=0

  if ! command -v uv >/dev/null 2>&1; then
    echo "missing: uv (https://docs.astral.sh/uv/)" >&2
    problems=1
  else
    echo "uv        $(uv --version 2>/dev/null || echo unknown)"
  fi

  if ! command -v cargo >/dev/null 2>&1; then
    echo "missing: cargo (https://rustup.rs/)" >&2
    problems=1
  else
    echo "cargo     $(cargo --version 2>/dev/null || echo unknown)"
  fi

  if [[ ! -f "$CRATE_DIR/Cargo.toml" ]]; then
    echo "missing: $CRATE_DIR/Cargo.toml" >&2
    problems=1
  fi

  if ! uv run python -c "import keep_or_nah_core" >/dev/null 2>&1; then
    echo "note: the native module is not built yet - run 'uv run maturin develop'" >&2
  else
    echo "native    keep_or_nah_core is importable"
  fi

  if [[ $problems -ne 0 ]]; then
    return 1
  fi
}

stage_lint_python() {
  stage_begin "lint-python"
  uv run ruff check .
}

stage_format_python() {
  stage_begin "format-python"
  uv run ruff format --check .
}

stage_format_rust() {
  stage_begin "format-rust"
  cargo fmt --manifest-path "$CRATE_DIR/Cargo.toml" --check
}

stage_lint_rust() {
  stage_begin "lint-rust"
  cargo clippy --manifest-path "$CRATE_DIR/Cargo.toml" --all-targets -- -D warnings
}

stage_test_rust() {
  stage_begin "test-rust"
  # The crate is built for CPython's stable ABI, so the test harness links
  # without libpython and needs no interpreter at all. PYO3_NO_PYTHON tells
  # PyO3 not to go looking for one. See ADR-0006.
  if ! PYO3_NO_PYTHON=1 cargo test --manifest-path "$CRATE_DIR/Cargo.toml" --no-default-features; then
    echo >&2
    echo "The Rust test suite could not run." >&2
    echo "If the failure is a link error mentioning __Py_ symbols, the crate" >&2
    echo "still hard-enables PyO3's extension-module feature. See issue #15." >&2
    return 1
  fi
}

stage_build() {
  stage_begin "build"
  uv run maturin develop --manifest-path "$CRATE_DIR/Cargo.toml"
}

stage_test_python() {
  stage_begin "test-python"
  uv run pytest -q
}

# --- runner ----------------------------------------------------------------

# Dispatch with a case statement rather than an associative array: macOS
# ships bash 3.2, which has no `declare -A`.
run_stage() {
  case "$1" in
    doctor) stage_doctor ;;
    lint-python) stage_lint_python ;;
    format-python) stage_format_python ;;
    format-rust) stage_format_rust ;;
    lint-rust) stage_lint_rust ;;
    test-rust) stage_test_rust ;;
    build) stage_build ;;
    test-python) stage_test_python ;;
    *) echo "error: no runner for stage '$1'" >&2; return 2 ;;
  esac
}

started_at=$(date +%s)

for stage in "${STAGES[@]}"; do
  if ! should_run "$stage"; then
    stage_skip "$stage (--fast)"
    continue
  fi
  if ! run_stage "$stage"; then
    stage_fail "$stage"
  fi
done

finished_at=$(date +%s)
elapsed=$(( finished_at - started_at ))

printf '\n%s=== summary ===%s\n' "$BOLD" "$RESET"
printf 'elapsed: %ds\n' "$elapsed"

if [[ ${#FAILURES[@]} -eq 0 ]]; then
  printf '%sALL STAGES PASSED%s\n' "$GREEN" "$RESET"
  exit 0
fi

printf '%s%d stage(s) failed:%s\n' "$RED" "${#FAILURES[@]}" "$RESET" >&2
for failure in "${FAILURES[@]}"; do
  printf '  - %s\n' "$failure" >&2
done
exit 1
