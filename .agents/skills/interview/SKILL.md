---
name: interview
description: Relentless interview primitive and application-specific planning. Structures discussions as a design tree, probes the frontier with recommended options, looks up facts autonomously, and blends Keep or Nah domain architecture (Tkinter, Rust core, preview pipeline, photo groups) to produce an actionable spec.
---

# Interview & Planning (Keep or Nah Design Tree Grilling)

The core interview and planning engine. Interviews the user relentlessly until every branch of the design tree is resolved, blending generic architectural principles with Keep or Nah subsystem knowledge.

---

## 1. The Design Tree & The Frontier

Map the feature as a **design tree**: every major decision branches into subordinate decisions.

- **The Frontier**: All decisions whose prerequisites have been resolved.
- **Rounds**: Ask the whole frontier in one batch.
- **Format**:
  ```markdown
  ❓ **Q1** - **<Decision Title>**: <Background, trade-offs, and options>

  ➡️ **Recommended**: <Concrete recommended choice and why>

  ---

  ❓ **Q2** - **<Decision Title>**: <Background, trade-offs, and options>

  ➡️ **Recommended**: <Concrete recommended choice and why>
  ```
- Wait for user responses. Each answer expands or settles branches, advancing the frontier.
- Stop when the frontier is empty and all technical requirements are locked down.

---

## 2. Autonomous Fact Discovery

**Finding facts is the agent's job, never the user's.**
- If a question depends on existing code patterns, UI coordinates, Rust PyO3 bindings, or configuration: **search and inspect the files directly**.
- Do NOT ask the user: "What parameters does `compute_blur_score` accept?" or "Where are session files saved?"
- Only decisions, trade-offs, and product requirements belong to the user.

---

## 3. Blend Application-Specific Keep or Nah Skills & Architecture

During the interview, ground every question in Keep or Nah's design contracts:

1. **Rust Core Contracts** (`crates/keep_or_nah_core/`, `preview_pipeline.py`):
   - Python-Rust bridge using PyO3.
   - Operations that belong in Rust: heavy image decoding, downscaling, Laplacian variance blur detection, perceptual hashing, SIMD/parallel loops.
   - Rebuilding after Rust edits: `uv run maturin develop`.
2. **GUI & Threading Discipline** (`main.py`, `classic_gui.py`, `preview_pipeline.py`):
   - Tkinter event loop must never block on disk I/O or image manipulation.
   - Asynchronous worker queues and background threads push completed Tk images/events back to the main thread safely.
   - Keyboard shortcuts, canvas zoom/pan transforms, and ribbon navigation should stay responsive (<16ms frame budget).
3. **Session & Grouping Contracts** (`photo_session.py`, `photo_groups.py`, `view_filter.py`):
   - Fast state toggles (Keep, Nah, Flag, Reset).
   - Burst detection and perceptual hash clusters should operate on cached metadata without reloading full raw images.
   - View filters must cleanly preserve active index and selection history.
4. **Session Persistence** (`session_persistence.py`):
   - Atomic saves and backward-compatible serialization.

---

## 4. Synthesize the Spec

When the interview completes, produce the formal spec directly in the conversation / ticket:
- **Problem Statement**: What problem is being solved?
- **Solution**: High-level architectural approach.
- **User Stories & Workflows**: Concrete interactions and UI behavior.
- **Implementation Decisions**: Data models, module interfaces, Rust/Python boundaries.
- **Public Seams**: The exact public interfaces where behavior will be tested.
- **Out of Scope**: Explicit boundaries.

Once approved by the user, hand off to:
👉 **`@to-tickets`** to break down the spec into tracer-bullet tickets on GitHub.
