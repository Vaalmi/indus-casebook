# Status

<!-- Kept current as each ticket or phase lands (docs/PROCESS.md). The first thing a new session reads after AGENTS.md. -->

Building `docs/PLAN.md` on branch `build/preview`. Slice 1 is built and reviewed: one scripted pair for archetype 10 (HH-4821, the trap; HH-7350, its twin), built from a seed, checked, and rendered as a static site under aliases. Its last criterion waits on the owner pushing a tag to GitHub Pages. Slice 2 is in progress.

## Running it

```bash
make setup                          # uv sync, Playwright's Chromium, the git hook (once per clone)
make check                          # the one check command
uv run casebook build --seed 2026   # the book, into out/book/0.0.1/
uv run casebook check               # pass or fail per check per household; exits 1 on a fail
uv run casebook site                # the site, into out/site/; refuses a failed check or gate
```

Open `out/site/index.html` in a browser, or serve `out/site/` with any static server. The site is published from a release tag by `.github/workflows/pages.yml`.

## Where things stand

| Ticket or phase | State | Evidence |
| --- | --- | --- |
| Spec | approved by the owner, 16 November 2026 | `docs/SPEC.md`; read-back of the earlier text in `review/spec-paraphrase.md` |
| Plan, slices 1 to 17 | approved by the owner, 16 November 2026; reviewed | `docs/PLAN.md`; `review/plan-r1-*.md`, `review/plan-r2-*.md`, `review/plan-amend-*.md` |
| Slice 1: one pair on the public site | built, reviewed (both reviewers pass); 7 of 9 criteria ticked. Waiting on the owner: the GitHub Pages delivery and rollback, and the Action's first run, which needs a push | `make check`: 122 passed, coverage 95.27%; a fresh clone ran `make setup && make check` clean; two builds gave tree hash `9c24cbca…` both times; `review/slice1-*.md` |
| Slice 2: one task under three arms | in progress. `claude -p` answered on 16 November 2026 (exit 0, `is_error: false`), so the sealed-workspace test can run | — |

### What the owner does for slice 1's last criterion

1. Create the public GitHub repo and push this branch (or merge it first; the builder never pushes).
2. In the repo's Settings → Pages, set Source to "GitHub Actions".
3. In Settings → Environments → `github-pages` → "Deployment branches and tags", add a tag rule `v*`. Without it GitHub refuses to deploy from a tag.
4. Tag the slice 1 commit and push the tag: `git tag v0.0.1 <commit>` then `git push origin v0.0.1`. The "Publish site" workflow builds, checks and publishes it; it refuses a tag that does not match the package version (`uv version --short`).
5. Open `https://<owner>.github.io/<repo>/households/HH-4821.html` in a private window: it should load with no account, the notice banner on top.
6. Rollback: once a `v0.0.2` exists (the builder will set version 0.0.2 in a later slice's commit), push it, see the site change, then run Actions → "Publish site" → Run workflow → "Use workflow from" tag `v0.0.1`. The site's footer should read "Book 0.0.1" again.

The "Check" workflow runs `make check` on every push; its first run is the evidence for the Action half of slice 1's first criterion.

## Known gaps

- **Spec, open decisions.** Finding the CPA or EA and the name check stay open as the owner's errands (owner, 13 November 2026).
- **Spec, reading U3** (the notice and watermark after review) is deferred by the owner to after the preview; slice 17 waits on it.
- **Slice 1's featured pair has template CRM notes**, marked `"author": "template"`. The owner writes the featured households' notes in slice 5.
- **Slice 1's security master has 5 securities,** the ones the pair holds. Slice 4 brings the 50 and the test that no ticker is an English word; slice 1's test covers length and the product's own acronyms.
- **Every book version re-draws the synthetic prices,** since each random stream is seeded by the seed, the version and the subject (`docs/PLAN.md`, Choices and why). A correction version therefore changes every price and fee in the book, not only the corrected item. The owner may want the version left out of the price seed; that would change a plan line.
- **Where slice 1 differs from the plan's module table** (both reviewers saw these and raised none as a blocker): `generate` uses `replay` to know holdings for dividends and fees; `plant` uses `generate.billing`; three small modules the table does not name (`notice.py`, `seeding.py`, `published_text.py`); real security names for the alias scan live in `securities/real_names.json`, outside the three-field master.

## Review log

One line per unit of work (`docs/REVIEW_PROTOCOL.md`).

| Unit | Opened | Closed | Reviewer (session) | Rounds and verdicts | Proven blockers | Notes kept |
| --- | --- | --- | --- | --- | --- | --- |
| Plan (`docs/PLAN.md`), two reviewers because it covers release and evaluation gates | 2026-11-13 22:13 | 2026-11-13 22:22 | reviewer_a, GPT-6 Astra xhigh (`01a1d80b-c6cd-77b3-9717-b84879527a15`); reviewer_b, GPT-6.1 Sol high (`01a1d80b-c6cd-76e0-8dc5-f717c28f2d64`) | A: R1 BLOCK, R2 PASS. B: R1 BLOCK, R2 PASS | S1, from both independently: slice 7 left the bracket out of the two-calculator agreement (`docs/SPEC.md:84-85`). Confirmed by reading; fixed in slice 7 and "Choices and why" | None left. reviewer_a's two notes (what resume skips; the watermark after review) were acted on |
| Plan amendment: the owner's answers on U1 to U6 (U4 changes what is held; slices 14 and 16 gain criteria). One targeted check, same sessions, since the plan's two rounds were spent | 2026-11-16 05:06 | 2026-11-16 05:08 | reviewer_a, GPT-6 Astra xhigh (`01a1d80b-c6cd-77b3-9717-b84879527a15`); reviewer_b, GPT-6.1 Sol high (`01a1d80b-c6cd-76e0-8dc5-f717c28f2d64`) | A: PASS. B: PASS | None | None |
| Slice 1, two reviewers (publish gates, checks, licence check) | 2026-11-16 06:06 | 2026-11-16 06:21 | reviewer_a, GPT-6 Astra xhigh (`01a1e409-bb52-79c2-99d2-89101a06bcb1`); reviewer_b, GPT-6.1 Sol high (`01a1e409-bb52-7453-b035-46216c8a1271`) | A: R1 BLOCK, R2 PASS. B: R1 BLOCK, R2 BLOCK (S1 held on new evidence), targeted check of S1 PASS | All confirmed by probe and fixed in the slice 1 commit: an HTML-escaped real name passed the alias gate (both; then a tag inside a name, B round 2); a priced JSON file lacked the synthetic check (A); a parenthesised SPDX expression passed the licence check (both); the units and cash checks passed with no opening balance (both) | A: the "price" text test is broad and may refuse prose that mentions prices |

## Milestones

The dates the process is judged by. Write each once, when it happens.

- Spec approved: 2026-11-16, by the owner, with the plan. Paraphrase run 2026-11-13 by reviewer_b (GPT-6.1 Sol, high): no difference in the must-do, must-not or not-building lines; six lines it could not settle (U1 to U6). The owner settled five on 16 November 2026 and the spec was edited to say so (U1, U2, U4, U5, U6); U3 is deferred to after the preview by the owner's choice. The reader was not rerun after the edits (`docs/PROCESS.md`).
- First usable in the real environment (slice 1 merged and used by the owner): <date>
- First release to someone other than the owner: <date>
