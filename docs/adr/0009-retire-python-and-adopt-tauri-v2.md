# Retire Python/CustomTkinter Runtime and Adopt Tauri v2 Native Desktop

Supersedes ADR-0002 (`Consolidate Desktop GUI on CustomTkinter`) and ADR-0006 (`The Native Core Is Built for CPython's Stable ABI`).

Maintaining a dual-language Python + Rust (PyO3/Maturin) runtime introduced GIL contention on high-resolution preview rendering, PyInstaller packaging bloat, and unused Python GUI dependencies such as `tkinterdnd2-universal` (`hook-tkinterdnd2.py`). We decided to decommission the Python codebase completely, convert `keep_or_nah_core` into a pure Rust `rlib` crate, and build the desktop application on **Tauri v2** (`src-tauri/`) with a **React 19 + TypeScript** frontend (`frontend/`).

## Considered Options

- **Retain CustomTkinter + PyO3 (`abi3-py312`)**: Continues carrying the Python interpreter, CustomTkinter canvas limitations, and unused `tkinterdnd2-universal` PyInstaller hooks.
- **Rebuild on Tauri v2 + Pure Rust Core (Chosen)**: Links `keep_or_nah_core` directly into the Rust Tauri binary with zero FFI/GIL overhead, streams thumbnails and progressive 2-stage RAW renders over native Tauri IPC and `asset://` protocol, and handles folder drag-and-drop natively via Tauri window events (`tauri://drag-drop`).

## Consequences

- `pyproject.toml`, `gui_app.py`, `hook-tkinterdnd2.py`, and `packaging/*.spec` are retired and removed from the repository.
- Folder drag-and-drop is handled natively through Tauri's `tauri://drag-drop` event listener without third-party drag-and-drop wrappers.
- `scripts/verify.sh` verifies the pure Rust + TypeScript stack (`doctor`, `format-rust`, `lint-rust`, `test-rust`, `lint-frontend`, `test-frontend`, `build`).
