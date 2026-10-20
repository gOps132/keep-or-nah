# Agent Pipeline

The contract every agent and every human follows to decide whether a change is
finished. It exists because this repository has a native Rust core, a Python
GUI, and a Python test suite that depends on the compiled native module — a
change can be green in one language and broken in the other.

## The gate

`scripts/verify.sh` is the single source of truth. It runs these stages in
order and stops reporting at the end of the run so one invocation tells you
everything that is wrong.

| Stage | Command | What it proves |
| --- | --- | --- |
| `doctor` | `scripts/agent/doctor.sh` | the toolchain is present and the native module imports |
| `lint-python` | `uv run ruff check .` | no lint findings against the pinned rule set |
| `format-python` | `uv run ruff format --check .` | formatting matches the pinned style |
| `format-rust` | `cargo fmt --check` | the Rust source is rustfmt-clean |
| `lint-rust` | `cargo clippy --all-targets -- -D warnings` | no clippy warnings |
| `test-rust` | `PYO3_NO_PYTHON=1 cargo test --no-default-features` | the Rust core behaves |
| `build` | `uv run maturin develop` | the native module compiles and installs |
| `test-python` | `uv run pytest -q` | the application behaves |

`--fast` skips `format-rust`, `lint-rust`, `test-rust`, and `build`. Use it
while iterating; never use it as the evidence for a completion claim.

`--stage <name>` runs a single stage. `--list` prints the stage names.

## Why the Rust tests need no Python

The crate is a PyO3 extension module, so its `Cargo.toml` enables PyO3's
`extension-module` feature. That feature tells the linker to leave the
CPython symbols unresolved, which is correct for shipping a shared library and
wrong for the test harness — the harness cannot link, and the error is a wall
of `undefined symbols: __Py_FalseStruct`.

The crate is also built for CPython's stable ABI (ADR-0006), so PyO3 does not
need an interpreter at all. The test command is:

```
PYO3_NO_PYTHON=1 cargo test --no-default-features
```

`--no-default-features` turns the crate's `extension-module` feature off, and
`PYO3_NO_PYTHON=1` tells PyO3 not to go looking for an interpreter. The test
binary therefore links with no libpython and no development headers, and the
Rust suite runs on a machine that has never had Python installed.

Two mechanisms make this work, and both are easy to break by accident:

- **`extension-module` has to be a cargo feature, not a hard-coded dependency
  feature.** It lives in `[features]` with `default = ["extension-module"]`, so
  `--no-default-features` can turn it off. A `[dev-dependencies]` entry on
  `pyo3` with `extension-module` is what lets the *test* target link without
  libpython: Cargo unifies the two for the test target only, and the release
  build maturin drives never sees the dev-dependency.
- **The crate needs a `build.rs` that adds `-undefined dynamic_lookup` for
  `cdylib` targets on macOS.** A Python extension module leaves the CPython
  symbols unresolved for the host interpreter to provide, and the macOS linker
  refuses to produce such an object by default. Maturin passes these flags
  itself; the build script makes a plain `cargo build` produce the same kind
  of object instead of failing with `undefined symbols: __Py_FalseStruct`.

Maturin enables a crate feature named `extension-module` automatically, so
the packaging path needs no extra configuration.

### The abi3 floor is linked to the project's minimum Python

The crate uses `abi3-py312`. The floor is not arbitrary: the wheel tag
`cp312-abi3` has to agree with the application's `requires-python =
">=3.12,<3.14"`. Raising the project's minimum Python means raising the abi3
floor with it. A mismatch is a packaging bug, not a cosmetic difference —
the artifact would claim compatibility with interpreters the project has
never been tested against.

### The file identity has five components, and the crate builds on stable Rust

The native core refuses to remove a file that no longer owns the identity it
recorded for it. That identity is the device, the inode, the size, and the
change time of the inode (ADR-0007). The device and the inode alone are not
enough: filesystems recycle inode numbers, so a replacement can carry the
inode of the file it replaced.

Two things about it are easy to break by accident:

- **A recorded identity is compared on the components it records.** A session
  saved before the identity was extended records the device and the inode
  only, and it is verified under exactly the guarantee it was recorded under.
  Do not reject a legacy record, and do not compare components the record
  does not carry: a photographer's pending session must not be discarded over
  the shape of its own record.
- **The crate builds on stable Rust on every platform, including Windows.**
  The Windows identity needs the volume serial number and the 64-bit file
  index, which the stable `std::os::windows::fs::MetadataExt` cannot read:
  those methods are still behind the unstable `windows_by_handle` feature.
  The crate asks the Windows API for them through the Windows-only
  `windows-sys` dependency. A platform-specific code path that is never
  compiled is a code path that is broken: check it with
  `cargo check --target x86_64-pc-windows-msvc` before claiming it works.

The change time of an inode moves when the application publishes a file,
because publishing changes the link count of the inode. The identity of a
published file is therefore read after the publication is complete, and the
components a publication cannot change decide whether a path still holds the
file that was published.

## Roles

### Implementer

1. Read the ticket. Confirm the ticket number and that it is unblocked.
2. Read `CONTEXT.md` and the relevant ADRs before touching code.
3. Write the change, and a test that would fail without it.
4. Run `scripts/agent/lint.sh` and `scripts/agent/test.sh`.
5. Hand off with the command output as evidence.

An implementer does not edit `scripts/verify.sh`, `.pre-commit-config.yaml`,
or the Ruff configuration to make a check pass. If a check is wrong, that is a
separate, deliberate change with its own ticket.

### Tester

The tester owns `scripts/agent/test.sh` and is the role that produces
evidence.

- Run the suite. Read the whole output. Count the passes and the failures.
- A red-green cycle for a regression test means: run it and watch it fail,
  apply the fix, run it again and watch it pass, then revert the fix and
  watch it fail again. A test that has only ever passed proves nothing.
- Report the exact commands and their real output. Never summarize a run you
  did not execute.
- The tester does not edit production code to make a test pass. When a test
  fails, the tester reports the failure and the evidence.

### Reviewer

1. Run `scripts/agent/verify.sh` in full, with no `--fast`.
2. Read the diff, not the summary.
3. Check the change against the ticket's acceptance criteria, one by one.
4. Check that the change does not silently alter behaviour. A refactor ticket
   that changes behaviour is a scope violation.
5. Check the domain vocabulary: does the change use the terms in
   `CONTEXT.md`, and does it avoid the terms the glossary forbids?

A reviewer who has not seen the gate pass does not approve.

## Pre-commit

```bash
uv run pre-commit install
```

The pre-commit hooks run the staged-file subset of the same checks: Ruff lint
and format, `cargo fmt`, the architecture-invariant test, and the artifact
check. They are a fast local gate, not a substitute for `scripts/verify.sh`.

The artifact check (`scripts/agent/check-artifacts.sh`) asserts that no tracked
file lives in a build or cache directory and that the ignore rules still cover
every artifact the project produces. It also runs as a CI job and as a pytest
case, so a hygiene regression fails the build even without the hook.

## The Rust configuration is pinned on purpose

Ruff's implicit default rule set changes between releases. In Ruff 0.17 it
enabled 409 rules and produced 165 findings that had never been triaged. If
the rule set is not committed, the lint gate is a moving target: a green run
on one machine fails on another after a dependency bump, and no one can tell
whether the code regressed or the linter did.

`[tool.ruff]` in `pyproject.toml` pins `select` explicitly and lists every
ignored rule with the reason it is ignored. Adding a rule is a deliberate act
that shows up in the diff.

## Escalation

If a check cannot pass because the check itself is wrong — a lint rule that
contradicts the architecture, a test that asserts a behaviour the ADR
superseded, a build step that needs a machine-local dependency — then:

1. Do not weaken the check.
2. Open a ticket describing the conflict, referencing the ADR or the ADR that
   should be written.
3. Report the blocker with the command output that demonstrates it.

A blocked stage is a finding, not a nuisance to be routed around.
