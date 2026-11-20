# Decision needed: accept the whole-branch review's last fix (tickers in any case)

**What's stuck.** The whole-branch review of `build/preview`. After round 2 and one targeted check, both reviewers hold H1: "no published file holds a real ticker or security name". The protocol allows no further round, so the last fix comes to you.

**Evidence.**
- **The finding, in four steps.**
  1. Round 1, reviewer B: a lower-case ticker ("Trim msft.") was neither mapped to its alias nor refused.
  2. Round 2, both reviewers: mixed case ("Trim Msft and AaPl.") was still missed. I had left mixed case out, because base64 in a committed transcript spells "Csco" by chance.
  3. Targeted check, both reviewers: my exemption for runs of 40 or more base64 characters also swallowed a readable list of tickers ("Compare Msft/Aapl/Csco/Nvda/…", "vti/vxus/bnd/msft/…").
  4. Gemini 4 Neon, asked by you after the review (`review/branch-neon.md`): the next exemption, a run with one piece that mixes digits with upper- and lower-case letters, also swallowed ordinary paths and query strings. "/reports/Portfolio2026Review/msft/aapl/nvda" was neither mapped nor refused. I reproduced it.
- **What the four have in common.** Each fix guessed from the characters what is encoded, and each guess also matched some ordinary text.
- **The fix now** (`src/casebook/published_text.py`, `provider_signature`; `src/casebook/securities/scan.py`; `src/casebook/publish/mapper.py`):
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
- **A limit I kept.** A ticker touching a letter or digit is not counted: "MSFTs", "MSFT2026", "100MSFT". That was so before this branch. Loosening the edge for upper case would raise 96 false alarms in six transcripts (each published and on the site), all on the provider's random IDs ("toolu_01LLY4Yt…"), and silencing those would mean guessing from the characters again.

**Options.**

1. **Accept the fix.** Consequence: the review closes on H1, and the branch waits only on the notes decision (`2026-11-20-follow-ups-in-owner-notes.md`).
2. **Accept it, and also count a ticker touching a digit or letter.** Consequence: provider IDs would have to be named and left out like the signature (`id`, `tool_use_id`, `requestId`, and so on). That means more fields to name, each one a place a ticker can hide.

**My recommendation.** Option 1. Nothing is guessed any more. The one field left out is named, it is provider-written, and the same characters anywhere else count.

**If you don't decide.** The whole-branch review stays open on H1, and the branch isn't ready to merge.

**Decision.** <open>
