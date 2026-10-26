---
name: interview
description: Relentless interview primitive and application-specific planning. Structures discussions as a design tree, probes the frontier with recommended options, looks up facts autonomously, and blends Keep or Nah domain architecture (Tauri v2, React/TypeScript frontend, Rust core, progressive preview pipeline, photo groups) to produce an actionable spec.
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

1. **Rust Core Contracts** (`crates/keep_or_nah_core/`):
   - Pure Rust crate linked directly into `src-tauri/`.
   - Operations that belong in Rust: directory scan, atomic file operations with 5-component file identity verification, embedded RAW preview extraction, hardware-accelerated full RAW demosaicing, SIMD Lanczos3 scaling, Laplacian sharpness scoring, and `dHash` perceptual hashing.
2. **Tauri v2 & Frontend Discipline** (`src-tauri/`, `frontend/src/`):
   - UI thread must never block on disk I/O or image decoding; heavy renders use bounded single-worker background tasks with monotonic cancellation (`HEAVY_RENDER_GENERATION`) and 300ms settle debounce (`useProgressiveAsset`).
   - Keyboard shortcuts, canvas zoom/pan transforms, and Thumbnail Strip navigation must remain responsive (<16ms frame budget).
3. **Session & Grouping Contracts** (`src-tauri/src/session.rs`, `crates/keep_or_nah_core/src/scan.rs`):
   - Atomic same-stem Photo Groups (`RAW` + `JPEG` + `XMP` sidecar).
   - Staged triage by default (`Keep`, `Nah`, `Flag`) with atomic Batch Commit and emergency recovery journal, plus optional Immediate Mode and custom destination folders.

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
