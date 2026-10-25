# Build Guide

This repo is a 100% Rust / Tauri desktop application.

## Requirements

- Node.js 20+
- A Rust toolchain (`cargo`)

## Verify before you build

`scripts/verify.sh` is the single verification gate for the repo. CI calls this
exact script, so a green local run and a green CI run execute byte-identical
commands.

```bash
scripts/verify.sh              # full gate
scripts/verify.sh --fast       # skip release packaging
scripts/verify.sh --list       # list the stages
```

The stages run in this order: `doctor`, `format-rust`, `lint-rust`, `test-rust`,
`lint-frontend`, `test-frontend`, `build`.

Per-role helpers live under `scripts/agent/`:

| Script | Purpose |
| --- | --- |
| `scripts/agent/doctor.sh` | Diagnose the local toolchain (`cargo`, `node`, `npm`, manifests). |
| `scripts/agent/lint.sh` | `cargo fmt --check`, `cargo clippy -D warnings`, and frontend build. |
| `scripts/agent/test.sh` | `cargo test` (core & tauri) and frontend Vitest suite. |
| `scripts/agent/build.sh` | Builds the standalone desktop executable. |

## Commands

### Install dependencies

```bash
npm --prefix frontend install
```

### Run in development mode

```bash
npm run dev
```

### Build standalone binary

```bash
npm run build:app
```

### Build installer bundle

```bash
npm run build
```

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request:

- `lint` — `cargo fmt --check`, `cargo clippy -D warnings`, and frontend typecheck.
- `test` — matrix across Ubuntu, macOS, and Windows running Rust tests, frontend tests, and standalone app compilation.
- `artifacts` — asserts the repository has picked up no stray build output.

Run the same checks locally before pushing:

```bash
scripts/verify.sh
```
