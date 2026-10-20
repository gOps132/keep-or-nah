# Build Guide

This repo uses `uv` for local environment management and `scripts/build.py` as the packaging entrypoint.

## Requirements

- `uv`
- Python 3.12 or 3.13
- A Rust toolchain (`cargo`, `maturin`) — the native core `keep_or_nah_core`
  lives in `crates/keep_or_nah_core` and is compiled with maturin through
  PyO3.

## Verify before you build

`scripts/verify.sh` is the single verification gate for the repo. CI calls this
exact script, so a green local run and a green CI run execute byte-identical
commands.

```bash
scripts/verify.sh              # full gate
scripts/verify.sh --fast       # skip the Rust stages and the native rebuild
scripts/verify.sh --list       # list the stages
scripts/verify.sh --stage test-python
```

The stages run in this order: `doctor`, `lint-python`, `format-python`,
`format-rust`, `lint-rust`, `test-rust`, `build`, `test-python`. The script
prints a banner per stage, keeps going after a failure, and exits non-zero if
any stage failed.

Per-role helpers live under `scripts/agent/`:

| Script | Purpose |
| --- | --- |
| `scripts/agent/doctor.sh` | Diagnose the local toolchain (missing `uv`, missing `cargo`, unbuilt native module) and report the fix for each item. |
| `scripts/agent/lint.sh` | `ruff check`, `ruff format --check`, `cargo fmt --check`, and `cargo clippy -D warnings`. |
| `scripts/agent/test.sh` | The canonical test command: the Rust test suite and the Python test suite. `--python` and `--rust` narrow it to one of them. |
| `scripts/agent/build.sh` | Builds the native core with `maturin develop` and verifies the import. `--release` produces a release build. |

## Commands

### Sync the local environment

```bash
uv sync
```

### Build the native core

```bash
uv run maturin develop
```

### macOS `.app`

```bash
uv run python scripts/build.py macos
```

Choose a specific interpreter if needed:

```bash
uv run python scripts/build.py macos --python /path/to/python3.12
```

Output:

```bash
dist/macos/Keep or Nah.app
```

The macOS app is unsigned.

### Windows `.exe` on Windows

Run this on a real Windows machine:

```bash
uv run python scripts/build.py windows
```

Or choose a specific interpreter:

```bash
uv run python scripts/build.py windows --python C:\path\to\python.exe
```

Output:

```bash
dist/windows/KeepOrNah.exe
```

### Windows `.exe` from macOS via CrossOver

On macOS, the Windows build runs inside a CrossOver bottle:

```bash
uv run python scripts/build.py windows --cx-bottle your-bottle-name
```

If the bottle does not expose Python on PATH, confirm the exact Windows path to
the interpreter and pass the complete path with `--win-python`:

```bash
uv run python scripts/build.py windows \
  --cx-bottle your-bottle-name \
  --win-python "C:\users\crossover\AppData\Local\Programs\Python\Python312\python.exe"
```

Do not assume `python.exe` is discoverable by name inside the bottle. Confirm
the interpreter location first.

### Build both from macOS

```bash
uv run python scripts/build.py all --cx-bottle your-bottle-name
```

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request. It installs the
Python toolchain with `uv` and the Rust toolchain with
`dtolnay/rust-toolchain`, caches the `uv` and `cargo` dependency trees, and
runs the same checks as the local gate:

- `lint` — `ruff check`, `ruff format --check`, `cargo fmt --check`, and
  `cargo clippy -D warnings`.
- `rust` — runs the Rust test suite in a link-safe mode.
- `test` — builds the native module with `maturin develop` and runs the full
  `pytest` suite. It runs on Ubuntu, macOS, and Windows, plus Ubuntu on Python
  3.13, so the desktop platforms the app actually ships to are covered.
- `artifacts` — asserts the repository has picked up no stray build output.

Every job carries a `timeout-minutes` budget, and no stage is allowed to fail
quietly: there is no `continue-on-error` on the lint or test stages.

The status checks to require in branch protection are `lint`, `rust`, and
each `test (<os>, python <version>)` leg of the matrix.

Run the same checks locally before pushing:

```bash
scripts/verify.sh
```

## Release

`.github/workflows/release.yml` turns a version tag into a downloadable GitHub
Release. It triggers only on `v*` tags and:

- builds the macOS `.app` bundle on a macOS runner with
  `uv run python scripts/build.py macos`;
- builds the Windows `.exe` on a Windows runner with
  `uv run python scripts/build.py windows`;
- compiles `keep_or_nah_core` in release mode, so the native module is bundled
  into both artifacts;
- uploads the artifacts and attaches them to a GitHub Release created from the
  tag, with release notes generated from the commits since the previous tag and
  `CHANGELOG.md` updated alongside them.

The macOS bundle is unsigned. State that in the release notes instead of
publishing an unnotified unsigned binary.

To rehearse a release locally, run the same build commands the workflow runs:

```bash
uv run python scripts/build.py macos
uv run python scripts/build.py windows
```

## Notes

- `packaging/macos.spec` builds the macOS app bundle.
- `packaging/windows.spec` builds the Windows single-file executable.
- `hook-tkinterdnd2.py` is included so the TkDnD runtime files are bundled.
- Build outputs are written under `dist/`.
- Intermediate files are written under `build/`.
- PyInstaller cache is written under `.pyinstaller/`.
