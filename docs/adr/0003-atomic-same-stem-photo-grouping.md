# Atomic Same-Stem Multi-File Photo Grouping

Photographers frequently shoot RAW+JPEG pairs alongside companion XMP sidecar metadata files that share an identical file stem within a folder. We decided to treat all files sharing a stem as an atomic `PhotoGroup` entity across directory scanning, thumbnail rendering, navigation, and triage operations, ensuring associated sidecars and matching format pairs are never separated or orphaned.

## Considered Options

- **Individual File Operations**: Operating on standalone files requires manual multi-selection by the user and routinely results in forgotten XMP sidecars or orphaned RAW duplicates.
- **Hiding Sidecars into Special Subfolders**: Mutates the user's directory organization and violates non-destructive photographer expectations.
- **Atomic PhotoGroup Representation (Chosen)**: Direct-child files sharing an exact stem are discovered natively and triaged together atomically, choosing one optimal representative for preview generation.

## Consequences

- File operations, session state, and undo journaling must coordinate moves across all member files within a group simultaneously.
- If a group contains multiple previewable formats (e.g. RAW and JPEG), the pipeline deterministically selects the optimal representative file.
