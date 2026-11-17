# Plan: The Indus Casebook

The plan for `docs/SPEC.md`, written as `docs/PROCESS.md` (Planning) describes. No code exists yet; every path below is new unless it says otherwise.

## What this builds

A seeded generator for a book of 100 synthetic households with four source sets each, checks that every household must pass, a 2025 tax layer, 24 public and 8 private graded tasks, a runner that attempts each task under three arms on Claude Code, and a public static site, a Claude plugin and versioned release bundles that show the evidence under aliases. It ends at the preview release v0.1, plus the switch that lets a later tax review release the held items. Importers, a leaderboard, other CLIs, API runs, tax year 2026 and the 2,500-household book stay out, as the spec's "Not for now" lists.

**Owner work the build depends on** (no agent can do these):

- Write the CRM notes for the 20 featured households by hand (slice 5). The builder supplies a fact sheet per household.
- Edit and approve the four advisor skills and the checklist the builder drafts (slices 2, 9, 10).
- Approve the task matrix (slice 5) and do the hand audit of 15 households (slice 12).
- Create the public and private GitHub repos, enable GitHub Pages, push branches and tags (the builder never pushes).
- Sign the `claude` CLI in on the machine that runs the tasks (it was signed out during planning), and `codex` and `agy` for the tone jury.
- Errands carried from the spec's open decisions: find the CPA or EA, check the name, and confirm each provider's terms before the full pass.

## Design

Python 3.13 managed by uv, one package `casebook` under `src/`, one `casebook` command, one check command `make check`. There is no existing code in this repo to mirror. Two conventions are carried from the owner's WealthContext (`~/projects/wealthcontext/docs/TECH_STACK.md`): uv with a lockfile, and the official MCP Python SDK for the one place a model calls a tool of ours (the CRM sandbox).

### Modules

| Module | What it is for | Uses |
| --- | --- | --- |
| `src/casebook/model/` | The types every other module trusts: household, person, account; the five separate relations (household membership, legal ownership, tax unit, billing group, disclosure permission); observation with valuation date and known-as-of date; the whitelisted event union; lot; registry entry; money as `Decimal` with the declared rounding | — |
| `src/casebook/rules/` | The 2025 rules table: every parameter with its value and a primary-source citation. Loading fails on a parameter with no citation | `model` |
| `src/casebook/securities/` | The security master (50 securities: internal ID, alias, real ticker, and no other field) and the synthetic price series, labelled "synthetic" | `model` |
| `src/casebook/generate/` | Turns an archetype and a seed, or a scripted household file, into opening lots and an event log | `model`, `rules`, `securities` |
| `src/casebook/replay/` | The ledger: applies whitelisted events to lots and cash from the opening lots to the scenario date. Any other event raises `UnsupportedEventError` naming it | `model` |
| `src/casebook/plant/` | Applies a planted item (a situation or a source disagreement) and writes its registry entry | `model` |
| `src/casebook/sources/` | The four emitters: custodian CSVs, portfolio-system JSON, CRM JSON with notes, document PDFs (statements and tax source documents) | `model`, `replay`, `plant`, `securities` |
| `src/casebook/build.py` | `casebook build --seed N [--real-tickers]`: generate, replay, plant, emit, write the manifest with file hashes | the six above, `tax` |
| `src/casebook/checks/` | The checks on every household and the check report. Reads emitted files only | `model` |
| `src/casebook/tax/engine/` | The in-house calculator: Form 1040 lines and the schedules and forms the spec lists, from tax-unit facts in the event log | `model`, `rules` |
| `src/casebook/tax/crosscheck.py` | The only module that imports Tax-Calculator. Maps tax-unit facts to its inputs and returns its figures | `model` |
| `src/casebook/tax/summary.py` | The 2025 tax summary per household, and the two-calculator comparison | `tax/engine`, `tax/crosscheck` |
| `src/casebook/tax/forms/` | Fills official IRS PDFs from a line-to-field map per form, reads fields back, stamps the "unreviewed" watermark and the notice | `tax/engine` |
| `src/casebook/keys/` | Answer keys per task, computed from the emitted files, the event log and the registry. Includes its own lot, RMD, wash-sale, loss-carryforward and Form 8606 logic | `model`, `rules` |
| `src/casebook/tasks/` | The task file type, the fixture loader that filters by known-as-of cutoff, the expected-output schemas | `model` |
| `src/casebook/crm/` | The CRM sandbox: an MCP server over a per-run copy of CRM JSON, and the diff of its final state | `model` |
| `src/casebook/graders/` | One grader per task: criteria breakdown, the three counts, critical fails. `graders/jury.py` is the tone jury and the only module that calls the jury CLIs | `model`, `tasks`, `keys` output files |
| `src/casebook/runner/` | The run workspace, the sealed preflight, the three arms, `runner/cli.py` (the only module that starts the CLI under test), the run record, the pass with pause and resume, the freeze | `tasks`, `crm` |
| `src/casebook/results/` | Turns graded run records into paired outcomes, counts per workflow and consistency across repeats | `model` |
| `src/casebook/publish/` | The alias mapper, the gates on published files, the release bundle, case packets, the review packet | `model`, `securities` |
| `src/casebook/site/` | The static site generator: Jinja2 templates and a little plain JavaScript, built from the alias-mapped bundle | `publish` output |
| `plugin/` | The Claude plugin: the skills, the sample book, and a gate that accepts only sample-book household IDs | — |
| `skills/`, `checklist/` | The four advisor skills and the checklist: drafted by the builder, edited and approved by the owner, pinned by hash | — |
| `book/scripted/` | The featured households' scripts and hand-written notes. Held-out pairs live in the private repo until the freeze | — |
| `tasks/public/` | The 24 public task files | — |

Three import contracts, enforced by import-linter in `make check`:

1. `keys` and `graders` import none of `generate`, `replay`, `plant`, `sources`, `build`, `tax.engine`. This is the spec's "generator" for the independent-keys rule.
2. `checks` imports only `model`. A check that reused the ledger would agree with the ledger's mistakes.
3. Each outside program is reached through one module: the CLI under test through `runner/cli.py`, Tax-Calculator through `tax/crosscheck.py`, the jury CLIs through `graders/jury.py` (`docs/CODE_STANDARDS.md` rule 5).

Checked against `docs/CODE_STANDARDS.md`: outside data (emitted files read back, CLI JSON, model output) is parsed at the boundary into `model` types (rule 9); every rule in the spec's "Rules" is a check that fails a build, a run or a release (rule 10), mapped in "Spec coverage" below; expected values in tests come from hand-worked cases and IRS worked examples, never from the code under test (rule 12); `make check` calls no model and no network, with a stand-in CLI in place of `claude`, `codex` and `agy` (rule 13).

**Where files go.** The private repo is a sibling folder named by `CASEBOOK_PRIVATE`.

| Path | Holds | Published |
| --- | --- | --- |
| `out/book/<version>/households/<id>/{custodian,portfolio,crm,documents}/` | The four source sets, aliases only | Yes |
| `out/book/<version>/sealed/` | Event logs, the registry | On the site only, never in a run workspace |
| `out/keys/<version>/` | Answer keys | Non-tax keys only, until review |
| `out/real/<version>/` | The real-ticker build that runs read | Never; the release script ignores it |
| `$CASEBOOK_PRIVATE/` | Private set, held-out pairs before the freeze, unmapped run records | Never |
| `out/release/<tag>/`, `out/site/` | The bundle and the site | Yes |

**New names** (none clash with the spec's "Words"): *fact sheet*, the per-household list of facts the owner writes notes from; *ID ledger*, the committed file recording what each published household and task ID means; *review packet*, the reviewer's bundle; *task matrix*, the table of which task sits on which household.

### State machines

**A household, from script to release.** `build.py` owns the state; it is recorded in the manifest.

| From | Operation (caller) | To | Refused when |
| --- | --- | --- | --- |
| — | `generate` (build) | `generated` | The household ID is already in the ID ledger with a different archetype, pair or role |
| `generated` | `replay` (build) | `replayed` | An event is outside the whitelist (`UnsupportedEventError`); a lot would be oversold; opening lots are not dated 1 January 2025 |
| `replayed` | `emit` (build) | `emitted` | A valuation date is later than its known-as-of date; a default build would write a real ticker |
| `emitted` | `check` (`casebook check`) | `passed` or `failed` | — |
| `passed` | `release` (release script) | `released` | Any gate in slice 16 fails. A `failed` household is never released |
| `released` | correction | `generated` under a new version | The same version is reused, or no errata entry exists |

**A run.** `runner` owns the state; it is recorded in the run record.

| From | Operation (caller) | To | Refused when |
| --- | --- | --- | --- |
| — | `prepare` (`casebook run`) | `ready` | The household ID is not in the book manifest; a fixture is dated after the task's cutoff; any sealed file is reachable from the workspace; the fixtures are held-out and the freeze does not match; the arm's config differs from the shared config in anything but the instruction |
| `ready` | `start` | `running` | — |
| `running` | the CLI exits cleanly, with the arm's instruction shown as loaded | `completed` | — |
| `running` | error, timeout, quota stop, or the instruction not loaded | `failed`, with the reason | — |
| `completed` | `grade` | `graded` | The task, key or grader hash differs from the one in the run record |
| `graded` | `map` (publish) | `mapped` | A real ticker or security name remains after mapping |
| `mapped` | `publish` | `published` | Tool, version, model or date is missing; the task is tax-lot or RMD and no review statement covers it (it publishes with no verdict) |

A `failed` run is never graded. A pass is a list of runs; a quota stop marks the pass `paused`. `casebook pass --resume` skips every run that reached `completed` or any state after it (`graded`, `mapped`, `published`) and starts the rest: runs never started, and `failed` runs, as a new attempt recorded under "retries" in the run record.

**The freeze and the held items.** `runner/freeze.py` and `publish` own these.

| From | Operation (caller) | To | Refused when |
| --- | --- | --- | --- |
| `unfrozen` | `casebook freeze` (owner) | `frozen`: the hashes of every skill, the checklist and every grader are recorded | Any grader self-test fails |
| `frozen` | a held-out run | runs | A skill, checklist or grader hash differs from the record |
| `frozen` | a skill or grader changes | `unfrozen` for the new hashes | Held-out results from the old freeze are mixed with new ones in one results page |
| tax items `unreviewed` | a review statement is added (owner) | `reviewed`, for the items its scope names | The statement has no date, reviewer or scope |

### Choices and why

**Settled by probes** (scripts and raw output in the session scratchpad; each is re-run as a test in the slice named).

- **The two calculators are the in-house engine and Tax-Calculator 6.9.1.** Tax-Calculator is CC0, so it may be imported. On three hand-worked 2025 cases (a high-income couple with the SALT phase-down, net investment income tax and Additional Medicare Tax; a 74-year-old with Social Security, an IRA distribution and the new senior deduction; a couple with a capped capital loss) Tax-Calculator and PolicyEngine-US 2.121.6 matched each other and my hand figures to the dollar: tax of 99,614, 14,606.56 and 28,878. PolicyEngine is AGPL, so it stays out of the build; it is a proven fallback that would run as a separate program. Turned down: `tenforty` (OpenTaxSolver, GPL), which could not express the retiree case and missed the SALT phase-down, and UsTaxes (AGPL, form coverage unconfirmed). Becomes a test in slice 7.
- **"Bracket" is the marginal ordinary-income rate, one of the seven 2025 rates, that applies to the tax unit's taxable ordinary income.** Each calculator derives it from its own taxable income and its own bracket thresholds (the rules table for the engine, Tax-Calculator's parameters for the cross-check). It is not a dollar figure, so agreement means the same rate.
- **No external calculator computes loss carryforwards or IRA basis.** For those two lines of the summary the second calculator is the independent implementation in `keys/`, checked against IRS worked examples. This meets "two calculators agree" with two in-house implementations, which is weaker than an outside tool. The owner should know; the review packet lists both lines as boundary cases.
- **The form filler is pypdf 7.1 (BSD) on the official IRS PDFs, with reportlab (BSD) for the watermark and for the documents we draw.** On the 2025 Form 1040, Schedule 1-A and Forms 8606, 8949 and 8960, pypdf filled fields, read the same values back, and a watermark was found on every page. Two findings shape slice 8: the forms carry an XFA layer that must be removed on write or some viewers show the form blank, and field names are opaque (`f1_01`), so each form needs a hand-built line-to-field map. That map is also the review packet's "mapping from inputs to form lines".
- **The licence check cannot rely on package metadata alone.** `tenforty` declares MIT and bundles GPL code. The dependency check reads declared licences and also a deny-list by name.
- **The CLI's `--restricted` mode is the planned confinement, unproven.** Claude Code 2.1.304 documents it as removing code-running tools and web fetch, ignoring user and project settings, and confining file tools to the working directory. The live test failed on sign-in ("OAuth session expired"), so slice 2 opens with a canary test: a run told to read a file outside its workspace must fail to. If it reads it, slice 2 moves runs into a container with only the workspace mounted before anything else is built on the runner. The same failed call showed the result JSON reports `is_error: true` beside `subtype: "success"`, so the runner trusts `is_error` and the exit code.

**Decided by the owner on 13 November 2026.**

- **The builder drafts the advisor skills and the checklist; the owner edits and approves them.** The spec's "Where we are" says so since 16 November 2026.
- **The site is published on GitHub Pages** from a release tag of the public repo.
- **Finding the CPA or EA and checking the name stay the owner's errands.** They gate only handing the review packet to a reviewer and the public launch under the name.

**Readings of spec lines the read-back could take two ways** (paraphrase by reviewer_b, 13 November 2026, `review/spec-paraphrase.md`, U1 to U6). The owner settled each on 16 November 2026, as stated here. The spec was edited to match on 16 November 2026, on the owner's word, for all but U3.

- **U2, the cutoff (owner: every row and document).** The fixture loader drops every observation, and every document, whose known-as-of date is after the task's cutoff. It filters rows inside a file, so a file written later never carries a late row into a workspace.
- **U3, the notice and watermark after review (owner: decide after the preview).** The spec's after-review line replaces the notice on tax items; it says nothing about the watermark. So slice 17 replaces the notice for items a review statement covers, and keeps the "unreviewed" watermark unless the owner's wording lifts it for reviewed returns. The rules as written say "whatever happens", so slice 17 does not start until the spec states the exception. Nothing before the preview depends on it.
- **U4, what is held before review (owner: the household page shows the conclusion with its figures).** A featured household's page shows all three truth layers for every planted item, tax and RMD items included: the justified conclusion as the registry states it, with the figures it rests on. A tax-lot or RMD task page shows the sources and each arm's output and nothing else: no verdict, no failure marking and no explanation of the task's expected output. See "What stays held for tax and RMD" below.
- **U5, "as triggered" (owner: only where triggered).** It applies to every schedule and form after the 1040. A featured household gets Form 8606, 8949, 8960 or 8959 only when its facts call for it.
- **U6, private runs (owner: outcome counts only).** The results page publishes outcome counts for private tasks and nothing else. Their prompts, outputs and run records stay in the private repo, since an output would show the task.
- **U1, the sixteen-week stop (owner: from the preview).** It counts sixteen weeks from the preview release. It does not change the build.

**Engineering defaults that affect a criterion, a contract, stored data, security or recovery.**

- **"Generator" means `generate`, `replay`, `plant`, `sources`, `build` and `tax.engine`.** Keys share only the types and the rules table with them. Sharing the rules table is accepted because a wrong parameter is caught by its citation and by Tax-Calculator, and a second table would double the citations to keep right.
- **Runs get file tools and the CRM sandbox, and nothing that runs code or reaches the web.** The site publishes the planted items, so a run with web access could read its own answers; a code-running tool cannot be sealed without a container. The cost is that the AI under test does lot arithmetic unaided. The owner may overrule this for a later version; it would need container isolation.
- **Each arm's instruction arrives the way a user would get it.** The skill arm loads the skill through `--plugin-dir`; the checklist arm loads the checklist as a one-file skill by the same route; the basic arm loads nothing. Model, tools, fixtures, limits and every other flag come from one shared config whose hash is in the run record. A run whose transcript does not show its instruction loaded is `failed`, never scored.
- **"No model-written text" in the 80 background households means the build calls no model and every note re-renders byte-for-byte from a named template and slot values taken from the event log.** The templates themselves are drafted by the builder and reviewed like code.
- **"Hand-written" notes are written by the owner.** Each note file carries a front-matter list of the facts it asserts. A check ties every dollar amount and date in the note to an asserted fact, and every asserted fact to the event log or a registry entry, so a hand-written note cannot add an unregistered disagreement.
- **What stays held for tax and RMD.** Held until a review statement covers them: every answer key that `keys` produces for a tax-lot or RMD task, the grader's verdict and failure marking on those tasks' outputs, the tax answer sheets in the case packets, and any combined score. Not held, by the owner's decision on U4 (16 November 2026): the registry's justified conclusion for a tax or RMD planted item, which the household page shows with its figures under the notice. A justified conclusion can state an amount that a held key also states; the owner chose the fuller page knowing that. The preview release gate tells the two apart by where a file comes from: anything from `out/keys/` for a tax-lot or RMD task, any tax answer sheet and any verdict on such a task fail the release; the registry does not.
- **"Differs sharply" means the invented price is at least three times, or at most one third of, the security's real 2025 trading range.** The cited range sits in the sealed registry entry of each of the two tasks, since the security master may hold no other field.
- **Real tickers are chosen to be scannable.** No security in the master has a ticker that is an English word or shorter than three letters, so the alias gate can match whole upper-case tokens and security names without false alarms. A test enforces it.
- **Identifiers that cannot be valid:** Social Security numbers in area 000, phone numbers 555-0100 to 555-0199, email addresses at `.example`, account numbers with an `SYN-` prefix. A check fails the build on any other shape.
- **Determinism:** each random stream is seeded from the seed and its subject (a household ID, or a security for prices and dividends), never the version, so a release changes only what its errata entry names (the owner's decision, 16 November 2026, `docs/decisions/2026-11-16-version-in-the-price-seed.md`); nothing reads the clock; JSON is written with sorted keys; PDFs and zips are written with fixed dates and IDs.
- **Money is `Decimal`.** A lint rule bans `float` in `model`, `replay`, `tax` and `keys`. Rounding is half-up to the cent, declared once in `model`.
- **Each workflow's six tasks are two trap-and-twin task pairs and two book-level tasks.** That meets "at least one book-level task" and "each task on a trap has a matching task on its twin" with 24 in all. Each private pair of tasks is one trap-and-twin task pair on a background pair.
- **The one check command is `make check`:** ruff, pyright, pytest with an 85% coverage floor, import-linter, the licence check, and the end-to-end tests (a small seeded build, the checks, a stand-in run of each arm, the site build and its gates, Playwright on the built site).
- **If the plan slips,** the cut order is the Background tab's: case packets first, then the featured set from 20 toward 16. Each cut is a decision page for the owner, since both weaken a spec line.

## Slices

One stream, in order. The week beside each slice is the Background tab's milestone it answers.

### Slice 1: Put one pair on the public site (weeks 1–2)

**Depends on:** nothing.

The thinnest path through every layer an outsider sees: one scripted pair for archetype 10 (fee and IPS drift), built by the real build command, checked, and published under aliases on GitHub Pages. It comes first because it proves the delivery route and puts the notice and alias gates in place before anything else is public.

- [ ] `make setup` on a fresh clone installs everything; `make check` passes; a pre-commit hook and a GitHub Action run it
- [x] `docs/TECH_STACK.md`, the one check command in `docs/PROCESS.md`, the hard-constraint table in `docs/CODE_STANDARDS.md`, `review.config.yaml` (owner, high-stakes paths) and the placeholders in `AGENTS.md` are filled in
- [x] `uv run casebook build --seed 2026` writes the pair's four source sets, an event log and one registry entry; a second build with the same seed is byte-identical (a test compares tree hashes)
- [x] `uv run casebook check` prints pass or fail per check per household for units, cash and valuation-date-not-after-known-as-of, and exits non-zero on a fail
- [x] The household page shows the four source sets side by side, the planted item and the three truth layers; Playwright asserts each is present and the console is clean
- [x] The build fails when the notice is removed from the README, a page or the data metadata (one test each), when a price file lacks "synthetic", and when a real ticker or security name is planted in a page
- [x] `LICENSE` (Apache-2.0) and `LICENSE-DATA` (CC BY 4.0) exist, and the dependency check fails on a planted GPL package
- [ ] Runs in the real delivery environment: the owner pushes tag `v0.0.1` and the pair's page loads from the GitHub Pages URL with no account. Publishing `v0.0.2`, then the workflow for `v0.0.1` again, restores the first version (the rollback). Spends nothing
- [x] The one check command passes

### Slice 2: Run one task for real under three arms (week 2)

**Depends on:** 1.

One reconciliation task on the trap household, attempted by Claude Code under each arm, graded, and shown on a task page. It proves the seal, the equal arms and the run record on a real CLI before any more tasks are written.

- [x] Canary test, live: a run told to read a sealed file outside its workspace, by absolute and relative path, does not obtain its content. If it does, the slice stops and switches to a container before going on
- [x] `uv run casebook run --task T-REC-01 --arm skill` creates a fresh workspace and writes a run record holding every field the spec lists; a schema test rejects a record missing any of them
- [x] The runner refuses to start, each with a named error and a test: a sealed file copied or symlinked into the workspace; an observation or document whose known-as-of date is after the cutoff; a household ID absent from the manifest
- [x] For any two arms the CLI arguments, environment and config hash are equal except the instruction (a test); a run whose transcript shows no instruction loaded is `failed`
- [x] A fixture note containing an instruction and shell characters changes neither the prompt nor the arguments (a test)
- [x] A stand-in CLI that errors, times out or reports a quota stop yields a `failed` record with the reason and no score
- [x] The grader passes its own tests: three defective outputs fail, a clean control passes, and a fabricated figure scores zero while keeping its breakdown
- [ ] The first skill (reconciliation and as-of) and the checklist are drafted and the owner has approved them
- [x] The task page shows what each arm produced with the failure marked, and names tool, version, model and date; published outputs contain no real ticker (the gate from slice 1, now on run outputs)
- [x] Runs in the real delivery environment: three live runs on the signed-in `claude` CLI, one per arm, with up to three retries, on the subscription
- [x] The one check command passes

### Slice 3: Replay every history from opening lots, and check it (week 3)

**Depends on:** 1.

- [x] Every history starts from opening lots dated 1 January 2025 and replays to 15 April 2026; a test rejects any other opening date
- [x] Each of the thirteen whitelisted events has a replay test with a hand-worked expected ledger, including the stock split and the death with basis step-up
- [x] An input needing any other event (a test uses a merger) is rejected with `UnsupportedEventError` naming the event
- [x] Carry-in history is present and checked: acquisition dates, loss carryforwards, IRA basis, prior 31 December balances
- [x] `casebook check` reports all nine checks in the spec per household. For each check a seeded defect makes that check fail and the report names the household, the line, and the account, lot or file
- [x] The wash-sale check looks 30 days either side across taxpayer, spouse and IRA accounts, and passes only when the repurchase has a registry entry
- [ ] The household checks and the grader tests run on every commit (the hook) and every push (the Action)
- [x] The one check command passes

### Slice 4: Emit the four source sets in full, with aliases and the registry (week 4)

**Depends on:** 3.

- [x] The custodian set holds positions, transactions, tax lots, beneficiaries, and settled and unsettled cash as separate fields; the portfolio-system set holds IPS targets, restrictions, the fee schedule and trade-date positions (schema tests on emitted files)
- [x] Every observation in every source set carries a valuation date and a known-as-of date; household membership, legal ownership, tax unit, billing group and disclosure permission are separate schema fields
- [x] The security master has 50 securities with exactly three fields each; the schema rejects a fourth; every price file and chart carries "synthetic"
- [x] A default build contains no real ticker in any file; `--real-tickers` writes to `out/real/` and differs from the default only in identifiers (a test maps one onto the other)
- [x] Every planted item has a registry entry with ID, type, sources involved and justified conclusion; a build with an unregistered difference between two sources fails
- [x] Identifiers match the cannot-be-valid shapes; a planted valid-looking Social Security number fails the build
- [x] The ID ledger exists; changing a published ID's archetype, pair or role fails the build
- [x] Restore: on a second clone, the same seed and version tag reproduce every hash in the manifest
- [x] The one check command passes

### Slice 5: Build the ten archetypes and the featured 20 (week 5)

**Depends on:** 4.

- [x] Each of the ten archetypes has a scripted featured pair whose planted item matches the archetype's core situation in the spec's table; every twin is clean, a near miss or unresolved
- [ ] The owner has written the CRM notes for all 20 featured households from the fact sheets; the notes check ties every amount and date to an asserted fact and every fact to the event log or the registry
- [x] The featured pairs for archetypes 7 and 8 are in `$CASEBOOK_PRIVATE` only; a test fails the build if either appears in the repo or the site before a freeze is recorded
- [ ] The task matrix places all 24 public and 8 private tasks on households, meets the per-workflow shape, and the owner has approved it
- [x] All 20 featured households pass every check; the 16 public ones have pages on the site
- [x] The one check command passes

### Slice 6: Generate the other 80 (week 6)

**Depends on:** 5.

- [ ] `uv run casebook build --seed 2026` builds 100 households: ten archetypes, five pairs each; the same seed and version give byte-identical files
- [x] Every background note re-renders byte-for-byte from its named template and slot values, and the build makes no model call (a test blocks the network and the CLIs)
- [x] No background household crosses a drift, RMD or concentration threshold without a registry entry (a seeded crossing fails the check)
- [x] All 100 households pass all nine checks; the report shows 900 passing lines
- [x] The one check command passes

### Slice 7: Compute 2025 tax for all 100 (week 7)

**Depends on:** 6.

- [x] Every parameter in the 2025 rules table cites a primary source; a parameter with no citation fails to load
- [x] All 100 households have a composite 1099, and a 1099-R, W-2 and SSA-1099 where the event log calls for one (a test compares documents present with events)
- [x] All 100 have a tax summary with income, bracket, net investment income tax, loss carryforwards and IRA basis
- [x] The in-house engine and Tax-Calculator agree on every household's summary: within 2 dollars on income, tax and net investment income tax, and on the same bracket. The engine and the `keys` implementation agree within 2 dollars on loss carryforwards and IRA basis. The report lists each household's differences
- [x] A summary altered in one field only fails the comparison, with one test per field: income, bracket, net investment income tax, loss carryforwards, IRA basis
- [x] The three hand-worked probe cases and at least one IRS worked example each for Form 8606 and the capital loss carryover are tests with literal expected values
- [x] The dependency check passes with Tax-Calculator imported and fails if PolicyEngine or `tenforty` is added
- [x] The one check command passes

### Slice 8: Fill the official forms for the featured 20 (week 8)

**Depends on:** 7.

- [x] Each featured household has a filled 1040 with Schedules 1, 1-A, 2, 3, A, B and D as triggered, and Forms 8949, 8606, 8960 and 8959 as triggered; a test asserts each trigger against the tax facts
- [x] Fields read back from each filled PDF equal the inputs; Form 8949 totals equal the closed-lot replay
- [x] Every page of every filled form carries the "unreviewed" watermark and the notice; removing either from one page fails the build
- [x] The filled forms open with visible values in a browser PDF viewer (Playwright screenshot of one page per form)
- [x] Featured household pages on the site show the returns
- [x] The one check command passes

### Slice 9: Write the keys, tasks and graders for reconciliation and for tax-lot and RMD (week 9)

**Depends on:** 8.

- [x] Twelve task files exist, six per workflow; each has a prompt, fixtures, allowed tools, expected output, grader and justified conclusion (a schema test)
- [x] Each workflow has two book-level tasks, and each task on a trap has its matching task on the twin (a test over the task matrix)
- [x] The import contract passes, and fails when a key module imports `replay` (a test)
- [x] Every key is tested against a hand-worked reference case, and key mutation tests show each grader fails when its key is altered
- [x] Every grader passes its own tests: defective outputs fail and clean controls pass
- [x] Each result records the three counts: correct "unresolved", unnecessary refusal, false alarm
- [x] Two tasks hold a security priced at least three times away from its cited real range, and their graders fail an answer that uses a price absent from the files
- [x] The tax-lot and RMD skill is drafted and approved by the owner
- [x] The one check command passes

### Slice 10: Add the CRM sandbox and the meeting and compliance tasks (week 10)

**Depends on:** 9.

- [x] Twelve more task files exist, six per workflow, with the same schema and twin tests as slice 9
- [x] Follow-up tasks are graded on the CRM sandbox's final state; the run record holds the sandbox diff
- [x] A write to another household scores zero, and so does an account number in an external message; each keeps its breakdown
- [x] Each compliance task states firm capacity, audience, channel and firm policy; the compliance expected-output schema has a field for issues for reviewer attention and rejects a legal-conclusion field
- [x] The tone score comes from three model families and each vote is stored; with stand-in CLIs a missing vote fails the grade rather than averaging two
- [x] The meeting and compliance skills are drafted and approved by the owner
- [x] Runs in the real delivery environment: one follow-up task, three live runs, shows the CRM sandbox reached from the real CLI and one live jury vote from each family
- [x] The one check command passes

### Slice 11: Keep the private set private (week 10)

**Depends on:** 10.

- [x] Eight private tasks, two per workflow, exist on background pairs in `$CASEBOOK_PRIVATE`, with graders that pass their own tests
- [x] The runner loads them from the path outside the public repo and writes their unmapped run records there
- [x] The public repo's check fails when a private task, fixture or key is copied into it (a test), and the release script fails on the same
- [ ] The private repo has a remote and a second copy; the owner confirms the backup
- [x] The one check command passes

### Slice 12: Support the hand audit, then freeze (week 11)

**Depends on:** 11.

- [x] `uv run casebook audit-sheet` writes a line-by-line worksheet for 15 households chosen by a seeded draw across all ten archetypes
- [ ] The owner has audited all 15 by hand; the audit log records each line checked and each defect, and shows zero arithmetic defects open. Any fix ships as a new book version
- [x] `uv run casebook freeze` records the hashes of every skill, the checklist and every grader, and refuses while any grader self-test fails
- [x] The runner refuses held-out fixtures with no freeze, and after any skill or grader byte changes (a test for each)
- [ ] Once the freeze is recorded, the held-out pairs move into the repo and the site, and the slice 5 test now passes with them present
- [x] The one check command passes

### Slice 13: Run the full pass and publish named results (week 12)

**Depends on:** 12. Before it starts, the owner confirms the provider's terms for automated runs on a subscription.

- [ ] `uv run casebook pass` schedules 288 runs: 24 public and 8 private tasks, three arms, three repeats
- [ ] A quota stop pauses the pass; `--resume` skips runs that are completed, graded, mapped or published and starts the rest (a test with the stand-in CLI stops at run 100 with some earlier runs already graded, and ends with 288 records and no duplicate)
- [ ] The results page shows paired outcomes per task, counts per workflow, consistency across repeats, public and private outcomes side by side for each arm, and the tool, version, model and date. It shows no combined score, and tax-lot and RMD outcomes appear as held
- [ ] A result with tool, version, model or date missing cannot be published (a test)
- [ ] Published run records show aliases only; unmapped records exist only under `$CASEBOOK_PRIVATE`; no prompt, output or run record of a private task is in the published files (a test)
- [ ] Runs in the real delivery environment: the 288 live runs on Claude Code and their jury votes, on the subscriptions, with every failed run listed with its reason
- [ ] The one check command passes

### Slice 14: Finish the site (week 13)

**Depends on:** 13.

- [ ] The site lists the 20 featured households with a page each, 24 task pages, the results page and an errata log page, and loads with no account or install
- [ ] Each task page shows the task, what every arm produced, the failure marked, and why the justified conclusion is what it is; tax-lot and RMD task pages show sources and outputs with no verdict, no failure marking and no explanation of the expected output (a test fails the site build when one carries any of the three)
- [ ] A featured household's page shows the justified conclusion with its figures for a tax or RMD planted item, the same as for any other; Playwright asserts it on one such household
- [ ] Every page carries the notice banner; invented security names appear everywhere; the alias gate passes on the whole site
- [ ] Playwright walks the home page, one household, one task and the results page at phone and desktop widths with a clean console
- [ ] The one check command passes

### Slice 15: Package the plugin (week 13)

**Depends on:** 13.

- [ ] The plugin installs in Claude from the repo and ships the sample book (the 20 featured households, aliases only) inside it
- [ ] Each of the four skills runs on a sample household and its output shows the sources it used and the notice
- [ ] The plugin accepts only household IDs in the sample book's manifest and offers no way to load other files (a test passes a path outside the book)
- [ ] Runs in the real delivery environment: the owner installs the plugin in Claude and runs each skill once
- [ ] The one check command passes

### Slice 16: Release the preview v0.1 (week 14)

**Depends on:** 14, 15.

- [ ] `uv run casebook release --preview` writes a versioned bundle and fails, each with a test, when the bundle holds: a tax or RMD answer key, a tax answer sheet, or a verdict on a tax-lot or RMD task; a combined score; a household with a failed check; a real ticker or security name; a private task, fixture or key; a filled-form page with no watermark; a file with no notice; a result with no tool, version, model or date; anything from `out/real/`
- [ ] A changed household or task ID with no new version and errata entry fails the release
- [ ] One zip per featured household holds its source files and a separate answer sheet; tax answer sheets are absent
- [ ] The review packet holds ten featured returns, every tax and RMD boundary case, the mapping from inputs to form lines, and five further household files
- [ ] The audit log for the 15 hand-checked households and the run records are in the release files
- [ ] The README opens with the notice and gives one command each to build the book, check it and run a task
- [ ] Runs in the real delivery environment: the owner pushes tag `v0.1.0`; the site serves it; a fresh clone builds the same manifest hashes from the seed and tag
- [ ] The one check command passes

### Slice 17: Let a tax review release the held items (after the preview)

**Depends on:** 16, and the owner's clarification of the notice and watermark rules (reading U3). The switch is built and tested with a fixture statement; the real statement waits for the reviewer.

- [ ] With a review statement naming a date, a reviewer and a scope, the notice on tax items in scope is replaced by the dated "tax reviewed" statement. The "unreviewed" watermark stays on every filled return unless the spec, as clarified, lifts it for reviewed returns; a test asserts whichever the spec then says
- [ ] The release script then allows the tax and RMD keys and verdicts in scope, and still refuses those outside it
- [ ] A statement missing its date, reviewer or scope is rejected
- [ ] The errata log lists each correction with its version
- [ ] The one check command passes

## Spec coverage

Every section of the spec, and where it is met. A line the plan reads in a particular way is under "Choices and why".

| Spec section | Slices |
| --- | --- |
| The book | 1 (one pair), 3 (opening lots, whitelist, named error), 4 (source sets, two dates, separate relations, registry, security master), 5 (featured 20, hand-written notes), 6 (100, templated notes, byte-identical) |
| Archetypes | 5 |
| Checks on every household | 1 (three checks), 3 (all nine), 6 (all 100) |
| Tax | 7 (documents, summary, two calculators, citations), 8 (forms, read-back, 8949 totals) |
| Tasks and grading | 2 (first task and grader), 9 and 10 (24 tasks, keys, graders, counts, critical fails, sandbox, compliance context, jury) |
| Runs and results | 2 (one run, run record), 13 (288 runs, results page) |
| Site, plugin and audit | 1 and 2 (week two), 12 (audit log), 14 (site), 15 (plugin) |
| Aliases, private set and licences | 1 (aliases, licences), 4 (real-ticker flag), 5 and 12 (held-out pairs), 8 (watermark), 9 (price tasks), 11 (private set), 13 (mapped records, side by side), 14 (no verdict) |
| Rules | Sealed answer material 2; No future evidence 2; Synthetic households only 2, 15; No invented disagreement 4; No failed check in a release 1, 16; Independent keys 9; Notice everywhere 1, 8; Held items 16; Freeze 12; Equal arms 2; Named results 2, 13; Synthetic prices 4; No legal rulings 10; Stable IDs 4, 16; Aliases in public 1, 16; Private set 11; Watermarked returns 8; Licence hygiene 1, 7 |
| Threat model | Wrong key 7, 9; leakage 2; accidental release 16; mistaken for advice 1, 8, 15; real client data 2, 15; real personal data 4; instructions in files 2; tuning to public tasks 11, 13 |
| What people see | 1, 2, 13, 14, 15, 16 (packets), 17 (after review) |
| Running it | Install 1; site and rollback 1; noticing a failure 3; a failed run 2, 13; diagnostics 3, 2; restore 4, 16; corrections 16, 17; provider terms 13; private set 11; real-ticker mode 4 |

## Review

Every slice except 5, 6 and 14 touches release and evaluation gates (the seal, the checks, the keys, the graders, the freeze, the alias and held-item gates, the plugin's household gate) and gets two reviewers. Slices 5, 6 and 14 are content and pages and get one, unless a change in them touches gate code. The final whole-branch review is always two.
