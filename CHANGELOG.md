# Changelog

All notable changes to Keep or Nah are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-10-21

The revamp, and the engineering process that keeps it honest.

### Added

- Deterministic verification gate: `scripts/verify.sh` with per-role hooks
  under `scripts/agent/` (`doctor`, `build`, `lint`, `test`, `verify`), and a
  pre-commit configuration that runs the staged-file subset of the same
  checks.
- Continuous integration: `.github/workflows/ci.yml` runs the lint, Rust, and
  Python test suites on Ubuntu, macOS, and Windows.
- Continuous delivery: `.github/workflows/release.yml` builds the macOS app
  bundle and the Windows executable from a `v*` tag and publishes them as a
  GitHub Release.
- Pinned Ruff configuration, so the lint gate does not drift when Ruff
  releases new default rules.
- Rust unit tests for the native core — 79 of them, up from 4 — and a
  `cargo test` mode that needs no Python installation at all.
- Documentation consistency tests that fail the build if the documentation
  describes a retired behaviour or drifts from the code.
- ADR-0005 (Staged Triage is the default) and ADR-0006 (the native core is
  built for CPython's stable ABI).

### Changed

- The GUI is a single CustomTkinter frontend. The `classic_gui.py` fallback
  was removed and the documentation updated to match.
- `gui_app.py` was decomposed into a `ui/` package: 2,119 lines became 330,
  with the widget tree still owned by a single `App`.
- `photo_session.py` was split: the session's forwarding accessors now live in
  `photo_session_properties.py`, keeping every domain module under the
  500-line architecture invariant.
- The native core is now built for CPython's stable ABI with a floor of 3.12.
  The published wheel is tagged `cp312-abi3` instead of `cp312-cp312`, which
  matches the application's own `requires-python`. See ADR-0006.
- Staged Triage is now the default interaction model rather than an opt-in.

### Fixed

- **The file identity could not tell a replaced file from the file it
  replaced on Linux.** The identity was the device and the inode, and Linux
  recycles inode numbers, so a file created at a path whose file was just
  unlinked could carry the inode of the file it replaced. The app could
  delete a file it did not own — the exact failure the Undo Journal exists
  to prevent. The identity now carries the size and the change time, which
  are not recycled. See ADR-0007.
- **The Rust crate never compiled on stable Windows.** The file index came
  from a nightly-only API. It now reads the volume serial number and the
  file index from the Windows API.
- **A staged file could never be flushed on Windows.** `sync_all` is
  `FlushFileBuffers` there, and it needs a handle that was opened for
  writing. Every staged file operation failed on Windows.
- **A session saved before the identity was extended lost its history on
  Windows.** The legacy record and the native identity are different
  numbers in different namespaces, and the legacy record is now verified in
  the namespace it was recorded in.
- `photo_session.py` referenced `Callable` and `threading` in annotations
  without importing them.
- The preview pipeline used bare `assert` statements for control flow, which
  disappear under `python -O`.
- Snapshot validators raised `ValueError` for type errors instead of
  `TypeError`.
- The review modal computed a `total_items` count that was never used.
- The crate could not be linted: `cargo fmt --check` and `cargo clippy` were
  both failing on the pre-existing code, invisibly, because the crate could
  not link.
- `.pytest_cache/` and `.ruff_cache/` were not in `.gitignore`. They did not
  show up in `git status` only because pytest and ruff each write a
  `.gitignore` inside their own cache directory — a convention, not a rule.
