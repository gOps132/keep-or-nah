# UI/UX First-Time User Exploration Checklist

Every feature reachable from the UI must be exercised during a `@ui_ux_tester` session:

1. **First-Run Empty State**
   - Launch with sandboxed `HOME` and inspect the welcome card (`No Photo Session Loaded`, `Choose Photo Folder`, header `Open Folder`, and `Preferences` button).
   - Capture screenshot `01-opening.png`.
2. **Opening a Photo Session**
   - Load the sandboxed copy of the assigned directory (`~/Pictures/screenshots`).
   - Verify the header displays the folder path and Photo Group count badge.
   - Verify the Thumbnail Strip populates and highlights the active Photo Group.
3. **Single-View Inspection, Zoom, and Pan**
   - Inspect EXIF telemetry overlay, burst cluster badge (`B1`), and Best Shot badge (`★`).
   - Zoom in/out via zoom buttons, `wheel --cmd`, and reset to fit (`0`).
   - Drag on the zoomed canvas to pan.
   - If the Photo Group has multiple formats (e.g., `JPG` + `ARW`), click the format pills and press `V` to cycle formats; verify the RAW progressive status badge (`RAW (Embedded Preview)` -> `RAW (Full Render)`).
4. **Triage Decisions & Undo**
   - Stage **Keep** (`1` or HUD Keep button), **Nah** (`2` or HUD Nah button), and **Flag** (`F` or HUD Flag button).
   - Confirm decision badges appear on the Thumbnail Strip and staged counters update in the header.
   - Press `Cmd+Z` / click `Undo` and confirm the last decision is reverted and focus returns to that Photo Group.
5. **Split Comparison (`2-Up Compare`)**
   - Toggle `2-Up Compare` via header button or `C`.
   - Verify both panes render side by side with synchronized zoom and pan.
   - Press `X` (or click `Format Compare` / `Next Photo`) on a multi-format Photo Group to compare `JPG` vs `RAW` side by side.
6. **Preferences (`SettingsModal`)**
   - Open Preferences via the gear button (`settings-open-btn`).
   - Test switching `Default View Mode on Launch` (`1-Up Single` vs `2-Up Comparison`).
   - Test switching `Triage Mode` (`Staged Batch` vs `Immediate Mode`) and `Action Mode` (`Move from Source` vs `Copy`).
   - Test `Keep Folder`, `Nah Folder`, and `Flag Folder` destination pickers (`Choose` and `Clear`).
   - Verify pressing `F` in `Immediate Mode` without a Flag folder shows `"Choose a Flag folder before sorting."`, and succeeds once a Flag folder is chosen.
   - Test reordering `Representative Format Priority` up/down and clicking `Reset`.
   - Close with `Escape` and `Done`.
7. **Review & Batch Commit (`ReviewCommitModal`)**
   - Open via `Review Batch` button or `Cmd+Enter`.
   - Inspect Keep count, Nah count, Disk Reclaimed, and per-stem item breakdown.
   - Toggle `Move from Source` vs `Copy`.
   - Execute `Commit Staged Groups` and verify files are moved/copied inside the sandbox.
8. **Window Geometry & Edge Cases**
   - Resize window to `640x480`, `820x620`, `1180x820`, and `1600x1150`; check for clipped or overlapping labels.
   - Test an empty folder, a folder with a corrupt image file, and a file with a very long stem name.
9. **Render Timing Log Verification**
   - Inspect `$SANDBOX_DIR/render-log.jsonl` and confirm every render boundary (`render.preview.fast`, `render.preview.full`, `render.thumbnail_decode`, `render.thumbnail_strip`, `render.split_comparison`, `render.loading_overlay`) reports `duration_ms`.
