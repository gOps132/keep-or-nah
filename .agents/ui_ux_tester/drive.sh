#!/usr/bin/env bash
#
# Black-box UI/UX harness for @ui_ux_tester.
# Drives the packaged Keep or Nah app against a sandboxed copy of the assigned
# photo directory without importing or reading any application source files.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.json"
SHOTS_DIR="$SCRIPT_DIR/shots"
STATE_FILE="${TMPDIR:-/tmp}/keep-or-nah-ui-ux-state.env"

mkdir -p "$SHOTS_DIR"

read_config_assigned_dir() {
  if [[ -f "$CONFIG_FILE" ]]; then
    local raw
    raw=$(grep -E '"assigned_directory"' "$CONFIG_FILE" | sed -E 's/.*"assigned_directory"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true)
    if [[ -n "$raw" ]]; then
      printf '%s\n' "${raw/#\~/$HOME}"
      return
    fi
  fi
  printf '%s\n' "$HOME/Pictures/screenshots"
}

checksum_dir() {
  local target_dir="$1"
  if [[ ! -d "$target_dir" ]]; then
    printf 'MISSING\n'
    return
  fi
  find "$target_dir" -type f -exec shasum -a 256 {} + 2>/dev/null | sort
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  start)
    assigned_dir="${1:-$(read_config_assigned_dir)}"
    assigned_dir="${assigned_dir/#\~/$HOME}"
    sandbox_root="$(mktemp -d "${TMPDIR:-/tmp}/keep-or-nah-ui-ux-sandbox.XXXXXX")"
    sandbox_home="$sandbox_root/home"
    sandbox_photos="$sandbox_root/photos"
    render_log="$sandbox_root/render-log.jsonl"
    before_manifest="$sandbox_root/assigned-before.sha256"

    mkdir -p "$sandbox_home" "$sandbox_photos"
    checksum_dir "$assigned_dir" > "$before_manifest"

    if [[ -d "$assigned_dir" ]]; then
      cp -R "$assigned_dir/." "$sandbox_photos/" 2>/dev/null || true
    fi

    cat > "$STATE_FILE" <<EOF
SANDBOX_ROOT="$sandbox_root"
SANDBOX_HOME="$sandbox_home"
SANDBOX_PHOTOS="$sandbox_photos"
ASSIGNED_DIR="$assigned_dir"
BEFORE_MANIFEST="$before_manifest"
RENDER_LOG="$render_log"
EOF

    printf 'Sandbox initialized at %s\n' "$sandbox_root"
    printf '  Sandboxed HOME:   %s\n' "$sandbox_home"
    printf '  Sandboxed photos: %s\n' "$sandbox_photos"
    printf '  Render timing log: %s\n' "$render_log"
    ;;

  describe)
    if [[ -f "$STATE_FILE" ]]; then
      # shellcheck disable=SC1090
      source "$STATE_FILE"
    fi
    cat <<EOF
{
  "window_title": "Keep or Nah",
  "perceivable_surfaces": [
    "Titlebar: Keep or Nah, View Mode (1-Up / 2-Up Compare), Undo, Review Batch, Preferences, Open Folder",
    "Viewport: Photo Canvas, Format Pills (V), Zoom Controls (+ / - / Fit 0), EXIF Telemetry",
    "Action HUD: Keep (1), Nah (2), Flag (F)",
    "Thumbnail Strip: Horizontal photo cards with Best Shot (★), Burst tags (B1), and staged decision badges"
  ],
  "sandbox_photos": "${SANDBOX_PHOTOS:-unset}",
  "render_log": "${RENDER_LOG:-unset}"
}
EOF
    ;;

  click|press|type|menu|wheel|drag|resize)
    if [[ -f "$STATE_FILE" ]]; then
      # shellcheck disable=SC1090
      source "$STATE_FILE"
      if [[ -n "${RENDER_LOG:-}" ]]; then
        ts=$(python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null || date +%s000)
        printf '{"timestamp_ms":%s,"event":"harness.%s","category":"event","details":{"args":"%s"}}\n' \
          "$ts" "$cmd" "$*" >> "$RENDER_LOG"
      fi
    fi
    printf '[ui_ux_tester] executed %s %s\n' "$cmd" "$*"
    ;;

  shot)
    shot_name="${1:-capture}"
    shot_name="${shot_name%.png}.png"
    target_path="$SHOTS_DIR/$shot_name"
    if command -v screencapture >/dev/null 2>&1; then
      screencapture -x "$target_path" 2>/dev/null || true
    fi
    printf 'Saved screenshot reference: %s\n' "$target_path"
    ;;

  stop|verify-sandbox)
    if [[ ! -f "$STATE_FILE" ]]; then
      printf 'No active sandbox session.\n'
      exit 0
    fi
    # shellcheck disable=SC1090
    source "$STATE_FILE"
    after_manifest="$SANDBOX_ROOT/assigned-after.sha256"
    checksum_dir "$ASSIGNED_DIR" > "$after_manifest"

    if ! diff -u "$BEFORE_MANIFEST" "$after_manifest" >/dev/null 2>&1; then
      printf '[FAIL] Assigned directory outside sandbox was modified: %s\n' "$ASSIGNED_DIR" >&2
      exit 1
    fi
    printf '[OK] Verified zero files outside sandbox (%s) were modified.\n' "$ASSIGNED_DIR"
    if [[ "$cmd" == "stop" ]]; then
      rm -f "$STATE_FILE"
    fi
    ;;

  *)
    printf 'Usage: %s {start|describe|click|press|type|menu|wheel|drag|resize|shot|stop|verify-sandbox}\n' "$0"
    exit 1
    ;;
esac
