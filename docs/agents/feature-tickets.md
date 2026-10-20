# Feature tickets: no ticket, no feature

Every **new feature** requested in a conversation must map to exactly one GitHub issue ticket before any implementation code is written. Bugfixes and quick refactors are exempt unless they expand into feature scope.

## The rule

1. **Resolve first.** When a feature request lands, ask for the ticket (`#NN`) — or create one with `gh issue create` if none exists. Do not start the design loop (grilling, planning, coding) until the ticket exists and its number is stated in the conversation.
2. **Create correctly.** Title `<slug>` (or `<NN>-<slug>`), body holds the agreed spec with `Type: task` near the top. Label `ready-for-agent` when implementing in-session, `needs-triage` when parking for later.
3. **Work in the open.** Reference `#NN` in the grilling rounds and the implementation plan. Keep specs and design decisions attached to the ticket and repo docs.
4. **Close the loop.** When the work is verified, post a summary comment (what shipped, files touched, verification results) and close the issue with `gh issue close <NN>`. One feature, one ticket, one close.

## Why

Tickets make feature work discoverable, reviewable, and attributable across sessions and after chat context is cleared.
