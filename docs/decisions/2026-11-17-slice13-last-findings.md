# Decided: slice 13's last fixes, accept them or check them again?

**What's stuck.** Slice 13's review (the tooling for the full pass, before any live run) spent its rounds: round 1, round 2 and the one targeted check `docs/REVIEW_PROTOCOL.md` allows. The targeted check closed the round-2 finding (an interrupted pass threw away a completed run and ran it again) but found three new defects in the recovery that fix introduced. The protocol sends them to you rather than to another round.

**The findings (reviewer A, `review/slice13-t-a.md`; reviewer B, `review/slice13-t-b.md`).** When `casebook pass --resume` recovers a run the process stopped in:

1. **A changed key went unnoticed** (A-S6, B-D2). Recovery graded a completed run against the answer key computed from the book as it is now; if the book changed after the run, that is a different key from the one the run recorded, and nothing compared them.
2. **A refused grade turned into a rerun** (A-S1). If recovery's grade was refused (the task, key or grader changed since the run), the completed run was closed as failed and its slot run again.
3. **A half-finished publication counted as done** (A-D1). A stop after the published record and before its transcript left the slot done with no transcript, and the task page linked to a missing file.

**What the builder did.** Confirmed each and fixed it in `src/casebook/runner/session.py` (`recover_run`) and `full_pass.py` (`close_interrupted`):

1. Recovery recomputes the key and grades only if its hash equals the run's recorded answer key; otherwise the grade is refused.
2. A refused grade keeps the run as it is, completed and ungraded, with the reason; `casebook pass --status` lists it under "completed runs not graded"; its slot is not run again.
3. Recovery always publishes a public run again, record and transcript, whatever the stop left.

Tests (`tests/test_pass.py`) drive the real `run_and_grade` on the stand-in CLI for each: a key changed before recovery leaves the run completed, ungraded and listed, with three launches, not four; a transcript missing after a stop is written on resume, with no relaunch. `make check` passes. No reviewer has seen the fixes.

**Options.**

1. **Accept the fixes as they stand.** Slice 13's tooling review closes on this page; the whole-branch review sees these lines with everything else.
2. **Ask for one more targeted check of these lines.** Both reviewers' sessions are still open; it costs one short call each.

**My recommendation.** Option 2. Each round of this review has found a defect the previous fix introduced, and this code decides whether a completed live run is kept, graded or run again: the 288 live runs depend on it, and a check costs two short calls, while a defect found during the pass costs live runs.

**If you don't decide.** The fixes stay in, and the live pass waits for your answer here and on the questions before it.

**Decision.** Option 2, one more targeted check (the owner, 17 November 2026).

## The second targeted check, and what it left

**Outcome (reviewer A, `review/slice13-t2-a.md`; reviewer B, `review/slice13-t2-b.md`).** Both reviewers closed all three fixes, each confirmed by their own probe: a changed key is refused, a refused grade keeps the run with no relaunch, and a missing transcript is published on resume. Both found one new blocker the second fix introduced (A-D2, B-D3): a **private** run kept completed and ungraded reached the private summary at the end of the pass, where `outcome` raised an uncaught `ResultsError`. That happened on that resume, and on every later one.

**What the builder did.** Confirmed it, and fixed it in `src/casebook/cli.py` (the `pass` command) and `full_pass.py` (`ungraded_runs`). When a run is kept ungraded, the pass still completes and runs nothing again. It writes no private counts, says why on stderr ("private outcome counts not written: run ... is completed with no grade"), lists the run under "completed runs not graded", and exits 1. A kept, ungraded public run also makes the pass exit 1. Nothing changes in whether a run is kept, graded or run again. The regression, `tests/test_pass.py::test_a_private_run_kept_ungraded_holds_back_the_private_counts_and_fails_the_pass_without_a_rerun`, resumes such a pass twice: six launches in all, no summary, exit 1 each time. No reviewer has seen this fix.

**Options.**

1. **Accept the fix as it stands.** The tooling review closes here; the whole-branch review sees these lines with everything else.
2. **Ask for a third targeted check.** It costs one short call to each reviewer.

**My recommendation.** Option 1. This fix touches only what the command prints and its exit code once the pass is complete; how runs are kept, graded or run again is what the second check confirmed, and it is unchanged. The case it covers arises only if the book, a key or a grader changes in the middle of the pass.

**If you don't decide.** The fix stays in, and the live pass waits on this and on the questions before it.

**Decision.** Option 1, accept the fix as it stands (the owner, 17 November 2026). The tooling review closes here; the whole-branch review sees these lines.
