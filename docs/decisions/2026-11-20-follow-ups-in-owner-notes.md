# Decision needed: how your hand-written notes record a follow-up, so T-MTG-05's key can read them

**What's stuck.** The merge, by the whole-branch review. Reviewer B holds D2 as a blocker after round 2 until you either choose a fix or accept the deferral in writing. Your notes step (slice 5) works today: the build accepts your notes and checks every amount and date. But as soon as one featured household has your notes, T-MTG-05's key stops on that note. The full pass and `casebook run --task T-MTG-05` stop with it. Nothing breaks until you add notes.

**Evidence.**
- I built the book with `tests/test_notes.py`'s worked example as HH-4821's notes. The key then raised `UnsettledFollowUpError N-4821-01: a note the key cannot read for a follow-up`.
- T-MTG-05 asks which households have a follow-up recorded in the CRM that hasn't happened by the cutoff. The key reads follow-ups from the CRM's activities. A template note says one of two set things, neither of which commits anyone to a step, so the key accepts it. It refuses any other note rather than guess (`src/casebook/keys/open_follow_ups.py:232`).
- Your notes are free text, and they can promise a step. The worked example's second note ends "Raising it with billing." Accepting owner notes as committing to nothing would make the key wrong exactly when a note promises something.
- The key is part of the recorded freeze. Changing it now would leave the published freeze and results out of step with the code at the `v0.1.0` tag, and refuse every run that reaches a held-out household until the freeze is recorded again.

**Options.**

1. **A note records what happened; a promised step is a CRM activity.** Each note in your notes file says `follow_up = false`. A step someone commits to goes in the household's script as an activity (a meeting, call or request, with what it agrees to), and the note may cite that activity as a fact. The build refuses a note without the line. Consequence: T-MTG-05's answer comes from activities alone, as now. You write a little more for a note that promises something, and "Raising it with billing." becomes an activity.
2. **A note may list the steps it commits to.** Each note gains `follow_ups = [...]`, each entry naming the step and the account, in a form the key reads, which is the same work as an activity. Consequence: more format to learn, and a second place follow-ups live.
3. **Leave T-MTG-05 off the households with your notes.** Consequence: the task's answer stops covering the featured households, which weakens the task.
4. **Reviewer B's alternative: the key marks a household "unresolved" when one of its notes is one it can't read.** T-MTG-05 then still runs, and the pass completes. The other follow-ups stay as found, and nothing is silently counted as absent. Consequence:
   - It is a change to a frozen key now, so before the tag you would record the freeze again and regrade the pass under it (`casebook freeze`, then `casebook regrade`). The published freeze and results must stay consistent with the code.
   - Every household with your notes becomes "unresolved" for T-MTG-05 until a format like option 1's lets the key read them.
5. **Accept the deferral.** Merge and tag as built. When you write notes, option 1 (or 2) lands with them, with the key change, a new freeze and a rerun of T-MTG-05.

With options 1 to 3 and 5, the key change, a new freeze and a rerun of T-MTG-05 go in with your notes. They are a new book version anyway, if they land after the preview.

**My recommendation.** Option 5 now, with option 1 as the format when you write notes. Nothing breaks until a note exists. Option 4 would change a frozen key, record the freeze again and regrade the pass before the tag, all for notes not yet written.

**If you don't decide.** The whole-branch review stays open on this finding, so the branch isn't ready to merge. Nothing else changes: when you write notes, the build accepts them and T-MTG-05 stops on them, naming the note. The STATUS step for your notes says so.

**Decision.** <open>
