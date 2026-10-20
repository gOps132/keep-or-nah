# Platform Notes

## Runtime Requirements

- **Python 3.12 or 3.13** — `pyproject.toml` pins
  `requires-python = ">=3.12,<3.14"`.
- **Tk 8.6 or newer** — the GUI is built on CustomTkinter, and CustomTkinter is
  the only frontend. Check the linked Tk version with
  `python3 -c "import tkinter; print(tkinter.TkVersion)"`.
- **The native Rust core** — `keep_or_nah_core` is a compiled extension
  module. Packaged builds ship it inside the app; development builds install
  it with `uv run maturin develop`.
- **Rust toolchain** (`cargo`, `rustfmt`, `clippy`) — needed to build or test
  the native core, not to run an already packaged build. The version is
  pinned in `rust-toolchain.toml` at the repository root, and `rustup` picks
  it up automatically from the working directory. The pin exists for the same
  reason the Ruff configuration is pinned: clippy gains lints between
  releases, so an unpinned toolchain turns the lint gate into a moving
  target. Raising it is a deliberate act — change the channel, then fix
  whatever the new clippy finds.
- **`uv`** — the toolchain this repo manages its environment with.

## macOS

- `Command` is the modifier key for undo, zoom, and preview settings.
- Settings live in `~/Library/Application Support/keep-or-nah/settings.json`,
  and the session recovery file sits next to it as `session.json`.
- The macOS app bundle is unsigned.
- Some Python distributions ship without Tk. If `import tkinter` fails, install
  the Tk bindings for your interpreter (for example `python-tk` from Homebrew)
  before blaming the app.

## Windows

- `Control` is the modifier key for undo, zoom, and preview settings.
- Settings live in `%APPDATA%\keep-or-nah\settings.json`, with `session.json`
  next to it.
- Native Windows packaging is supported through `scripts/build.py windows`.
- CrossOver-based Windows packaging from macOS is also supported, but it
  requires a bottle with a working Windows Python installation. See
  [BUILD.md](BUILD.md).
- The atomic publish path hard-links the staged file into the destination. On
  Windows, where hard links are not always available, it renames the staged
  file into place instead.

## Linux

- `Control` is the modifier key, matching the Windows bindings.
- Settings live in `$XDG_CONFIG_HOME/keep-or-nah/settings.json` (default
  `~/.config/keep-or-nah/settings.json`), with `session.json` next to it.
- Mouse-wheel zoom binds the X11 `Button-4`/`Button-5` events.
- No packaging recipe ships for Linux. Run the app from source with
  `uv run python main.py`.
- **Linux recycles inode numbers.** After a file is unlinked, the next file
  created at the same path can be handed the same inode number, so a
  `(device, inode)` pair does not by itself prove that a path still refers to
  the file it did a moment ago. The native core's file identity includes
  information that is not recycled, so a replaced file is still detected
  here. This is the reason the file-identity tests run on Linux in CI rather
  than only on macOS.
