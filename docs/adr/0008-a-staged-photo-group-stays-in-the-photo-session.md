# A Staged Photo Group Stays in the Photo Session

ADR-0004 chose staged triage over immediate filesystem writes, and it required a staged decision to be "rendered visually on the thumbnail strip". The implementation removed the Photo Group from the queue the moment it was staged, so there was nothing left to render and no way to see what had been decided without opening the review modal. We decided that a Photo Group that carries a Staged Decision stays in the Photo Session: it is still in the source folder, it is still in the queue, and the Thumbnail Strip shows the decision on it.

## Considered Options

- **Leave the Photo Group out of the queue and report the staged decisions elsewhere**: the behaviour the code had. We rejected it: the strip is the one surface that shows every Photo Group in the session, and a decision the photographer cannot see is a decision they have to remember. ADR-0004 was written to buy the safety of a staged decision, and a hidden decision spends that safety on a second confirmation step.
- **Leave the Photo Group out of the queue and add a second row to the strip for the staged decisions**: a second surface that answers "what have I decided" but not "what did I decide about *this* photo", and it splits one list into two.
- **Keep the Photo Group in the queue and render the decision on it (chosen)**: the Photo Group is still in the source folder, so the queue is still an honest picture of the folder. The decision is drawn on the Photo Group itself, so the answer and the question are in the same place.

## Consequences

- A Photo Group that carries a Staged Decision is a pending Photo Group that already has a decision. `completed_stems` is the set of stems whose decision reached the disk, and a staged Photo Group is not in it.
- `remaining_count` is the number of Photo Groups still waiting for a decision. `pending_count` is the number of Photo Groups the session holds, decided or not, which is what makes a session worth recovering.
- The keep and nah counts are the decisions that reached the disk. A staged decision is counted by the batch summary until the batch is committed.
- Deciding again about a Photo Group that already carries a Staged Decision revises that decision instead of recording a second one, and the focus moves to the next Photo Group that is still waiting for a decision. When every Photo Group has a decision there is no next one, so the focus stays where it is and the decision key revises the decision the photographer is looking at.
- The snapshot format does not change. A session saved before this decision put a staged Photo Group in `completed_stems` and left it out of the pending list; those sessions are migrated when they are restored, so a photographer does not lose the staged decisions they had in flight.
- A Batch Commit takes the committed Photo Groups out of the queue, because their decision has been carried out and the strip must not keep offering them for triage.
