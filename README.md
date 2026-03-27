# Keep or Nah

Simple desktop photo sorter.

The app works like a Tinder-style triage flow for images:
- choose a source folder full of photos
- send left to move or copy into a separate Nah folder
- send right to move or copy into a Keep folder
- move through photos quickly with a one-by-one decision flow

## Current Features

- CustomTkinter primary UI with automatic fallback to classic `tkinter` on older Tk builds.
- Source, Keep, and Nah folder pickers.
- Image preview with EXIF-aware rotation.
- Keyboard shortcuts: Left / `A` for Nah, Right / `D` for Keep.
- Move or copy mode for each decision.
- TkDnD-ready runtime base for future drag-and-drop support.
- `uv`-based dependency management.
- PyInstaller packaging for macOS `.app` and Windows `.exe`.
- A single build entrypoint at `scripts/build.py`.

## Setup

```bash
uv sync
```

## Run The App

```bash
uv run python main.py
```

## Build Packages

```bash
uv run python scripts/build.py --help
```

See [docs/BUILD.md](/Users/giancedrick/dev/projects/keep-or-nah/docs/BUILD.md) for macOS, Windows, and CrossOver build instructions.

See [docs/PLATFORM.md](/Users/giancedrick/dev/projects/keep-or-nah/docs/PLATFORM.md) for platform-specific runtime notes.
