# Staged Triage Is the Default Interaction Model

ADR-0004 chose staged triage over immediate filesystem writes: a triage decision is recorded in memory as a Staged Decision, shown to the photographer, and only executed as a Batch Commit after a review modal confirms the set. The implementation shipped the feature but defaulted it off, so the interaction model ADR-0004 rejected was the one every new user got. We decided to make Staged Triage the default and to keep the immediate mode available as an explicit, persisted choice.

## Considered Options

- **Keep immediate mode as the default**: Preserves the muscle memory of the pre-staged releases. But it means the default behaviour is the one ADR-0004 argued against, and a user who never opens the View menu never sees the safety property the ADR was written to buy.
- **Remove immediate mode entirely**: Simplest and safest. Rejected because the hotkey ergonomics of "press right, file is gone" are genuinely faster for users with a full disk and a clear intent, and the staged model costs a confirmation step on every session.
- **Staged Triage by default, immediate mode as a persisted opt-out (Chosen)**: The safe path is the path you get by doing nothing. A photographer who wants files to move on every keystroke turns that off once, in the View menu or the settings dialog, and the choice persists.

## Consequences

- A settings file that predates the `staged_decisions` key reads as staged, because the key is absent rather than explicitly `false`. This changes behaviour for existing users on upgrade, deliberately: they get the safer model and can switch back with one toggle.
- The Batch Commit button is enabled by default, and the review modal becomes the primary way a session ends. A user in immediate mode sees it disabled.
- The Staged Decision count on the Review Batch button is the primary feedback channel for a decision, which makes issue #21 (rendering Staged Decisions on the Thumbnail Strip) more important: in the default mode, the strip is the only surface where a staged decision could be visible without opening the modal.
- `app_settings.DEFAULT_STAGED_DECISIONS` is the single place the default is defined, and a test asserts it.
