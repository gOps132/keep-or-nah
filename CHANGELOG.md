# Changelog

All notable changes to Keep or Nah are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.1.0] - Unreleased

Initial release of the revamped application: Photo Groups, staged triage with
batch commit, split comparison, burst clustering, the native Rust core, and the
verified undo journal.
