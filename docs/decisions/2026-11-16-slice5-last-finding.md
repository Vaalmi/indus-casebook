# Decision needed: accept slice 5's last fix without another review round?

**What's stuck.** Slice 5's review spent its rounds: round 1, round 2 and the one targeted check `docs/REVIEW_PROTOCOL.md` allows. reviewer_b passed the targeted check. reviewer_a passed both of its own round-2 blockers there, then found one defect the fix had introduced. The protocol sends an open blocker after the targeted check to you rather than to another round.

**The finding (reviewer_a, targeted check, `review/slice5-r3-a.md`).** A registry entry now states the first day its conclusion can be known (`known_as_of`), so a note cannot cite it earlier. The wash-sale planter dated its item by the replacement purchases only. A replacement bought *before* the loss sale (30 days either side counts) would then date the item before the sale, and a note written between the two could cite the disallowed loss. The book's own trap buys after the sale, so it is unaffected; a script that bought first would be.

**What the builder did.** Confirmed it by reading the line, and fixed it: the item is known on the later of the sale and its replacements (`src/casebook/plant/a09_wash_sale.py`). A test moves the trap's purchase before its sale and checks the item is dated by the sale, 2025-11-03 (`tests/test_plant_a09.py`, last test). `make check` passes. No reviewer has seen the fix.

**Options.**

1. **Accept the fix as it stands.** Slice 5's review closes on this page; the next whole-branch review (two reviewers, `docs/PLAN.md`) sees this line with everything else.
2. **Ask for one more targeted check of this line.** Both reviewers' sessions are still open; it costs one short call each.

**My recommendation.** Option 1. The defect is one line, the fix is the reviewer's own suggestion ("include the sale date"), and a test pins it.

**If you don't decide.** The fix stays in, and slice 5 is recorded as closed by this page with the finding fixed but unreviewed.

**Decision.** <The owner's answer, with the date.>
