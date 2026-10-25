# Agent Pipeline

The contract every agent and every human follows to decide whether a change is
finished. It exists because this repository is a pure Rust core (`keep_or_nah_core`)
with a Tauri v2 desktop application and React/TypeScript frontend.

## The gate

`scripts/verify.sh` is the single source of truth. It runs these stages in
order and stops reporting at the end of the run so one invocation tells you
everything that is wrong.

| Stage | Command | What it proves |
| --- | --- | --- |
| `doctor` | `scripts/agent/doctor.sh` | the Rust toolchain, Node, and project manifests are present |
| `format-rust` | `cargo fmt --check` (core & tauri) | the Rust source is rustfmt-clean |
| `lint-rust` | `cargo clippy --all-targets -- -D warnings` | no clippy warnings |
| `test-rust` | `cargo test` (core & tauri) | the Rust core & desktop integration behave |
| `lint-frontend` | `npm --prefix frontend run build` | frontend TypeScript and assets compile cleanly |
| `test-frontend` | `npm --prefix frontend test` | frontend component & mock Tauri integration tests pass |
| `build` | `npx --prefix frontend tauri build --no-bundle` | the standalone desktop executable builds |

`--fast` skips `build` (release packaging). Use it while iterating; never use it as the evidence for a completion claim.

`--stage <name>` runs a single stage. `--list` prints the stage names.

## The file identity has five components, and the crate builds on stable Rust

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

An implementer does not edit `scripts/verify.sh` to make a check pass. If a check is wrong, that is a separate, deliberate change with its own ticket.

### Tester

The tester owns `scripts/agent/test.sh` and is the role that produces evidence.

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
pre-commit install
```

The pre-commit hooks run the staged-file subset of the same checks: `cargo fmt`
for core and tauri crates, and the artifact check. They are a fast local gate,
not a substitute for `scripts/verify.sh`.

The artifact check (`scripts/agent/check-artifacts.sh`) asserts that no tracked
file lives in a build or cache directory and that the ignore rules still cover
every artifact the project produces. It also runs as a CI job.

## Escalation

If a check cannot pass because the check itself is wrong — a lint rule that
contradicts the architecture, a test that asserts a behaviour the ADR
superseded, a build step that needs a machine-local dependency — then:

1. Do not weaken the check.
2. Open a ticket describing the conflict, referencing the ADR or the ADR that
   should be written.
3. Report the blocker with the command output that demonstrates it.

A blocked stage is a finding, not a nuisance to be routed around.
