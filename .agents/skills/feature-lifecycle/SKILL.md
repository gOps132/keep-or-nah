---
name: feature-lifecycle
description: Consolidated end-to-end engineering lifecycle for Keep or Nah. Unifies routing (ask-matt), GitHub ticket initialization (grill-me-with-docs), relentless interview with photo curation domain context (interview/grill-me), tracer-bullet ticket decomposition (to-tickets), and test-driven implementation (implement).
---

# Feature Lifecycle (Keep or Nah Engineering Workflow)

The consolidated end-to-end engineering pipeline for Keep or Nah. Takes any feature request, performance enhancement, or architectural change from inception through relentless interview, ticket breakdown, test-driven implementation, and verified close on GitHub Issues.

```
                    ┌─────────────────────────┐
                    │  Incoming Feature / Idea│
                    └────────────┬────────────┘
                                 │
                                 ▼
                     Phase 0: Route & Gate
                     (@ask-matt flow selector)
                                 │
                                 ▼
           Phase 1: Initialize GitHub Workflow & Domain Docs
           (@grill-me-with-docs — "No ticket, no feature")
                                 │
                                 ▼
         Phase 2: Relentless Interview & Application Planning
         (@interview + @grill-me + Keep or Nah Subsystems)
                                 │
                                 ▼
           Phase 3: Tracer-Bullet Ticket Decomposition
           (@to-tickets — vertical slices + blocking edges)
                                 │
                                 ▼
           Phase 4: Ticket Implementation, Review & Close
           (@implement — TDD seams, 2-axis review, gh close)
```

---

## Phase 0: Route & Flow Selection (`@ask-matt`)

Before writing any code or drafting specs, confirm the route:

1. **New feature / capability / architectural change** → Proceed through this full pipeline (**Phase 1**).
2. **Raw incoming bugs / unvetted requests** → Triage first into standard roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`).
3. **Hard-to-pin bugs or regressions** → Stop and establish a **tight feedback loop** (one command that goes red on this bug) before theorizing.
4. **Foggy multi-session epic** → Chart a shared map of decision tickets before building specs.

---

## Phase 1: Initialize GitHub Workflow & Domain Docs (`@grill-me-with-docs`)

Keep or Nah enforces a strict invariant from `docs/agents/feature-tickets.md`:
> **No ticket, no feature.** Every new feature requested in a conversation must map to exactly one GitHub issue ticket before any implementation code is written.

### 1. Resolve or Create the GitHub Issue
- Ask the user for the ticket number (`#NN`).
- If not provided, create one immediately via GitHub CLI:
  ```bash
  gh issue create --title "<feature-slug>" \
    --body "Type: task\n\n## Overview\nInitial ticket for feature discussion and specification." \
    --label "ready-for-agent"
  ```
- Announce the active ticket: `Working on ticket #NN: <title>`.

### 2. Read Domain Documentation
- **`CONTEXT.md`**: Read domain glossary if present.
- **`docs/adr/`**: Read existing ADRs in touched areas.
- **`docs/agents/`**: Read issue tracker, triage labels, and feature ticket rules.

---

## Phase 2: Relentless Interview & Planning (`@interview` / `@grill-me`)

Interview relentlessly until every branch of the design tree is resolved.

### Ground in Keep or Nah Architecture:
1. **Tkinter GUI & Event Loop** (`main.py`, `classic_gui.py`):
   - TkinterDnD2 drag-and-drop support.
   - Canvas image rendering and coordinate transformations.
   - Non-blocking UI operations (heavy I/O offloaded from Tkinter mainloop).
2. **Rust Core Extension** (`crates/keep_or_nah_core/`):
   - Fast image decoding, downsampling, and thumbnail generation.
   - Perceptual hash calculation (`dhash`, `phash`) and similarity grouping.
   - Blur detection via Laplacian variance.
   - Recompile extension when modifying Rust: `uv run maturin develop`.
3. **Photo Pipeline & State** (`photo_session.py`, `preview_pipeline.py`, `view_filter.py`, `photo_groups.py`):
   - Session states: Keep, Nah, Undecided, Flagged.
   - View filtering and responsive keyboard shortcuts (1-4, J/K, Delete, Space).
   - Async thumbnail and preview pre-fetching pipeline.
4. **Persistence & Settings** (`session_persistence.py`, `app_settings.py`):
   - JSON-based session file serialization and recovery.
   - Application preferences and geometry persistence.

### Discovery Rule:
- **Autonomous fact discovery**: The agent reads the codebase, inspects existing modules, and runs verification commands. Never ask the user for facts visible in the code.
- Only decisions, trade-offs, and user preferences belong to the user.

---

## Phase 3: Tracer-Bullet Ticket Decomposition (`@to-tickets`)

Break down the agreed specification into vertical slices:
- **Tracer Bullets**: Cuts across UI/state/Rust layers; delivers observable, testable behavior.
- **Explicit Blocking Edges**: Connect tickets via `Blocked by: #NN`.
- **Review with User**: Confirm granularity and dependencies before publishing.
- **Publish to GitHub**:
  ```bash
  gh issue create --title "<NN>-<slug>" --body "..." --label "ready-for-agent"
  ```

---

## Phase 4: Implementation, Review & Close (`@implement`)

Pick up unblocked tickets one by one:
1. **Claim Ticket**: `gh issue edit <NN> --add-assignee @me`.
2. **Agree on Seam**: Identify the public seam to test (e.g. `PhotoSession`, `PreviewPipeline`, `keep_or_nah_core`).
3. **TDD Loop**:
   - Write failing test in `tests/test_...py`.
   - Run test: `uv run pytest tests/test_...py -k <test_name>`.
   - Implement minimal green code.
   - If Rust was edited: compile with `uv run maturin develop`.
   - Verify full suite: `uv run pytest`.
4. **Two-Axis Code Review**:
   - *Standards*: Check against smell baseline (names, duplication, coupling).
   - *Spec*: Verify all acceptance criteria are met with zero scope creep.
5. **Commit & Close**:
   - Commit with conventional commit referencing `#NN`.
   - Post summary comment with shipped changes and test results.
   - Close issue with `gh issue close <NN>`.
