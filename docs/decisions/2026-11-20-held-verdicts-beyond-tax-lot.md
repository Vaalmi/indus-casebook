# Decision needed: 11 meeting, compliance and reconciliation tasks are held as well as the six tax-lot and RMD tasks; confirm or change that

**What's stuck.** Nothing is blocked. The docs-against-code check before the whole-branch review (`review/build-preview-docs.md`, item R6) found a reading that no owner decision covers. The builder made it in slice 9, after a review finding, and later slices widened it. The preview scores 7 of the 24 public tasks, not 18.

**Evidence.** Two spec lines pull apart:
- "Held items stay held: the preview release script fails if the bundle contains a tax or RMD answer key."
- "Each task page shows what every arm produced, with the failure marked." The only exception is "Tax-lot and RMD task pages".

`is_held` (`src/casebook/site/tasks.py:76`) holds every tax-lot and RMD task, plus any task whose key computes a tax figure (`HELD_GRADERS`, `src/casebook/tasks/task.py:31`). That covers:
- reconciliation: T-REC-03 and 04 (an RMD);
- meeting: T-MTG-01 and 02 (Form 8606), 03 and 04 (net investment income tax) and 06 (tax surprises);
- compliance: T-CMP-01 and 02 (a released lot's basis and gain) and 03 and 04 (a conversion's taxable amount).

Their keys go to `out/keys/` and are never published. Their pages show no verdict, and the results page counts them as "held". Scored in the preview: T-REC-01, 02, 05 and 06; T-MTG-05; T-CMP-05 and 06. The private set's meeting and compliance counts are all "held" too.

**Options.**

1. **Keep it as built.** Consequence:
   - No published key or verdict states, or confirms, a tax figure before review.
   - The preview's skill-against-checklist comparison rests on 7 tasks: meeting has 1 and compliance has 2. The rest are scored once slice 17 releases them.
2. **Split those 11 tasks' grading.** Publish a verdict on the criteria with no tax figure (the right household, the follow-up written, the issue raised), and hold the tax-figure criteria. Consequence:
   - Most of the 11 get a partial verdict in the preview.
   - It costs grader rework, a regrade of the stored pass (no new runs), a new freeze and a review.
   - A partial verdict must not show whether the output's figure matched, which is easy to get wrong.
3. **Hold only the six tax-lot and RMD tasks.** Consequence:
   - All 18 others are scored.
   - It publishes keys and verdicts that state tax figures, against the "Held items stay held" rule as written, so it needs a spec change first.

**My recommendation.** Option 1 for the preview. It is what the held-items rule requires, and option 2 fits better beside slice 17, after the review. If 7 scored tasks feel too thin for the launch, option 2 is the one to weigh.

**If you don't decide.** The preview ships as built (option 1), and the results page says which tasks are held and why.

**Decision.** <open>
