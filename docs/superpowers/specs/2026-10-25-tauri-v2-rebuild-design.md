# Rebuild GUI on Tauri v2 with Native macOS & Windows Design

## Goal

Replace the CustomTkinter GUI with a modern, high-performance desktop application built on **Tauri v2** that directly integrates the existing Rust core (`keep_or_nah_core`). Deliver a custom, beautifully designed, professional macOS-native interface (vibrancy, dark studio canvas, floating glass action HUD, SF Pro typography) that also adapts seamlessly to Windows 11/10 (Mica/Acrylic, native caption buttons, Edge WebView2), packaged as a single lightweight binary (~15MB) with zero Python or PyInstaller runtime dependencies.

## Architecture and Bridge

- **Tauri v2 Workspace**: Add `src-tauri` at the repository root, configured with `tauri = "2.0"` and directly referencing the workspace crate `keep_or_nah_core`.
- **Rust Core Reuse**: Keep 100% of the existing 3,742 LOC in `crates/keep_or_nah_core` (directory scan and atomic same-stem grouping, SIMD Lanczos3 image resize, Laplacian variance sharpness analysis, difference perceptual hash, and atomic file move/copy operations with transactional undo journal).
- **Type-Safe Tauri IPC**: Define Tauri commands (`#[tauri::command]`) for session initialization, triage staging, batch commits, undo, and settings. Generate TypeScript type definitions from Rust models using `ts-rs` or `specta` to enforce type safety across the IPC boundary.
- **Async Streaming & Preview Protocol**:
  - Background directory scans and thumbnail decodes stream progress and items to the frontend over Tauri events (`app_handle.emit`).
  - Previews are served via a custom local asset protocol (e.g., `app-preview://`) backed by the Rust memory cache, delivering raw decoded image buffers directly to the canvas without Base64 serialization overhead.

## Visual Design System & Styling

- **Palette**: Dark studio workspace (`#0c0c0e` canvas, `#141417` toolbars/panels, `#1e1e23` subtle borders) preserving photographic color fidelity. Semantic accents: Keep (`#16a34a`), Nah (`#dc2626`), Flag (`#d97706`), Selection (`#3b82f6`).
- **Typography**: macOS system hierarchy (`SF Pro Text` 13px UI, `SF Pro Display` 16px headers, `SF Mono` 11px EXIF telemetry). Automatically resolves to `Segoe UI Variable` / `Cascadia Code` on Windows (or bundled `Inter`).
- **Window Chrome**:
  - macOS: `titleBarStyle: "Overlay"` with NSWindow vibrancy blur under the unified header bar and traffic lights.
  - Windows: Native caption buttons (minimize, maximize, close) in top-right with Windows 11 Mica / Acrylic effects.
- **Tactile Action HUD**: A floating frosted glass pill (`backdrop-filter: blur(20px)`) resting above the photo canvas with spring press micro-interactions (`active:scale-95`) and embedded shortcut tags (<kbd>1</kbd> Keep, <kbd>2</kbd> Nah, <kbd>F</kbd> Flag).
- **Segmented Controls**: Recessed pill tracks with sliding active indicators for `1-Up` / `2-Up Compare` and `Move` / `Copy`.
- **Thumbnail Strip**: Horizontal virtualized strip with 4px rounded cards, 2px blue selection ring, burst cluster tags, Best Shot star badge (★), and staged decision check/cross badges.
- **Canvas Viewport**: Hardware-accelerated WebGL / HTML5 2D canvas supporting buttery 60fps pan, trackpad pinch-to-zoom (`⌘ + wheel` / `Ctrl + wheel`), and synchronized split-comparison view.
- **Review & Commit Modal**: Centered modal sheet with frosted dark glass backdrop, summary chips (space reclaimed, file counts), collapsible operation breakdown, and atomic commit confirmation.

## Session State, Staged Triage, and Undo

- **State Ownership**: Session state (queue of `PhotoGroup`s, active index, staged triage map, view filter extensions, undo journal pointer) is owned by the Rust backend in `src-tauri` using thread-safe state (`tauri::State<Mutex<PhotoSession>>`).
- **Staged Triage**: Decisions (Keep, Nah, Flag) are recorded in-memory without disk modifications. The UI updates instantaneously with optimistic badge updates.
- **Batch Commit**: Invoking `commit_batch` triggers the Rust core atomic file coordinator. On any error, completed operations roll back automatically, and failures are surfaced to the UI.
- **Undo**: Invoking `undo` triggers the Rust core transactional undo journal, reversing the last executed file operation and restoring previous state.

## Error Handling

- **Missing Files**: Files removed or modified by external tools before a batch commit trigger a preflight failure that halts execution and warns the user without corrupting the session.
- **Corrupt / Unsupported Images**: Renders a clean "Preview unavailable" state card while leaving sorting and navigation controls fully operable.
- **Rollback Failures**: If transactional rollback encounters unexpected I/O barriers, an emergency recovery journal is written to disk and presented in a detailed dialog.

## Tests & Verification

- **Rust Unit Tests**: Verify Tauri command handlers, session state transitions, and IPC serialization using standard `cargo test`.
- **Frontend Component Tests**: Vitest + Testing Library verifying HUD interactions, keyboard shortcuts, thumbnail selection, and staged badges.
- **E2E Smoke Verification**: Automated Tauri WebDriver / Playwright flow launching the packaged app, opening a mock photo folder, staging decisions, and verifying atomic batch commit.
- **Continuous Integration**: Build and verify single-binary artifacts on macOS and Windows in GitHub Actions.
