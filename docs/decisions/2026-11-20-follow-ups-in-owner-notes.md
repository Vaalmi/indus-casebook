# Decision needed: how your hand-written notes record a follow-up, so T-MTG-05's key can read them

**What's stuck.** The whole-branch review, reviewer B's D2. Your notes step (slice 5) works today: the build accepts your notes and checks every amount and date. But as soon as one featured household has your notes, T-MTG-05's key stops on that note. The full pass and `casebook run --task T-MTG-05` stop with it. Nothing breaks until you add notes.

**Evidence.**
- I built the book with `tests/test_notes.py`'s worked example as HH-4821's notes. The key then raised `UnsettledFollowUpError N-4821-01: a note the key cannot read for a follow-up`.
- T-MTG-05 asks which households have a follow-up recorded in the CRM that hasn't happened by the cutoff. The key reads follow-ups from the CRM's activities. A template note says one of two set things, neither of which commits anyone to a step, so the key accepts it. It refuses any other note rather than guess (`src/casebook/keys/open_follow_ups.py:232`).
- Your notes are free text, and they can promise a step. The worked example's second note ends "Raising it with billing." Accepting owner notes as committing to nothing would make the key wrong exactly when a note promises something.
- The key is part of the recorded freeze. Changing it now would leave the published freeze and results out of step with the code at the `v0.1.0` tag, and refuse every run that reaches a held-out household until the freeze is recorded again.

**Options.**

1. **A note records what happened; a promised step is a CRM activity.** Each note in your notes file says `follow_up = false`. A step someone commits to goes in the household's script as an activity (a meeting, call or request, with what it agrees to), and the note may cite that activity as a fact. The build refuses a note without the line. Consequence: T-MTG-05's answer comes from activities alone, as now. You write a little more for a note that promises something, and "Raising it with billing." becomes an activity.
2. **A note may list the steps it commits to.** Each note gains `follow_ups = [...]`, each entry naming the step and the account, in a form the key reads, which is the same work as an activity. Consequence: more format to learn, and a second place follow-ups live.
3. **Leave T-MTG-05 off the households with your notes.** Consequence: the task's answer stops covering the featured households, which weakens the task.

With any option, the key change, a new freeze and a rerun of T-MTG-05 go in with your notes. They are a new book version anyway, if they land after the preview.

**My recommendation.** Option 1. It keeps one place for follow-ups, the key stays simple, and the notes check already ties every amount and date to a fact.

**If you don't decide.** Nothing changes before you write notes. When you do, the build accepts them and T-MTG-05 stops on them, naming the note. The STATUS step for your notes says so.

**Decision.** <open>
