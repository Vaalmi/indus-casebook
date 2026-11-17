# Decision needed: accept slice 12's last fix without another review round?

**What's stuck.** Slice 12's review spent its rounds: round 1, round 2 and the one targeted check `docs/REVIEW_PROTOCOL.md` allows. Both reviewers closed every round-1 finding in round 2 but one, which the round-1 fix had introduced. The targeted check closed that one for a single attempt, then both found the same new case its fix introduced. The protocol sends an open blocker after the targeted check to you rather than to another round.

**The finding (reviewers A and B, targeted check, `review/slice12-t-a.md`, `review/slice12-t-b.md`).** A run record says which freeze its output ran under, so a task page never shows results from two freezes side by side. To stop a freeze recorded during a run from relabelling its output, the targeted fix took the freeze, and the skill, checklist and dataset hashes, once, before the run's first attempt. But a run retries a failed attempt: if attempt 1 failed, the owner recorded a new freeze, and attempt 2 then ran and succeeded, its output kept attempt 1's freeze and hashes.

**What the builder did.** Confirmed it with the reviewers' trigger, and fixed it: each attempt now takes its own freeze identity and input hashes as it starts, after its preflight, and the record keeps the last attempt's, which produced the output (`src/casebook/runner/run.py`, `_inputs_hashes`). A test drives the real `run_task` on the stand-in CLI: attempt 1 fails, a skill byte changes and a new freeze is recorded, attempt 2 succeeds, and the record carries attempt 2's freeze and skill hash (`tests/test_freeze.py::test_a_retry_s_output_carries_the_freeze_and_hashes_it_ran_under`); the single-attempt test still passes. `make check` passes. No reviewer has seen the fix.

**Options.**

1. **Accept the fix as it stands.** Slice 12's review closes on this page; the next whole-branch review (two reviewers, `docs/PLAN.md`) sees this line with everything else.
2. **Ask for one more targeted check of this line.** Both reviewers' sessions are still open; it costs one short call each.

**My recommendation.** Option 1. The fix is the one both reviewers proposed ("record provenance corresponding to the successful attempt"), it is a few lines in one function, and a test pins the retry case beside the single-attempt one. The case also needs the owner to record a new freeze between two attempts of one run, which no command does.

**If you don't decide.** The fix stays in, and slice 12 is recorded as closed by this page with the finding fixed but unreviewed.

**Decision.** <The owner's answer, with the date.>
