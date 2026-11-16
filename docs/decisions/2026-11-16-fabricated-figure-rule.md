# Decision needed: how strictly the grader counts a "fabricated figure"

**What's stuck.** Slice 2's review, finding S1 (reviewer_b; reviewer_a closed it). The spec: "A critical fail scores zero and keeps its breakdown: fabricated figure". After round 2 and the one targeted check, reviewer_b still holds S1: an answer that adds "The joint account held 48 thousand in cash" or "The household is worth 50 million" (a number with a multiplier word, no currency word) scores 100.

**Evidence.** `review/slice2-r3-b.md`: `prose_amounts("The joint account held 48 thousand in cash.")` returns `[]`. The grader already zeroes `$48,113.27`, `USD 48,113.27`, `48,113.27 dollars`, `$50 million` and `4944.13` (`tests/test_grader_fee_reconciliation.py`). Each tightening so far also zeroed an honest live answer until the answer key listed that derivation: an account's value at another quarter end, the correct fee shared across accounts, three amounts in one figure. Seven real answers are now regression tests, all scoring 100.

**Options.**

1. **Strict, as now, plus bare multipliers.** Treat "48 thousand" and "50 million" as amounts too (a small change, ready to apply), and keep widening each task's key as live runs show honest derivations. Consequence: invented amounts in prose are caught in every form but spelled-out words ("forty-eight thousand"); an honest derivation the key does not list zeroes a run until the key is widened, and each widening changes the grader's hash, so that task's live runs are redone (about two minutes for three runs).
2. **Strict for what an answer attributes to the evidence, not for prose.** A fabricated figure is one in the answer's `figures` list or its three money fields that no file holds and the key does not derive. Prose amounts are left to the criteria. Consequence: no false zeroes from prose; an invented amount that appears only in prose costs nothing. Both reviewers argued the spec needs prose covered.
3. **A model judges prose figures.** Consequence: catches any wording, but puts a model in a grader, against the plan's code-only graders and the checks' no-model rule, and adds cost.

**My recommendation.** Option 1. It is what both reviewers read the spec to require, and the false-zero risk is visible: every live answer becomes a regression test, and a zero names the figure that caused it.

**If you don't decide.** The grader stays as reviewer_a passed it (strict, without bare multipliers). Slice 2 is committed with S1 recorded as open; slices that do not touch the grader go on. Slice 9's ten more graders follow whichever rule you choose.

**Decision.** <The owner's answer, with the date.>
