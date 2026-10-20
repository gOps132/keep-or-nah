---
name: grill-me-with-docs
description: Initialize GitHub workflow and domain docs context for Keep or Nah. Enforces the "no ticket, no feature" rule, resolves or creates the GitHub issue, reads CONTEXT.md and ADRs, and starts the design loop.
---

# Grill Me with Docs (GitHub Workflow & Domain Setup)

Stage 1 of the Keep or Nah feature lifecycle. Ensures every feature is anchored in a GitHub issue, grounded in existing domain documentation, and leaves an architectural paper trail.

## 1. Enforce the Invariant: No Ticket, No Feature

Per `docs/agents/feature-tickets.md`:
> Every new feature requested in a conversation must map to exactly one GitHub issue ticket before any implementation code is written.

### Workflow:
1. **Resolve or Create**:
   - Check if the user specified an issue number (`#NN`).
   - If not, create one immediately:
     ```bash
     gh issue create --title "<feature-slug>" \
       --body "Type: task\n\n## Overview\nInitial ticket for feature discussion and specification." \
       --label "ready-for-agent"
     ```
2. **Anchor in Conversation**:
   - Announce the active ticket: `Working on ticket #NN: <title>`.
   - All subsequent grilling notes, ADRs, and commits will reference this issue.

---

## 2. Read Domain Documentation

Before exploring the codebase or interviewing the user:
1. **`CONTEXT.md`**: Read the domain glossary. Use terms defined here; do not drift to synonyms the glossary explicitly avoids.
2. **`docs/adr/`**: Read existing ADRs in the area being touched to understand historical decisions and avoid reopening settled trade-offs.
3. **`docs/agents/`**: Review issue tracker, triage labels, and feature ticket conventions.

---

## 3. Active Domain Modeling

As discussions proceed:
- **Challenge terminology**: If the user uses a term that conflicts with `CONTEXT.md`, call it out immediately.
- **Sharpen fuzzy language**: Propose canonical names for ambiguous concepts (e.g. "culling" vs "curating", "similarity cluster" vs "burst group").
- **Update `CONTEXT.md` inline**: Add newly agreed domain terms directly to `CONTEXT.md`. (Keep `CONTEXT.md` strictly as a glossary—no implementation details).
- **Propose ADRs**: When a decision is:
  1. *Hard to reverse* (e.g. session file schema changes, Rust FFI signature shifts)
  2. *Surprising without context*
  3. *Result of a genuine trade-off*
  Write an ADR under `docs/adr/NNNN-<slug>.md` using the project's standard ADR template.

---

## 4. Next Step

Proceed directly into the relentless interview loop:
👉 **Use `@interview` (or `@grill-me`)** to map out the design tree and settle all technical decisions with application context.
