---
name: ask-matt
description: Router over engineering flows for Keep or Nah. Directs tasks to feature-lifecycle, triage, diagnosing-bugs, or wayfinder.
---

# Ask Matt (Keep or Nah Flow Router)

Route incoming tasks, feature requests, bugs, and performance improvements to the correct workflow in Keep or Nah.

## The Main Flow: Feature Lifecycle

When you have a new feature, architecture change, or non-trivial capability to build:
👉 **Use `@feature-lifecycle`** (or `@grill-me-with-docs`).

The pipeline runs unbroken:
1. **`@grill-me-with-docs`**: Resolves/creates the GitHub issue (`#NN`), reads `CONTEXT.md` & `docs/adr/`.
2. **`@interview` / `@grill-me`**: Relentless design interview, discovering codebase facts autonomously and grounding decisions in Keep or Nah architecture (Tkinter UI, Rust core, preview pipeline, photo groups).
3. **`@to-tickets`**: Splits approved spec into tracer-bullet vertical slices with blocking edges on GitHub.
4. **`@implement`**: Builds each ticket test-first via TDD at public seams, verifies with `uv run pytest`, performs two-axis code review, and closes the ticket.

---

## On-Ramps & Alternatives

### 1. Incoming Bugs & Backlog Requests → Triage
When reports or requests arrive raw:
- Map issue into standard triage roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
- Update GitHub label using `gh issue edit <NN> --add-label <label>`.
- Tickets produced by `@to-tickets` are already `ready-for-agent`—do not re-triage them.

### 2. Broken Code & Resilient Bugs → Diagnosing Bugs
When a bug resists immediate inspection or flake occurs:
- **Rule**: Refuse to theorize until you have a **tight feedback loop** (a single command like `uv run pytest tests/test_...py -k ...` that reliably fails on this bug).
- Write a reproduction test, verify the red state, then fix with a minimal patch.
- If the root issue is architectural, document it in `docs/adr/` and feed it into `@feature-lifecycle`.

### 3. Foggy Greenfield / Massive Multi-Session Efforts → Wayfinder
When the path from here to the destination is not visible:
- Do NOT write a monolithic spec or rush into coding.
- Chart a map of **decision tickets** on GitHub (`gh issue create --label wayfinder:map`).
- Resolve decisions one by one until the fog recedes.
- Once clear, hand off to `@feature-lifecycle` to build.
