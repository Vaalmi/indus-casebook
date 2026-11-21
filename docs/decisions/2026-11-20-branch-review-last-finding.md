# Decision needed: accept the whole-branch review's last fix (tickers in any case) without another round

**What's stuck.** The whole-branch review of `build/preview`, on H1: "no published file holds a real ticker or security name". After round 2, one targeted check and a second one you asked for, reviewer A closes H1 and reviewer B holds it on one case, now fixed. No reviewer has seen that last fix, so it comes to you.

**Evidence.**
- **The finding, in five steps.**
  1. Round 1, reviewer B: a lower-case ticker ("Trim msft.") was neither mapped to its alias nor refused.
  2. Round 2, both reviewers: mixed case ("Trim Msft and AaPl.") was still missed. I had left mixed case out, because base64 in a committed transcript spells "Csco" by chance.
  3. Targeted check, both reviewers: my exemption for runs of 40 or more base64 characters also swallowed a readable list of tickers ("Compare Msft/Aapl/Csco/Nvda/…", "vti/vxus/bnd/msft/…").
  4. Gemini 4 Neon, asked by you after the review (`review/branch-neon.md`): the next exemption, a run with one piece that mixes digits with upper- and lower-case letters, also swallowed ordinary paths and query strings. "/reports/Portfolio2026Review/msft/aapl/nvda" was neither mapped nor refused. I reproduced it.
  5. The second targeted check, of `8b5261f` (`review/branch-t2-a.md`, `review/branch-t2-b.md`). Reviewer A: **PASS, H1 closed**; it notes the edge rule below as a limit, not a blocker. Reviewer B: H1 held on one case, a quantity written onto the ticker: "Quantity discrepancy: custodian 100MSFT; portfolio 90MSFT." was neither mapped nor refused. A reconciliation answer could plausibly write that.
- **What steps 1 to 4 have in common.** Each fix guessed from the characters what is encoded, and each guess also matched some ordinary text.
- **The fix the reviewers checked** (`8b5261f`) (`src/casebook/published_text.py`, `provider_signature`; `src/casebook/securities/scan.py`; `src/casebook/publish/mapper.py`):
  - A real ticker counts in any case, everywhere. The scan no longer guesses what is encoded.
  - The one encoded field a published file holds is named instead: a **provider signature**, the provider's encoded seal on a thinking block in a transcript (`{"type": "thinking", "thinking": …, "signature": …}`, with base64 of 64 or more characters). The scan leaves it out, and the mapper publishes it as recorded. The thinking text beside it is scanned and mapped like any text.
  - The same characters anywhere else count: in the thinking text, in a text block, in a block of another shape, or in a signature that isn't base64.
- **Why only that field.** I scanned every published file with no exemption at all. The only chance tickers (Csco, MuB, xoM, in three transcripts) were all thinking-block signatures.
- **What it does now.**
  - Gemini's three cases map every ticker to its alias, and the scan finds them.
  - The reviewers' long lists and "Trim Msft and AaPl." are still found.
  - The committed signatures give nothing.
  - 5,482 published or publishable files give no false alarm: the book with its PDFs, the plugin, the skills, the tasks, the published runs, the site, the audit sheet, the README and its images.
- **Tests:** Gemini's three cases; the signature by where it sits, escaped slashes included; the same characters in five other places; the mapper on a path and on a thinking block. Each failed on the old code except the non-base64 signature, which the old code already scanned.
- **The last fix, for reviewer B's case** (the commit that records this page; unreviewed). A token that is digits and then a ticker counts: "100MSFT", "90msft", "1,000msft", "2.5Aapl". The mapper writes "custodian 100 Orrin Software Group". A longer token is still not a ticker: "x100MSFT", "toolu_01MSFT2". The 5,482 files still give no false alarm. Its two tests failed on `8b5261f`.
- **A limit I kept.** A ticker with a letter or digit after it is not counted: "MSFTs", "MSFT2026". That has been so since slice 4, and neither reviewer holds it. Loosening the edge for upper case would raise 96 false alarms in six transcripts (each published and on the site), all on the provider's random IDs ("toolu_01LLY4Yt…"), and silencing those would mean guessing from the characters again.

**Options.**

1. **Accept the last fix without another round.** Consequence: the review closes on H1, and the branch waits only on the notes decision (`2026-11-20-follow-ups-in-owner-notes.md`).
2. **Ask reviewer B for one more targeted check of the quantity fix.** Consequence: about 15 minutes, outside the protocol's budget again.
3. **Also count a ticker with a letter or digit after it.** Consequence: provider IDs would have to be named and left out like the signature (`id`, `tool_use_id`, `requestId`, and so on). That means more fields to name, each one a place a ticker can hide.

**My recommendation.** Option 1. Reviewer A passed the fix it checked, and the last fix is narrow: it widens what counts, so it can only add findings, and it adds no false alarm. Nothing is guessed from the characters any more.

**If you don't decide.** The whole-branch review stays open on H1, and the branch isn't ready to merge.

**Decision.** Option 1, accept the last fix (`018e8cc`) without another round (the owner, 20 November 2026: "Yes, as recommended"). The whole-branch review closes on H1. The limit above stays: a ticker with a letter or digit after it is not counted.
