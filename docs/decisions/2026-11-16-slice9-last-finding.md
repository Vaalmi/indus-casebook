# Decision needed: accept slice 9's last fix without another review round?

**What's stuck.** Slice 9's review spent its rounds: round 1, round 2 and the one targeted check `docs/REVIEW_PROTOCOL.md` allows. reviewer_a passed the targeted check. reviewer_b passed both of its own round-2 blockers there, then found one defect the second of those fixes had introduced. The protocol sends an open blocker after the targeted check to you rather than to another round.

**The finding (reviewer_b, targeted check, `review/slice9-t-b.md`).** The graders now refuse a price no file holds, even when a key figure happens to match it (a computed balance passed off as a fund's price). To stop arithmetic that mentions prices ("sum(price × units) + cash = $337,343.96") from reading as a price claim, the pattern was narrowed to stated prices: "price" or "priced", then "of", "was", "is", "at", "=" or ":", then the amount. But it required a space before the colon, so "The bond fund price: $337,343.96 per share." slipped through and scored 100 on T-TAX-01.

**What the builder did.** Confirmed it with the reviewer's exact probe, and fixed it: a colon or equals sign may follow "price" directly, while a word still needs a space before it (`src/casebook/graders/common.py`, `_PROSE_PRICE`). A test runs the probe and three other forms ("price=$…", "price was $…", "priced at $…"), each now scoring zero; the arithmetic case still passes, and so do the far-priced tests and the published T-REC-01 answers (`tests/test_grader_rmd_review.py`, last test). `make check` passes. No reviewer has seen the fix.

**Options.**

1. **Accept the fix as it stands.** Slice 9's review closes on this page; the next whole-branch review (two reviewers, `docs/PLAN.md`) sees this line with everything else.
2. **Ask for one more targeted check of this line.** Both reviewers' sessions are still open; it costs one short call each.

**My recommendation.** Option 1. The defect is one character class in one pattern, the fix is what the reviewer asked for ("handle adjacent punctuation without reintroducing the arithmetic false positive"), and tests pin both sides.

**If you don't decide.** The fix stays in, and slice 9 is recorded as closed by this page with the finding fixed but unreviewed.

**Decision.** <The owner's answer, with the date.>
