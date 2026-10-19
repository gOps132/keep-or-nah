# Keep or Nah

A desktop photo culling and triage application for photographers to rapidly review, compare, and organize photo sessions.

## Language

### Core Entities

**Photo Group**:
All files sharing the exact same filename stem in a directory (e.g., RAW, JPEG, and XMP sidecar), treated as an atomic unit.
_Avoid_: Stem group, photo cluster, multi-file set

**Representative**:
The primary image file within a photo group chosen for preview rendering and thumbnail generation.
_Avoid_: Primary file, display image, hero file

**Photo Session**:
The active working state managing the source directory, queue of photo groups, triage destinations, and navigation position.
_Avoid_: Project, catalog, album

### Triage & Decisions

**Triage**:
The evaluation and categorization of a photo group into Keep, Nah, or Flag.
_Avoid_: Culling, sorting, rating

**Keep**:
A triage decision marking a photo group to be retained and moved or copied to the designated keep directory.
_Avoid_: Approve, accept, favorite

**Nah**:
A triage decision marking a photo group to be discarded and moved to the designated trash destination or system trash.
_Avoid_: Reject, delete, discard, drop

**Flag**:
A triage decision marking a photo group for later re-examination without moving it immediately.
_Avoid_: Star, bookmark, mark

**Staged Decision**:
A non-destructive, in-memory triage decision recorded during a session prior to batch execution.
_Avoid_: Draft decision, pending action, uncommitted change

**Batch Commit**:
The atomic execution of all staged triage decisions with a confirmation review modal and automatic rollback on failure.
_Avoid_: Save changes, apply actions, flush decisions

### File Operations & Safety

**File Operation**:
A verified file system action (atomic move or copy) on an individual file member within a photo group.
_Avoid_: File transfer, file change

**Undo Journal**:
A persistent, transactional record of executed file operations that enables exact, verified reversal.
_Avoid_: History log, audit trail, undo stack

**Action Mode**:
The mechanism used when triaging files, either moving them from the source directory or copying them.
_Avoid_: Transfer type, execution mode

### Analysis & Inspection

**Burst Cluster**:
A sequence of photo groups captured in rapid succession with high visual similarity, detected via timestamp proximity and perceptual difference hashing.
_Avoid_: Photo series, burst group, sequence

**Best Shot**:
The sharpest, highest-quality photo identified within a burst cluster using Laplacian variance sharpness analysis.
_Avoid_: Hero shot, top photo, winner

**Split Comparison**:
A 2-up side-by-side comparison mode displaying two photos with synchronized zooming and panning for precise inspection.
_Avoid_: Compare mode, dual view, side-by-side mode

**Thumbnail Strip**:
The horizontal strip displaying asynchronously decoded thumbnails of photo groups in the active session.
_Avoid_: Filmstrip, bottom gallery, preview bar
