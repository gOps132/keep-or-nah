---
name: implement
description: Implement work based on a GitHub ticket or spec for Keep or Nah. Drives test-first TDD at pre-agreed seams, enforces uv run pytest and type verification, performs two-axis code review (Standards + Spec), and closes the GitHub issue.
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
  - Rust core algorithms: test through `keep_or_nah_core` module in `tests/test_rust_core.py`.
  - Photo session state & navigation: test through `PhotoSession` in `tests/test_photo_session_groups.py`.
  - Preview & Caching: test through `PreviewPipeline` in `tests/test_preview_strategies.py`.
  - View Filtering: test through `ViewFilter` in `tests/test_view_filter.py`.
- Confirm the seam with the spec/user before writing tests.

### Rules of the Loop
1. **Red Before Green**: Write a failing test first that specifies the expected observable behavior. Run the test and ensure it fails for the expected reason:
   ```bash
   uv run pytest tests/test_<module>.py -k <test_name>
   ```
2. **Minimal Green**: Write only enough code to pass the test. Do not anticipate future requirements or add speculative abstractions.
3. **One Slice at a Time**: One seam, one test, one minimal implementation per cycle.
4. **Rust Extensions**: If Rust code in `crates/keep_or_nah_core/` was modified, recompile into the active virtual environment before testing:
   ```bash
   uv run maturin develop
   ```
5. **Anti-Patterns to Avoid**:
   - *Never mock internal collaborators*: Avoid mocking private methods or internal state variables. Test against public API outcomes.
   - *Never write tautological tests*: Use independent, known-good test fixtures or assets.
   - *Never write all tests upfront*: Advance test-by-test.

### Verification Cadence
- Run focused tests after every green edit:
  ```bash
  uv run pytest tests/test_<module>.py
  ```
- Run formatting / lint checks:
  ```bash
  uv run ruff check .
  ```
- Run the **entire project test suite** before code review:
  ```bash
  uv run pytest
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
