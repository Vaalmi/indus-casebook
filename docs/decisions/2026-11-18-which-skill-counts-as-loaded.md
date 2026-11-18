# Decided: which skill counts as the skill arm's instruction loaded

**What's stuck.** The live full pass (`pass-20261118T080940Z-4471`), repeat 1. The plan says "A run whose transcript does not show its instruction loaded is `failed`, never scored" (Choices and why). The runner read "its instruction" as the one skill mapped to the task's workflow (`ARM_SKILLS` in `src/casebook/runner/run.py`). The spec does not say which skill: it says only that the arms share one configuration and "Only the instruction differs".

**Evidence.** Four skill-arm slots failed on all four attempts with "the transcript shows no instruction loaded": T-REC-03, T-REC-04, X-CMP-01 and X-CMP-02. In every attempt the model's first call loaded `indus-advisor:tax-lot-rmd`, a skill of the same package, for a task about an IRA distribution or an RMD, and then answered (`subtype: success`). Its answers were never graded. T-MTG-06's skill arm loaded the same skill; its first two attempts finished and were failed the same way.

**Options.**

1. **Any skill of the arm's own package counts.** The run record names the skills it loaded. Consequence: the skill arm is scored on what a user who installed the package would get, whichever skill the model picks; which one it picks becomes a result.
2. **Keep the strict check.** Consequence: these slots fail in every repeat, and the skill arm is scored only on tasks where the model picks the skill the plan expected.

**My recommendation.** Option 1.

**Decision.** Option 1 (the owner, 18 November 2026). A skill counts only under its arm's plugin name (`indus-advisor` for the skill arm, `indus-checklist` for the checklist arm); a user's own skill or another plugin's never counts, even under the same short name. The record's `skills_loaded` names them. The failed slots run again when the pass resumes.

**Found alongside.** T-CMP-06 (both arms) and T-MTG-06's last attempts ended on the CLI's 40-turn limit (`error_max_turns`). Their recorded reason, "CLI error (exit code 1): " with nothing after it, now carries the CLI's own error, "Reached maximum number of turns (40)". The limit stays at 40, as in the shared config every run of the pass has.
