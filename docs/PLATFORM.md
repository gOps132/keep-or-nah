# Platform Notes

## Runtime Requirements

- **Node.js 20+** and **npm** — required to build the React 19 + TypeScript frontend (`frontend/`).
- **The native Rust core** — `keep_or_nah_core` (`crates/keep_or_nah_core/`) is a pure Rust library crate linked directly into the Tauri v2 desktop binary (`src-tauri/`).
- **Rust toolchain** (`cargo`, `rustfmt`, `clippy`) — pinned in `rust-toolchain.toml` at the repository root and picked up automatically by `rustup`.

## macOS

- `Command` (`⌘`) is the modifier key for undo (`⌘Z`), batch review (`⌘↵`), and trackpad pinch/scroll zoom (`⌘ + wheel`).
- Debug timing logs (`KEEP_OR_NAH_DEBUG=1`) default to `~/Library/Application Support/keep-or-nah/render-log.jsonl` unless overridden via `KEEP_OR_NAH_DEBUG_LOG`.
- Hardware-accelerated RAW demosaicing uses native macOS CoreImage / ImageIO (`sips`) with fallback to embedded preview extraction.
- The open-source macOS app bundle (`Keep-or-Nah-macos-arm64.dmg`) is unsigned; run `xattr -cr /Applications/keep-or-nah.app` if quarantined by Gatekeeper.

## Windows

- `Control` (`Ctrl`) is the modifier key for undo (`Ctrl+Z`), batch review (`Ctrl+Enter`), and wheel zoom (`Ctrl + wheel`).
- Debug timing logs (`KEEP_OR_NAH_DEBUG=1`) default to `%APPDATA%\keep-or-nah\render-log.jsonl`.
- Packaged via Tauri v2 (`npm run build`) using Microsoft Edge WebView2.

## Linux

- `Control` (`Ctrl`) is the modifier key, matching the Windows bindings.
- Debug timing logs (`KEEP_OR_NAH_DEBUG=1`) default to `$XDG_CONFIG_HOME/keep-or-nah/render-log.jsonl` (or `~/.config/keep-or-nah/render-log.jsonl`).
- **Linux recycles inode numbers.** After a file is unlinked, the next file created at the same path can be handed the same inode number, so a `(device, inode)` pair does not by itself prove that a path still refers to the file it did a moment ago. The native core's 5-component file identity (ADR-0007) includes size and inode change time so a replaced file is always detected.
