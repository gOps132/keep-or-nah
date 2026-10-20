---
name: to-tickets
description: Break down a spec, plan, or conversation into tracer-bullet vertical slice tickets with explicit blocking edges, published directly to GitHub Issues on gOps132/keep-or-nah.
---

# To Tickets (Tracer-Bullet Decomposition)

Break an approved specification into self-contained vertical-slice tickets, establish dependency blocking relationships, and publish them to GitHub Issues on `gOps132/keep-or-nah`.

---

## 1. Vertical Slice Rules

Every ticket must be a **tracer bullet**:
- **Vertical, Not Horizontal**: Cuts a narrow but complete path through all required layers (e.g. Rust core -> Python wrapper -> Session/Pipeline -> GUI interaction -> tests). Never create tickets for "add Rust functions" in isolation from their consumer.
- **Demoable / Verifiable**: Each ticket delivers observable, testable behavior that can be confirmed immediately when finished.
- **Smart Zone Sized**: Sized to fit comfortably inside a single fresh context window (~150k tokens).
- **Prefactoring First**: Isolate refactoring or preparation into its own initial ticket ("Make the change easy, then make the easy change").
- **Expand–Contract for Wide Refactors**: When a change affects many call-sites (e.g. changing `PhotoItem` attributes or session schema), sequence as:
  1. *Expand*: Add new interface alongside existing.
  2. *Migrate*: Shift callers module by module.
  3. *Contract*: Delete the old interface once all callers are migrated.

---

## 2. Declare Blocking Edges

Identify dependencies clearly:
- Each ticket lists: `Blocked by: #NN, #NN` or `None (can start immediately)`.
- A ticket cannot start until all its blocking issues are closed on GitHub.
- Any ticket with no open blockers is on the **frontier** and ready for implementation.

---

## 3. Review Granularity with the User

Present the ticket breakdown to the user before publishing:
- **Title**: `<NN>-<slug>` (e.g. `12-blur-score-display`, `13-similarity-grouping`)
- **What it delivers**: The end-to-end observable capability.
- **Blocked by**: Upstream prerequisite tickets.

Ask the user:
- Is the granularity right (too coarse or too fine)?
- Are the dependencies accurate?
- Do any tickets need merging or splitting?

---

## 4. Publish to GitHub Issues (`gh`)

Once approved, publish each ticket in dependency order (blockers first) so issue numbers can be cross-referenced:

```bash
gh issue create \
  --title "<NN>-<slug>" \
  --body "$(cat << 'EOF'
## Parent
Parent Feature: #<PARENT_ISSUE_NUMBER>

## What to build
<End-to-end observable behavior from user/caller perspective>

## Acceptance Criteria
- [ ] Observable behavior 1
- [ ] Observable behavior 2
- [ ] Test coverage at agreed seam (`uv run pytest`)
- [ ] Documentation updated if architectural

## Blocked by
- #<BLOCKER_ISSUE_NUMBER> (or None)
EOF
)" \
  --label "ready-for-agent"
```

---

## 5. Next Step

Begin implementation of the first unblocked ticket:
👉 **Use `@implement`** to pick up the ticket and build test-first.
