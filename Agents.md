# Agent Guidelines

- Use conventional commits style commit.

## Agent skills

### Issue tracker

GitHub issues. See `docs/agents/issue-tracker.md`.

### Feature tickets

No ticket, no feature. See `docs/agents/feature-tickets.md`.

### Triage labels

Default triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`CONTEXT.md` and `docs/adr/` at the repo root). See `docs/agents/domain.md`.

### Two-axis code review

Standards and Spec reviews run in parallel before merging to `main`. See `.agents/skills/code-review/SKILL.md`.

## Verification pipeline

**Nothing is done until `scripts/verify.sh` passes.** See `docs/agents/pipeline.md`
for the full contract.

```bash
scripts/verify.sh          # the canonical gate: lint, format, rust tests, build, python tests
scripts/verify.sh --fast   # skip the rust stages and the native rebuild
scripts/verify.sh --list   # list the stages
```

Per-role hooks, one command per role:

| Hook | Command | Owner |
| --- | --- | --- |
| Doctor | `scripts/agent/doctor.sh` | any role, first thing on a new machine |
| Build | `scripts/agent/build.sh` | implementer, tester |
| Lint | `scripts/agent/lint.sh` | implementer, reviewer |
| Test | `scripts/agent/test.sh` | tester |
| Verify | `scripts/agent/verify.sh` | reviewer, and every role before claiming completion |
| Artifacts | `scripts/agent/check-artifacts.sh` | reviewer, and the pre-commit hook |

### Roles

- **Implementer** — writes the code. Runs `scripts/agent/lint.sh` and
  `scripts/agent/test.sh` before handing off. Does not edit the verification
  scripts to make a failing check pass.
- **Tester** — owns `scripts/agent/test.sh`. Produces evidence: the exact
  commands run and their real output. Never edits production code to make a
  test pass; reports the failure instead.
- **Reviewer** — runs `scripts/agent/verify.sh` in full, executes the two-axis
  code review (Standards + Spec), reads the diff, and checks the change
  against the ticket's acceptance criteria. A reviewer who has not seen the
  gate pass does not approve.

### Rules

1. Evidence before claims. A stage that has not been run is not a stage that
   passed.
2. A lint run is not a verification. The lint auto-fixer once removed 76
   findings from this repository and silently broke the import graph. Always
   run the test suite after a lint fix.
3. Never weaken an assertion, a lint rule, or a hook to make a gate pass.
   Fix the code, or change the rule deliberately and explain why.
4. One ticket, one close. See `docs/agents/feature-tickets.md`.
5. Use the domain vocabulary from `CONTEXT.md` in ticket titles, commit
   messages, test names, and code. See `docs/agents/domain.md`.
6. Two-axis code review before completion. Every feature or refactor must run
   the two-axis review (Standards + Spec) to prevent drift and fragmentation.
