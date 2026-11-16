# Status

<!-- Kept current as each ticket or phase lands (docs/PROCESS.md). The first thing a new session reads after AGENTS.md. -->

Building `docs/PLAN.md` on branch `build/preview`. Slices 1 to 4 are built and reviewed (commits `494098b`, `359e56b`, `f0cdc5a`, and slice 4's). Slice 1: one scripted pair for archetype 10 (HH-4821, the trap; HH-7350, its twin), built from a seed, checked, and rendered as a static site under aliases. Slice 2: one reconciliation task, T-REC-01, run live on the signed-in `claude` CLI under the three arms, graded, and shown on a task page. Slice 3: every whitelisted event replays against a hand-worked ledger, and `casebook check` runs all nine checks of the spec on every household. Slice 4: the four source sets in full (beneficiaries, restrictions, dates on every observation), 50 securities, identifiers in ranges that cannot be valid, the ID ledger, and a build that refuses an unregistered difference between two sources. Each of slices 1 to 3 has a criterion waiting on the owner, and one decision waits on the owner (below). On 16 November 2026 the owner decided that a new version re-draws no price (option 2) and set the models' efforts; the version left the price and dividend seeds, which re-drew the book once (the trap's overbilling is now $290.25), and T-REC-01 was rerun live under all three arms. Next: slice 5, whose CRM notes for the featured households the owner writes.

## Running it

```bash
make setup                          # uv sync, Playwright's Chromium, the git hook (once per clone)
make check                          # the one check command
uv run casebook build --seed 2026   # the book, into out/book/0.0.1/; refuses an ID the ledger contradicts,
                                    # a valid-looking identifier, a real ticker, or an unregistered difference
uv run casebook check               # nine checks per household, pass or fail; exits 1 on a fail
uv run casebook site                # the site, into out/site/; refuses a failed check or gate

# Runs (the real CLI; CASEBOOK_PRIVATE is a folder outside this repo for unmapped records)
uv run casebook build --real-tickers                     # the build runs read, into out/real/0.0.1/
CASEBOOK_PRIVATE=../indus-casebook-private uv run casebook canary
CASEBOOK_PRIVATE=../indus-casebook-private uv run casebook run --task T-REC-01 --arm skill
```

`casebook run` writes the mapped record and transcript to `published/runs/` and the reconciliation key to `published/keys/`; both are committed release files, so a tag rebuilds the task page.

Open `out/site/index.html` in a browser, or serve `out/site/` with any static server. The site is published from a release tag by `.github/workflows/pages.yml`.

## Where things stand

| Ticket or phase | State | Evidence |
| --- | --- | --- |
| Spec | approved by the owner, 16 November 2026 | `docs/SPEC.md`; read-back of the earlier text in `review/spec-paraphrase.md` |
| Plan, slices 1 to 17 | approved by the owner, 16 November 2026; reviewed | `docs/PLAN.md`; `review/plan-r1-*.md`, `review/plan-r2-*.md`, `review/plan-amend-*.md` |
| Slice 1: one pair on the public site | built, reviewed (both reviewers pass); 7 of 9 criteria ticked. Waiting on the owner: the GitHub Pages delivery and rollback, and the Action's first run, which needs a push | `make check`: 122 passed, coverage 95.27%; a fresh clone ran `make setup && make check` clean; two builds gave tree hash `9c24cbca…` both times; `review/slice1-*.md` |
| Slice 2: one task under three arms | built; 10 of 11 criteria ticked. Waiting on the owner: approval of the first skill and the checklist, and a decision on finding S1 ([how strictly the grader counts a fabricated figure](decisions/2026-11-16-fabricated-figure-rule.md)); reviewer_a passes the slice, reviewer_b holds S1 only | Live canary on `claude` 2.1.304 (Read by absolute and relative path and Grep on the parent, each refused by `--restricted`); three live runs of T-REC-01 (12:10 to 12:12 UTC), one attempt each, all 100, each arm loading only its own instruction; `make check`: 233 passed, coverage 94.19%; `review/slice2-*.md`. After the price-seed decision, rerun on the re-drawn book at `--effort high` (13:58 to 13:59 UTC): one attempt each, all 100, each finding the $290.25 overbilling |
| Slice 3: replay every history and all nine checks | built, reviewed; 7 of 8 criteria ticked. Waiting on the owner's first push: the Action half of "the checks run on every commit and every push" (the hook half runs on every commit) | `make check`: 286 passed, coverage 92.18%; `casebook check`: 18 lines, 18 pass, on the default and the real-ticker builds; `review/slice3-*.md` |
| Slice 4: the four source sets in full, aliases and the registry | built, reviewed (both reviewers pass); 9 of 9 criteria ticked | `make check`: 369 passed, coverage 92.47%; both builds: 2 households, 42 files, `casebook check` 18 of 18 pass each; a second clone of the slice's tree rebuilt with seed 2026 gave a byte-identical manifest and `shasum -c` confirmed all 41 hashes; `review/slice4-*.md` |

### What the owner does for slice 1's last criterion

1. Create the public GitHub repo and push this branch (or merge it first; the builder never pushes).
2. In the repo's Settings → Pages, set Source to "GitHub Actions".
3. In Settings → Environments → `github-pages` → "Deployment branches and tags", add a tag rule `v*`. Without it GitHub refuses to deploy from a tag.
4. Tag the slice 1 commit and push the tag: `git tag v0.0.1 <commit>` then `git push origin v0.0.1`. The "Publish site" workflow builds, checks and publishes it; it refuses a tag that does not match the package version (`uv version --short`).
5. Open `https://<owner>.github.io/<repo>/households/HH-4821.html` in a private window: it should load with no account, the notice banner on top.
6. Rollback: once a `v0.0.2` exists (a correction release; since the owner's decision a version changes only what its errata entry names), push it, see the site change, then run Actions → "Publish site" → Run workflow → "Use workflow from" tag `v0.0.1`. The site's footer should read "Book 0.0.1" again.

The "Check" workflow runs `make check` on every push; its first run is the evidence for the Action half of slice 1's first criterion.

### What the owner decides and approves

**Decide** [how strictly the grader counts a fabricated figure](decisions/2026-11-16-fabricated-figure-rule.md) (one page; my recommendation is option 1).

**Approve the skill and the checklist:**

1. Read and edit the drafts: the skill `skills/indus-advisor/skills/reconciliation-as-of/SKILL.md` and the checklist `checklist/indus-checklist/skills/advisor-checklist/SKILL.md`. The checklist is deliberately generic; it is the comparison arm. The skill names billing groups against signed agreements among its fee steps, which is close to T-REC-01; you may want it more general.
2. Say "approved" (with your edits made). The builder then drops "DRAFT" from both `plugin.json` descriptions, and, if either text changed, reruns that arm live: `CASEBOOK_PRIVATE=../indus-casebook-private uv run casebook run --task T-REC-01 --arm skill` (and `--arm checklist`). The run records carry each package's hash, so a result is always tied to the text it ran with.

## Known gaps

- **Spec, open decisions.** Finding the CPA or EA and the name check stay open as the owner's errands (owner, 13 November 2026).
- **Spec, reading U3** (the notice and watermark after review) is deferred by the owner to after the preview; slice 17 waits on it.
- **Slice 1's featured pair has template CRM notes**, marked `"author": "template"`. The owner writes the featured households' notes in slice 5.
- **The 45 securities slice 4 added are held by no household yet;** slices 5 and 6 use them. A builder subagent chose them; the English-word test reads web2 (1934) plus a short list of modern words found in review (`vig`, which retired VIG for VYM). No web search was made for real firms named like the invented families (Larkspur, Fernhollow, Brackwater, Wexcombe, Ridgeholm).
- **"Every chart carries synthetic" has nothing to apply to yet:** the site draws no charts. Every price file row carries the label.
- **The published T-REC-01 runs read the book before slice 4's additions** (beneficiaries, tax IDs on contacts, dates on price rows, a restriction on the twin). Their dataset hash is not the current manifest's; the figures they rest on are unchanged, and `make check` grades their answers against the current book. They will be rerun once slice 5's notes for HH-4821, which the owner writes, settle its files.
- **The household page shows beneficiaries and restrictions only as linked files,** not in its summary tables.
- **The ID ledger is written by hand** (`book/id_ledger.json`): HH-4821, HH-7350 and T-REC-01. The build checks households against it and `make check` checks task files; slice 16's release gate should refuse a published ID the ledger lacks.
- **"Sources agree" compares the facts two sources share today** (holdings, cash, accounts and owners, people, beneficiaries, householding against billing groups, statement totals, holdings, cash, owners, registration and activity). A fact a later slice puts in two sources needs its comparison added.
- **The version left the seed on 16 November 2026** ([the owner's decision](decisions/2026-11-16-version-in-the-price-seed.md)). That re-drew every price once, under version 0.0.1 (nothing is released). The seven earlier live answers are graded against a copy of the files they read (`tests/fixtures/live/HH-4821-first-draw/`); the three published answers are graded against the current book, so a change that moves their figures fails `make check`. The superseded published runs and their key are in `$CASEBOOK_PRIVATE/superseded-mapped/first-draw/`.
- **Models and efforts, set by the owner on 16 November 2026:** the runs pass `--effort high` to `claude` (Opus 5.5); reviewer_b and the other Sol roles run GPT-6.1 Sol at xhigh; the `agy` entry is Gemini 4 Carbon at high, which no role uses until the tone jury (slice 10). reviewer_a stays GPT-6 Astra at xhigh, and the builder role's roster entry stays Opus 5.5 at xhigh (the owner named neither). The `claude` CLI does not echo the effort in its log, so a run's recorded arguments are the evidence; `ask.mjs` checks Sol's effort in the Codex log on each review.
- **The seven events slice 3 added are tested at the replay boundary but not yet end to end.** No household uses them, so the lots check's paths for splits, moves in kind and step-ups (`checks/lots.py`, 62% covered) and the custodian rows for those events (`sources/transactions.py`, 61%) have not run on an emitted book. Slice 5's archetypes (RMDs, QCDs, Roth conversions, RSUs, a death) exercise them; a defect there would surface as a failed check on a built household.
- **The fabricated-figure rule is strict, by the reviewers' reading of the spec.** Every amount an answer states as money, prose included, must be in the household's files or among the figures the task's key derives; a derivation the key does not list counts as fabricated and zeroes the run. Live runs turned up three honest derivations (an account's value at another quarter end, a fee shared across accounts, several amounts in one figure); the key now lists them and the answers are regression tests. Others will surface on later tasks; each needs the key widened. The owner may prefer a looser rule (only figures an answer attributes to a file); that would change what the spec's "fabricated figure" means in practice.
- **The six earlier live runs of T-REC-01 are not published.** They were graded under graders since corrected (a false fabricated-figure zero, docked dates, then the stricter rule); their records stay in `$CASEBOOK_PRIVATE`. The published three are the runs under the final grader.
- **Published transcripts omit the files a run read as base64** (the statement PDFs), with a note in their place: they carry real tickers and cannot be mapped in place. The book publishes the same documents under aliases.
- **`$CASEBOOK_PRIVATE` is a plain folder,** `../indus-casebook-private`, until slice 11 makes it a private repo with a backup.
- **Slice 3 changed the book's files** under the same version 0.0.1 (nothing is released yet): the custodian's transactions gain a `lot_id` column and one row per account an event touches; new `custodian/realized_lots.csv` and `portfolio/tax_profile.json`; tax lots listed on the prior 31 December too; each statement states its total in one line; registry entries name the records they are about (`references`), and every check that accepts an entry requires it to name the specific records. The generator does not yet produce the seven events slice 3 added (RMD, QCD, Roth conversion, transfer, RSU vesting, split, death); slice 5's archetypes will use them.
- **The CLI's default model was `claude-fable-5-1`;** the shared configuration pins `claude-opus-5-5`, and every run's reported model confirms it.
- **Where slice 1 differs from the plan's module table** (both reviewers saw these and raised none as a blocker): `generate` uses `replay` to know holdings for dividends and fees; `plant` uses `generate.billing`; three small modules the table does not name (`notice.py`, `seeding.py`, `published_text.py`); real security names for the alias scan live in `securities/real_names.json`, outside the three-field master.

## Review log

One line per unit of work (`docs/REVIEW_PROTOCOL.md`).

| Unit | Opened | Closed | Reviewer (session) | Rounds and verdicts | Proven blockers | Notes kept |
| --- | --- | --- | --- | --- | --- | --- |
| Plan (`docs/PLAN.md`), two reviewers because it covers release and evaluation gates | 2026-11-13 22:13 | 2026-11-13 22:22 | reviewer_a, GPT-6 Astra xhigh (`01a1d80b-c6cd-77b3-9717-b84879527a15`); reviewer_b, GPT-6.1 Sol high (`01a1d80b-c6cd-76e0-8dc5-f717c28f2d64`) | A: R1 BLOCK, R2 PASS. B: R1 BLOCK, R2 PASS | S1, from both independently: slice 7 left the bracket out of the two-calculator agreement (`docs/SPEC.md:84-85`). Confirmed by reading; fixed in slice 7 and "Choices and why" | None left. reviewer_a's two notes (what resume skips; the watermark after review) were acted on |
| Plan amendment: the owner's answers on U1 to U6 (U4 changes what is held; slices 14 and 16 gain criteria). One targeted check, same sessions, since the plan's two rounds were spent | 2026-11-16 05:06 | 2026-11-16 05:08 | reviewer_a, GPT-6 Astra xhigh (`01a1d80b-c6cd-77b3-9717-b84879527a15`); reviewer_b, GPT-6.1 Sol high (`01a1d80b-c6cd-76e0-8dc5-f717c28f2d64`) | A: PASS. B: PASS | None | None |
| Slice 1, two reviewers (publish gates, checks, licence check) | 2026-11-16 06:06 | 2026-11-16 06:21 | reviewer_a, GPT-6 Astra xhigh (`01a1e409-bb52-79c2-99d2-89101a06bcb1`); reviewer_b, GPT-6.1 Sol high (`01a1e409-bb52-7453-b035-46216c8a1271`) | A: R1 BLOCK, R2 PASS. B: R1 BLOCK, R2 BLOCK (S1 held on new evidence), targeted check of S1 PASS | All confirmed by probe and fixed in the slice 1 commit: an HTML-escaped real name passed the alias gate (both; then a tag inside a name, B round 2); a priced JSON file lacked the synthetic check (A); a parenthesised SPDX expression passed the licence check (both); the units and cash checks passed with no opening balance (both) | A: the "price" text test is broad and may refuse prose that mentions prices |
| Slice 2, two reviewers (the seal, the runner, the grader, the gates) | 2026-11-16 06:37 | open: S1 awaits the owner's decision (2026-11-16 07:15) | reviewer_a, GPT-6 Astra xhigh (`01a1e426-4923-7003-86f6-70aaba4bb447`); reviewer_b, GPT-6.1 Sol high (`01a1e426-4913-7070-9ebe-8b2a3b261fc5`) | A: R1 BLOCK, R2 BLOCK (S1, S2 held; S8 new), targeted check PASS. B: R1 BLOCK, R2 BLOCK (S1, S2 held; N1 new), targeted check BLOCK (S1 held) | All confirmed by probe and fixed in the slice 2 commit: fabricated figures were checked only in the `figures` list, then missed prose amounts without a dollar sign (S1, both; still held by B for bare multipliers); a linked source file, then a linked household folder, was read (S2, both); an alias book ran as if real (A-S3, B-S4); the key read a household before its manifest check (A-S4, B-S3); the tag build had no run records (S5, both); a Skill call without a result counted as loaded (A-H1); a CLI that could not start raised (A-D1); published transcripts carried real tickers inside base64 PDFs (A-S8, B-N1). S6, the owner's approval, is the owner's step | A: the outside-program test had a dead branch (fixed). B: the grade used the key held in memory (now re-hashed from files) |
| Slice 3, two reviewers (the nine checks are release gates) | 2026-11-16 07:20 | 2026-11-16 07:43 | reviewer_a, GPT-6 Astra xhigh (`01a1e44d-efcd-7053-8879-1825da31be5b`); reviewer_b, GPT-6.1 Sol high (`01a1e44d-efe0-7a81-8119-d6296b2c975f`) | A: R1 BLOCK, R2 BLOCK (S6 held; D2 new), targeted check PASS. B: R1 BLOCK, R2 BLOCK (S5 new), targeted check PASS | All confirmed by probe and fixed in the slice 3 commit: duplicate rows in the price series collapsed before checking (A-S5, B-S1); carried-in entries passed without amounts (A-S4, B-S2); cash compared one way only (B-S3); retained shares of a partly sold purchase missed as replacements (B-S4), then shares already sold counted as replacements (A-D2); the wash-sale check trusted the gain column (A-S1, B-D1); one registry entry excused every wash sale (A-S2); spouses filing apart missed (A-S3); statements compared by total only, then without price and cash (A-S6, B-S5); a zero distribution met an RMD (A-S7); a cash transfer failed for blank units (A-D1) | None |
| Slice 4, two reviewers (release gates, identifiers, the registry); also covers the owner's decisions of 16 November 2026 (`e6aafb1`). First run of reviewer_b at xhigh: `ask.mjs` verified the Codex log shows `gpt-6.1-sol` at xhigh | 2026-11-16 14:14 | 2026-11-16 14:40 | reviewer_a, GPT-6 Astra xhigh (`01a1e4b5-a630-75d2-91dd-12873f1f39ca`); reviewer_b, GPT-6.1 Sol xhigh (`01a1e4b5-a630-7a10-a661-5130de8ab5b0`) | A: R1 BLOCK, R2 BLOCK (D1 new), targeted check PASS. B: R1 BLOCK, R2 BLOCK (S1 new, D2 new), targeted check PASS | All confirmed by probe and fixed in the slice 4 commit: a bare nine-digit tax ID and a dotted phone passed the build (A-S1, B-S1; then a dotted phone before a full stop, B round 2); portfolio prices, beneficiaries and statement activity were not compared across sources (A-S2, B-S2); VIG is a dictionary word (A-S3); a repeated statement row crashed the check and left the refused build's output (A-D1, B-D2, round 2) | B: the tech-stack line still put the version in the seed (fixed) |


## Milestones

The dates the process is judged by. Write each once, when it happens.

- Spec approved: 2026-11-16, by the owner, with the plan. Paraphrase run 2026-11-13 by reviewer_b (GPT-6.1 Sol, high): no difference in the must-do, must-not or not-building lines; six lines it could not settle (U1 to U6). The owner settled five on 16 November 2026 and the spec was edited to say so (U1, U2, U4, U5, U6); U3 is deferred to after the preview by the owner's choice. The reader was not rerun after the edits (`docs/PROCESS.md`).
- First usable in the real environment (slice 1 merged and used by the owner): <date>
- First release to someone other than the owner: <date>
