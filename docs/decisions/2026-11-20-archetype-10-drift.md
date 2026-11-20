# Decision needed: archetype 10 plants the missed fee breakpoint but not "approved exception versus real drift"

**What's stuck.** Slice 5's first criterion, which I have unticked: "Each of the ten archetypes has a scripted featured pair whose planted item matches the archetype's core situation in the spec's table". The docs-against-code check before the whole-branch review (`review/build-preview-docs.md`, item B8) found that archetype 10 meets only half of its line. Nothing else is blocked.

**Evidence.**
- The spec's table, row 10: "Fee and IPS drift household | Missed fee breakpoint; approved exception versus real drift".
- `src/casebook/plant/a10_fee_breakpoint.py` plants only the breakpoint: a signed householding agreement that the billing ignores. The featured twin HH-7350 is a billing near miss.
- No household has an IPS exception or a drift. `portfolio/ips.json` holds asset classes, targets, restrictions and a concentration limit, with no exception record. The background generator keeps every weight within five points of its target, so nothing drifts (`generate/background/common.py:408`).
- For comparison, archetype 2's SALT limit appears only in the conclusion's prose, because the book has no state taxes (STATUS, "The book's tax simplifications"). That is already a declared simplification.

**Options.**

1. **Ship the preview as built and add the drift item in the next book version.** The item: an IPS exception approved in the CRM on one pair, and real drift with no approval on its twin.
   - The preview's archetype 10 is the fee breakpoint only. STATUS and the household page say so.
   - The next version (0.0.2) ships with an errata entry, and the tasks that read archetype 10 households are run again then.
2. **Add it before the preview.** That means a new planted item on HH-4821 and HH-7350 (or a second pair), a new registry entry and a rebuild.
   - Every task whose fixtures include those households, or the whole book, would have to run again. That includes T-REC-01, 02 and 05, T-CMP-05 and the book-level sweeps: well over 100 live runs on your subscription, then a regrade, before tagging.
3. **Narrow the spec's row 10 to the missed fee breakpoint.** The book then meets it as built, and the drift case is dropped.

**My recommendation.** Option 1. The breakpoint already gives archetype 10 a real trap-and-twin pair. Adding drift now means rerunning most of the pass just before the tag, while a new book version is the route the spec already gives for corrections.

**If you don't decide.** The preview ships as built (option 1's first half), and slice 5's first criterion stays unticked.

**Decision.** <open>
