---
name: implement
description: Implement work based on a GitHub ticket or spec for Keep or Nah. Drives test-first TDD at pre-agreed seams, enforces scripts/verify.sh, performs two-axis code review (Standards + Spec), and closes the GitHub issue.
---

# Implement (Test-Driven Ticket Execution)

Picks up an unblocked GitHub ticket on `gOps132/keep-or-nah`, implements the solution strictly test-first at pre-agreed public seams, runs a two-axis code review, and closes the ticket loop.

---

## 1. Claim & Fetch the Ticket

1. Identify the unblocked ticket from the frontier:
   ```bash
   gh issue list --state open --label "ready-for-agent"
   ```
2. Fetch the full ticket details and comments:
   ```bash
   gh issue view <NN> --comments
   ```
3. Assign the ticket to indicate active in-progress work:
   ```bash
   gh issue edit <NN> --add-assignee @me
   ```

---

## 2. Test-Driven Development (TDD) Loop

TDD is the red → green loop. Tests verify behavior through public interfaces, never internal implementation details.

### Agree on Seams Before Writing Code
- A **seam** is the public boundary where behavior is observed without reaching into internals:
  - Rust core algorithms (`crates/keep_or_nah_core/`): unit and parity tests via `cargo test --manifest-path crates/keep_or_nah_core/Cargo.toml`.
  - Tauri session state, burst clustering, & IPC commands (`src-tauri/`): unit and integration tests via `cargo test --manifest-path src-tauri/Cargo.toml`.
  - React/TypeScript frontend (`frontend/src/`): component & integration tests via `npm --prefix frontend test`.
- Confirm the seam with the spec/user before writing tests.

### Rules of the Loop
1. **Red Before Green**: Write a failing test first that specifies the expected observable behavior. Run the test and ensure it fails for the expected reason:
   ```bash
   scripts/agent/test.sh
   ```
2. **Minimal Green**: Write only enough code to pass the test. Do not anticipate future requirements or add speculative abstractions.
3. **One Slice at a Time**: One seam, one test, one minimal implementation per cycle.
4. **Anti-Patterns to Avoid**:
   - *Never mock internal collaborators*: Avoid mocking private methods or internal state variables. Test against public API outcomes.
   - *Never write tautological tests*: Use independent, known-good test fixtures or assets.
   - *Never write all tests upfront*: Advance test-by-test.

### Verification Cadence
- Run focused tests after every green edit:
  ```bash
  scripts/agent/test.sh
  ```
- Run formatting / lint checks:
  ```bash
  scripts/agent/lint.sh
  ```
- Run the **full verification pipeline** before code review:
  ```bash
  scripts/verify.sh
  ```

---

## 3. Two-Axis Code Review (`code-review`)

Before committing, review the diff (`git diff HEAD~1` or against the base branch) along two independent axes:

### Axis 1: Standards Review
- Does the code follow repository conventions and documentation standards?
- Check against the **smell baseline**:
  - *Mysterious Name*: Variables, functions, or types whose names don't reveal their purpose.
  - *Duplicated Code*: Shared logic across multiple hunks that should be factored out.
  - *Feature Envy*: Methods reaching into another object's data more than their own.
  - *Primitive Obsession*: Raw numbers/strings instead of domain classes/enums.
  - *Thread-Safety Smells*: Calling Tkinter UI methods directly from background threads instead of `root.after()`.
  - *Speculative Generality*: Unused abstractions, unnecessary parameters, or dead branches.

### Axis 2: Spec Review
- Verify that every acceptance criterion in ticket `#NN` is completely satisfied.
- Check for **scope creep**: Is there any behavior or change introduced that the ticket did not ask for? Remove it.
- Confirm edge cases specified in the ticket are covered by tests.

---

## 4. Commit, Document & Close the Ticket

1. Commit changes referencing the issue (conventional commits style):
   ```bash
   git commit -m "feat(<scope>): <concise description> (closes #NN)"
   ```
2. Post a summary comment on the GitHub issue:
   ```bash
   gh issue comment <NN> --body "$(cat << 'EOF'
   ### Shipped
   - <Concise summary of what was delivered>

   ### Files Modified
   - `<file1>`
   - `<file2>`

   ### Verification
   - Tests added: `<test-name>`
   - Full test suite passed: `uv run pytest` (139 passed)
   EOF
   )"
   ```
3. Close the issue:
   ```bash
   gh issue close <NN>
   ```
4. If an architectural invariant was modified, verify that `CONTEXT.md` and `docs/adr/` are updated.
