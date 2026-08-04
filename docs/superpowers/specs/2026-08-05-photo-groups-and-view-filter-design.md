# Photo Groups and View Filter Design

## Goal

Treat every regular file with the same exact filename stem as one photo group. Users view one representative, then Keep, Nah, Copy, and Undo operate on the entire group. Let users choose which discovered file extensions can represent groups in the queue. Unsupported formats remain sortable and show a clear unavailable-preview state.

## Group and Queue Model

- Add a `PhotoGroup` domain type containing one stem, all matching source files, and one representative path.
- Group direct-child regular files from the selected source directory by exact, case-sensitive stem. Extension matching is case-insensitive.
- Include a group when at least one member uses an enabled view-filter extension.
- Choose one representative per group. Prefer an enabled member supported by a registered preview strategy; otherwise choose enabled extensions alphabetically. Use filename order as the final deterministic tie-breaker.
- Keep unsupported representatives in the queue. Display filename, extension, and `Preview not available` instead of treating preview failure as a session error.

## View Filter and Preview Strategies

- Extend both preview settings dialogs with checkboxes for extensions discovered in the current source directory.
- On first load of a source, enable every discovered extension. Store the selection in session state so an unfinished session restores exactly. A newly selected source resets the selection to all extensions found there.
- Applying the filter rebuilds groups from the source directory, preserves the active group by stem when possible, and otherwise selects the nearest remaining group.
- Define a small `PreviewStrategy` interface responsible for declaring support and producing preview images. Register the current Pillow renderer as the first concrete strategy.
- When no strategy supports the representative, use an unavailable-preview strategy. Future RAW support can register another strategy without changing grouping, filtering, or decision logic.

## Decisions, Collisions, and Undo

- Keep/Nah in Move or Copy mode processes every member of the active group, including metadata, video, and other same-stem files regardless of filter selection.
- Preflight one shared destination suffix for the whole group. If any original destination name exists, try ` (1)`, ` (2)`, and so on until every destination is free.
- Record all source/destination pairs as one compound action. Counts advance once per group, not once per file.
- If an operation fails midway, reverse already completed operations before reporting the error. If rollback also fails, report both failures and preserve enough action data for recovery.
- Undo reverses the complete compound action. Restored history retains existing source/destination root validation and rejects unsafe members.

## Persistence and Compatibility

- Version the session snapshot and persist photo groups, active stem, enabled extensions, counts, and compound action history.
- Restore only direct children of the saved source and destination roots. Reject traversal and symlink escapes.
- Safely reject incompatible or malformed grouped snapshots. Existing pre-group snapshots migrate by rebuilding groups from their saved source and enabled legacy image extensions when possible.
- Keep CustomTkinter and classic Tk interfaces behaviorally identical through shared group, filter, startup, and preview coordination.

## Error Handling

- Missing group members discovered before a decision are pruned; the remaining members still move or copy.
- A group with no remaining members leaves the queue.
- Unsupported or corrupt previews show the unavailable state while leaving sorting controls usable.
- Persistence errors remain nonfatal and use the existing deduplicated recovery warning.

## Tests

- Group same-stem files and ignore different stems.
- Select one deterministic representative and show one queue item per stem.
- Apply extension filters and restore active stem when possible.
- Render Pillow-supported representatives and show unavailable state for unsupported formats.
- Move and copy all group members with one shared collision suffix.
- Roll back partial failures and undo full compound actions.
- Round-trip grouped session/history state and migrate valid legacy snapshots.
- Reject out-of-root and symlink-escaping queue/history members.
- Exercise filter/startup behavior through both GUI frontends.
- Run unit tests, compile checks, diff checks, and packaged macOS bundle smoke checks.
