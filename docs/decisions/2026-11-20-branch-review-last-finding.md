# Decision needed: accept the whole-branch review's last fix (tickers in any case) without another round

**What's stuck.** The whole-branch review of `build/preview`. After round 2 and one targeted check, both reviewers hold H1: "no published file holds a real ticker or security name". The protocol allows no further round, so the last fix comes to you.

**Evidence.**
- **The finding, in three steps.**
  1. Round 1, reviewer B: a lower-case ticker ("Trim msft.") was neither mapped to its alias nor refused.
  2. Round 2, both reviewers: mixed case ("Trim Msft and AaPl.") was still missed. I had left mixed case out, because base64 in a committed transcript spells "Csco" by chance.
  3. Targeted check, both reviewers: my exemption for runs of 40 or more base64 characters also swallowed a readable list of tickers ("Compare Msft/Aapl/Csco/Nvda/…", "vti/vxus/bnd/msft/…"). They were neither mapped nor refused.
- **The last fix** (`src/casebook/securities/scan.py`, `TickerFinder` and `_in_opaque_run`; the scan and the mapper share it):
  - A ticker in upper case counts everywhere, as before.
  - A ticker in any other case counts unless it sits in a run of 40 or more base64 characters that is plainly encoded: one stretch between its separators is 16 or more characters long and mixes digits with upper- and lower-case letters. Random base64 always does that; a list of tickers or words never does.
- **What it does now.** The reviewers' three cases each map every ticker to its alias, and the scan finds them (9, 10 and 10 tickers). So do "Trim Msft and AaPl." and a list ending in a year. The committed base64 line gives nothing. 5,456 published or publishable files give no false alarm: the book with its PDFs, the plugin, the published runs, the site, the README and its images.
- **Tests:** each ticker in lower, title and swapped case; the base64 line; the three long lists; the mapper on a long list. This last fix has not been seen by a reviewer.

**Options.**

1. **Accept the fix without another round.** Consequence: the review closes on H1, and the branch waits only on the notes decision (`2026-11-20-follow-ups-in-owner-notes.md`). The risk: a case nobody has thought of yet. One example is a ticker in odd case placed inside a real encoded run, which would need a hostile run output. The threat model leaves hostile contributions out of scope.
2. **Ask for one more targeted check of this fix,** outside the protocol's budget, as you did for slice 12. Consequence: about 15 minutes more, and the same question again if it finds another case.

**My recommendation.** Option 1. The fix closes every case the reviewers found, the scan stays as strict as before for upper case, and nothing published sets it off.

**If you don't decide.** The whole-branch review stays open on H1, and the branch isn't ready to merge.

**Decision.** <open>
