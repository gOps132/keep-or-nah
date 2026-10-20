# Staged Triage with Batch Review and Commit

Immediate filesystem mutation upon every triage action creates user anxiety regarding accidental keypresses and makes multi-step rollback risky during fast curation sessions. We decided to implement an in-memory staged triage mode where decisions (`keep`, `nah`, `flag`) are recorded non-destructively, rendered visually on the thumbnail strip, and confirmed via a review modal before batch atomic execution.

## Considered Options

- **Immediate Disk I/O with Undo Stack**: Modifies the filesystem on every keystroke. Files moved immediately are vulnerable to external lockouts, accidental loss, and directory pollution if interrupted mid-session.
- **Implicit Commit on Folder Change or Exit**: Surprises the user with hidden disk operations without an explicit summary of files or disk space reclaimed.
- **Staged Triage with Batch Commit (Chosen)**: Non-destructive in-memory decision mapping with visual indicators, batch summary statistics (file count, reclaimed disk space), and atomic execution with complete rollback on failure.

## Consequences

- Session snapshots must persist staged decisions across unexpected app crashes or exits.
- The UI must distinguish between immediate triage mode and staged triage mode while maintaining identical hotkey ergonomics.
