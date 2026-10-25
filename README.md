# Keep or Nah

Desktop photo triage application for photographers. Load a folder of photos,
then review, compare, and organize one **Photo Session** at a time.

A **Photo Group** is every file in the source folder that shares the exact same
filename stem — a RAW, its JPEG, and its XMP sidecar are one unit and are never
separated. One file in the group, the **Representative**, renders the preview
and the thumbnail.

## Current Features

- **Photo Groups** — same-stem files are grouped atomically during the native
  directory scan, and a group is always triaged, moved, and reversed as a
  whole.
- **Representative** — the best previewable member of a Photo Group drives the
  preview and the thumbnail.
- **Triage** — every Photo Group gets a **Keep**, **Nah**, or **Flag** decision.
  Keep and Nah send the group's files to their destination folders; Flag sets
  the group aside for later re-examination.
- **Action Mode** — a segmented control switches between moving files out of
  the source folder and copying them.
- **Staged Triage** — decisions are recorded in memory as **Staged
  Decisions** instead of touching the filesystem. This is the default; the
  View menu and the settings dialog switch to immediate mode, and the choice
  persists. A staged Photo Group stays on the Thumbnail Strip with a badge
  that says which decision it carries. The **Review Batch** button shows how
  many are outstanding, and the review modal lists every Staged Decision with
  its size alongside the Keep, Nah, and total counts and the disk space
  reclaimed, before anything is executed.
- **Batch Commit** — all Staged Decisions are executed together from the review
  modal, with automatic rollback if any part of the batch fails.
- **Split Comparison** — a 2-up view of two Photo Groups with synchronized zoom
  and pan, for judging near-identical frames. `1` and `2` triage the left or
  the right photo in one keystroke.
- **Burst Clustering** — photos taken in rapid succession are grouped into a
  **Burst Cluster** using timestamp proximity and perceptual difference
  hashing. The sharpest frame is the **Best Shot**, chosen by Laplacian
  variance sharpness analysis, and it is badged in the **Thumbnail Strip**.
- **Undo Journal** — every executed file operation is written to a persistent,
  transactional record. Undo reverses the last action and verifies file
  identity before it touches anything.
- **Thumbnail Strip** — asynchronously decoded thumbnails of the Photo Groups
  in the active Photo Session, with a selection indicator, the Best Shot
  badge, and a badge for the Staged Decision of a decided Photo Group.
- **Native Rust core** (`keep_or_nah_core`) handles
  directory scanning, same-stem grouping, SIMD Lanczos3 thumbnail generation,
  EXIF-aware preview rendering, atomic file operations, sharpness scoring, and
  perceptual hashing.
- **Tauri Desktop Application** — high-performance native Rust desktop backend
  with React + TypeScript frontend, hardware-accelerated rendering, and
  consistent cross-platform keyboard shortcuts.
- **Session recovery** — the active Photo Session, including Staged Decisions
  and the Undo Journal, is written to disk and restored on the next launch.

## Setup

Requires Node.js 20+ and a Rust toolchain (`cargo`).

```bash
npm --prefix frontend install
```

## Run the App

```bash
npm run dev
```

## Test and Verify

`scripts/verify.sh` is the single verification gate. CI calls the same script,
so a green local run and a green CI run execute identical commands.

```bash
scripts/verify.sh            # full gate
scripts/verify.sh --fast     # skip release desktop packaging
```

Per-role helpers live under `scripts/agent/`:

```bash
scripts/agent/doctor.sh      # diagnose the local toolchain
scripts/agent/lint.sh        # cargo fmt, cargo clippy, frontend check
scripts/agent/test.sh        # Rust core & Tauri tests + frontend Vitest suite
scripts/agent/build.sh       # build standalone desktop application
```

To run only the frontend Vitest suite:

```bash
npm --prefix frontend test
```

## Keyboard Shortcuts

| Key | Action |
| --- | --- |
| `Left` | Previous Photo Group |
| `Right` | Next Photo Group |
| `A` | Nah |
| `D` | Keep |
| `F` | Flag |
| `Space` | Keep |
| `Del` | Nah |
| `C` | Toggle Split Comparison |
| `1` | Split Comparison: keep the left photo, the right one becomes Nah |
| `2` | Split Comparison: keep the right photo, the left one becomes Nah |
| `Cmd+Z` (`Ctrl+Z` elsewhere) | Undo the last action through the Undo Journal |
| `Cmd+-` / `Ctrl+-` | Zoom out |
| `Cmd+=` / `Ctrl+=` | Zoom in |
| `Cmd+0` / `Ctrl+0` | Reset zoom to fit |
| `Cmd+,` / `Ctrl+,` | Preview settings |

The triage keys behave identically in Staged Triage mode, where they record a
Staged Decision instead of writing to disk, and in immediate mode, where they
write to disk directly. Shortcuts are ignored while a text entry has focus.

## Build Application

```bash
npm run build:app
```
