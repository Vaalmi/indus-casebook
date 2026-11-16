# The Indus Casebook: spec

Nov 13, 2026 · @HD

From the owner.

## Outcome

An independent US advisor can see, in two minutes and with nothing to install, whether an AI assistant handles a client's messy records safely. A builder can rerun the same test with one command.

- **Whose task gets better:** an independent US advisor (RIA or small practice) deciding whether to trust an AI assistant with routine client work. Second, a reader of The Indus Signal who wants evidence in place of demos.
- **How it goes today:** advisors judge AI tools from vendor demos and vendor-run exam scores. No open set of realistic household records exists to test on. The advisor skills have no evidence behind them beyond the author's word.
- **The target:** a public site, a book of 100 invented households and 24 graded tasks, released as an unvalidated preview within 14 working weeks at 20+ hours a week.

Evidence, measured eight weeks after the preview:

- **Continue:** about 100 new Substack subscribers, 50 repo stars and 5 inbound messages from advisors or builders.
- **Change direction:** the skill does not beat the generic checklist on paired task outcomes. The book and site stay; the skills are reworked.
- **Change direction:** inbound messages are about the site and none mention the plugin. The plugin is dropped and effort moves to the site.
- **Stop:** the hand audit cannot reach zero arithmetic defects, or the CPA or EA review finds the tax answer keys unreliable beyond repair.
- **Stop:** sixteen weeks after the preview, none of the three signals has reached its target.

## Where we are

Nothing is built yet. This is a first build with three things to build on.

- **WealthContext:** an existing governed data-access server in which every figure carries a valuation date and a known-as-of date. This product reuses its two-date idea and changes nothing in it.
- **Advisor skills:** planned, not yet published. They are what the tasks test. The builder drafts the skills and the checklist; the owner edits and approves them.
- **Decisions:** scope and design were settled on 13 November 2026. The reasoning, plan, risks and prior art are in Background.

## What we need

Each bullet is something a test, a command's output or a page can show.

### The book

- One command with a seed builds the book: 100 households, ten archetypes, five pairs per archetype.
- The same seed and version produce byte-identical files.
- Every household has four source sets: custodian CSVs, portfolio-system JSON, CRM JSON with notes, and document PDFs.
- The custodian set holds positions, transactions, tax lots, beneficiaries, and settled and unsettled cash as separate fields.
- The portfolio-system set holds IPS targets, restrictions, the fee schedule and trade-date positions.
- Twenty households are featured, one pair per archetype, and their CRM notes are hand-written files in the repo.
- The other 80 households' notes come from templates; a check confirms no model-written text.
- Every history starts from opening lots dated 1 January 2025 and replays to the scenario date of 15 April 2026.
- Replay accepts only whitelisted events: buys, sells, dividends, contributions, withdrawals, RMDs, QCDs, Roth conversions, transfers, fees, RSU vesting, one stock split, and a death with basis step-up.
- An input that needs any other event is rejected with a named error.
- The security master lists 50 securities, each with an internal ID, an alias and a real ticker; every price file and chart carries the word "synthetic".
- Every observation carries a valuation date and a known-as-of date.
- Household membership, legal ownership, tax unit, billing group and disclosure permission are separate fields in the schema.
- Every planted item has a registry entry: ID, type, sources involved, justified conclusion.

### Archetypes

| # | Archetype | Core situation |
| --- | --- | --- |
| 1 | Dual-income accumulators | Backdoor Roth with an existing rollover IRA (Form 8606) |
| 2 | High-income household near thresholds | Net investment income tax, SALT limit, asset location |
| 3 | Concentrated executive | RSU basis missing on the 1099-B; IPS concentration limit |
| 4 | Pre-RMD retiree | Roth conversion with IRA basis |
| 5 | First-RMD retiree | First required distribution across several IRAs and a 401(k) |
| 6 | Established RMD retiree with QCDs | Charitable distribution evidenced only in the CRM |
| 7 | Inherited-IRA beneficiary | Ten-year rule and whether annual distributions apply |
| 8 | Recently widowed investor | Basis step-up lagging in custodian records; beneficiary updates |
| 9 | Cross-account tax-loss harvester | Replacement purchase in another account or an IRA |
| 10 | Fee and IPS drift household | Missed fee breakpoint; approved exception versus real drift |

### Checks on every household

A check command reports pass or fail for each line, per household.

- Opening units plus acquisitions minus disposals, adjusted for corporate actions, equal closing units and open lots.
- Closing cash equals opening cash plus signed settled cash flows.
- One price per ticker per date; value equals units times that price under the declared rounding.
- No lot is oversold; basis rolls forward.
- No loss sale has a repurchase within 30 days either side, across taxpayer, spouse and IRA accounts, unless planted.
- Carry-in history is present: acquisition dates, loss carryforwards, IRA basis, prior 31 December balances.
- The valuation date is never later than the known-as-of date.
- No two sources disagree without a registry entry.
- No background household crosses a drift, RMD or concentration threshold without a registry entry.

### Tax

- All 100 households have tax source documents: a composite 1099, and a 1099-R, W-2 and SSA-1099 where they apply.
- All 100 households have a computed 2025 tax summary: income, bracket, net investment income tax, loss carryforwards, IRA basis.
- Two calculators agree on each summary within 2 dollars.
- The 20 featured households have filled official forms: the 1040, and Schedules 1, 1-A, 2, 3, A, B and D and Forms 8949, 8606, 8960 and 8959, each only where the household's facts trigger it.
- Fields read back from each filled PDF equal the inputs.
- Form 8949 totals equal the closed-lot replay.
- Every parameter in the 2025 rules table cites a primary source.

### Tasks and grading

- The public suite has 24 tasks, six in each workflow: reconciliation and as-of, meeting prep and follow-up, tax-lot and RMD review, compliance review.
- Each task file has a prompt, fixtures, allowed tools, expected output, grader and justified conclusion.
- Each workflow has at least one book-level task.
- Each task on a trap has a matching task on its twin.
- Each compliance task states firm capacity, audience, channel and firm policy.
- Answer keys are produced by code that an import check shows never imports the generator.
- Every grader passes its own tests: defective outputs fail and clean controls pass.
- Follow-up tasks are graded on the CRM sandbox's final state.
- Each result records three counts: correct "unresolved", unnecessary refusal, false alarm.
- A critical fail scores zero and keeps its breakdown: fabricated figure, write to the wrong household, account number in an external message.
- A tone score comes from three model families and each vote is stored.

### Runs and results

- One command runs one task under one arm in a fresh workspace and writes a run record.
- The run record holds: dataset, task, skill, checklist and grader hashes; CLI version; requested and reported model IDs; UTC times; settings; tools and permissions; transcript; retries and errors; token use; CRM sandbox diff.
- A full Claude Code pass completes 288 runs: 24 public and 8 private tasks, three arms, three repeats.
- The results page shows paired outcomes per task, counts per workflow, and consistency across repeats.
- The results page names the tool, its version, the model and the date.

### Site, plugin and audit

- The site loads with no account and no install.
- Each featured household has a page showing the four source sets side by side, the planted item and the three truth layers. For a tax or RMD planted item the page shows the justified conclusion with its figures, before review as after.
- Each task page shows what every arm produced, with the failure marked.
- The plugin installs in Claude and runs each skill on the sample book.
- By the end of week two the site shows one pair and one task.
- An audit log for 15 hand-checked households is published with the preview.

### Aliases, private set and licences

- The default build, the site, the plugin and every release bundle show securities under aliases only.
- A build flag switches real tickers on, and no file from a default build contains a real ticker.
- A private set of 8 tasks, two per workflow, runs on background pairs and lives outside the public repo.
- The results page shows public and private outcomes side by side for each arm. For private tasks it publishes outcome counts only; their prompts, outputs and run records stay private.
- The featured pairs for archetypes 7 and 8 are absent from the repo and the site until the freeze is recorded.
- Every page of a filled return carries an "unreviewed" watermark.
- Tax-lot and RMD task pages show sources and outputs only, with no verdict and no failure marking, until review.
- The repo carries Apache-2.0 for code and CC BY 4.0 for data.

* Every run uses real-ticker mode: the files given to the AI under test carry real tickers with invented prices.
* Published run outputs and run records show aliases, with real tickers and security names mapped back before release.
* A check fails the site build if a real ticker or security name from the security master appears in any published page or file.
* Unmapped run records are kept outside the public repo.
* At least two tasks hold a security whose invented price differs sharply from any real price, and the grader fails an answer that uses a price absent from the files.

## Rules

These hold whatever happens. Each is enforced by a check that fails the build, the run or the release, not by an instruction in a prompt.

- **Sealed answer material:** the AI under test can never read the event log, the registry or an answer key. The runner refuses to start if any of them is reachable from the run workspace.
- **No future evidence:** a task never exposes an observation or a document whose known-as-of date is after the task's cutoff. The fixture loader filters every row and every document by that date.
- **Synthetic households only:** the runner and the plugin accept only household IDs listed in the book manifest. Nothing in the product reads a file from outside the book.
- **No invented disagreement:** a household with an unregistered difference between sources fails the build.
- **No household with a failed check enters a release.**
- **Independent keys:** answer-key code that imports generator code fails the build.
- **Notice everywhere:** the build fails if the README, any site page, the data metadata or any filled form lacks the notice.
- **Held items stay held:** the preview release script fails if the bundle contains a tax or RMD answer key or a combined score. A planted item's justified conclusion on a household page is not an answer key.
- **Freeze before held-out runs:** the runner refuses held-out fixtures unless the skill and grader hashes match the recorded freeze.
- **Equal arms:** the three arms share one runner configuration for model, tools, records and limits. Only the instruction differs.
- **Named results:** a result without tool, version, model and date cannot be published.
- **Synthetic prices, plain identifiers:** the security master schema allows only the listed fields, with no logos and no proprietary identifiers. Every price file carries the synthetic label.
- **No legal rulings:** the expected-output schema for compliance tasks has a field for issues for reviewer attention and none for a legal conclusion.
- **Stable IDs:** a published household or task ID never changes meaning. Corrections ship as a new version with an errata entry.

* **Aliases in public:** the site build and the release script fail if a published page or file contains a real ticker or a real security name.
* **Private set stays private:** the release script and the public repo's checks fail if a private task, its fixtures or its answer key is present.
* **Watermarked returns:** the build fails if any page of a filled form lacks the "unreviewed" watermark.
* **Licence hygiene:** a dependency check fails the build if the code imports an AGPL or GPL package. Such tools run only as separate programs.

The notice, verbatim:

> **UNVALIDATED SYNTHETIC RESEARCH PREVIEW.** Household data, prices, transactions and document contents are invented. Securities appear under invented names by default; an optional mode uses real ticker identifiers with invented prices. Tax calculations, answer keys and workflow judgments have not been independently reviewed by qualified practitioners. This is not tax, investment or compliance advice and is unsuitable for filing, trading or client decisions. No performance claims are established.

## Threat model

The product protects mainly against its own mistakes and against being mistaken for advice. A review finding about security or privacy blocks only inside this list.

In scope:

- **A wrong answer key that looks right:** the generator and the key share a mistaken rule, or a truncated history resets basis or RMD facts.
- **Answer leakage:** the AI under test reads answer material, or sees evidence dated after the task's cutoff.
- **Accidental release:** a held tax key, an unreviewed score or an unlabelled filled form is published.
- **Mistaken for advice:** an advisor treats an output, a filled form or a result as something to act on for a client.
- **Real client data:** someone points the plugin or runner at real records.
- **Real personal data in the book:** an invented name, address or number matches a real person. Identifiers use ranges that cannot be valid.
- **Instructions inside source files:** text in a note or document is data. The runner never treats fixture text as a command.

* **Tuning to the published tasks:** a tool does well on the public tasks and poorly on the private set of 8. The results page shows both.

Out of scope:

- A party who obtains the private set itself.
- Hostile contributions beyond ordinary code review.
- Other users' data: the site has no accounts and stores nothing about visitors.
- A stolen device.
- The security of the model providers and their CLIs.
- Whether real tickers with invented prices are legally clear. Aliases are the default for that reason.

## What people see

- **An advisor or reader on the site:** a banner with the notice; a list of the 20 featured households; one page per household with the four source sets side by side, the planted item and the three truth layers.
- **On a task page:** the task, what each arm produced, the failure marked, and why the justified conclusion is what it is.
- **On the results page:** paired outcomes per task, counts per workflow, consistency across repeats, and the tool, version, model and date. No combined score in the preview. Public and private outcomes appear side by side.
- **An advisor in the plugin:** a choice of sample household, the skill's output with the sources it used, and the notice. No way to load their own files.
- **A builder in the repo:** the notice at the top of the README; one command each to build the book, check it, and run a task; versioned release bundles.
- **A builder using case packets:** one zip per featured household with its source files and a separate answer sheet. Tax answer sheets are absent until review.
- **A reviewer (CPA or EA):** a packet with ten featured returns, every tax and RMD boundary case, the mapping from inputs to form lines, and five further household files.
- **After review:** a dated "tax reviewed" statement naming the scope replaces the notice on tax items, with a public errata log.

* **Securities:** invented names everywhere on the site and in the plugin.
* **Filled returns:** shown for the featured households with an "unreviewed" watermark on every page.
* **Tax-lot and RMD task pages:** sources and each arm's output only, with no verdict and no failure marking, until review.

## Running it

Scaled to a one-person open project with a static site and local runs.

- **Install:** clone the repo, run one setup command, build the book from a seed. No service to run and no key to configure.
- **Site:** static files published from a release tag to a static host.
- **Plugin:** installed in Claude from the repo; it ships with the sample book inside it.
- **Noticing a failure:** every change runs the household checks and the grader tests. A failed check blocks the release.
- **A failed run:** the runner marks the run failed with a reason and never scores it. Quota stops pause a pass, and it resumes where it left off.
- **Diagnostics for the book:** the check report names the household, the failed line, and the account, lot or file involved.
- **Diagnostics for a run:** the run record and transcript. For a task: the grader's breakdown per criterion.
- **Restore:** the book is rebuilt from its seed and version tag. Hand-written notes and scripted households live in the repo, since they cannot be regenerated. Run records and transcripts are kept as release files.
- **Rollback:** every release is tagged. Rolling back the site means publishing the previous tag.
- **Corrections:** a data or key fix ships as a new version with an errata entry.
- **Before the full runs:** confirm each provider's terms for automated runs on a consumer subscription.

* **Private set:** kept in a private repo with its own backup. The runner loads it from a path outside the public repo.
* **Real-ticker mode:** a build flag. Its output goes to a separate folder that the release script ignores. Runs read from that folder.

## Not for now

- **Importers for real custodian, CRM or tax files:** export formats are undocumented and change, and loading client data into unsupported software raises privacy obligations.
- **Published tax and RMD answer keys, and a combined score:** held until a CPA or EA has reviewed the tax work.
- **Filled returns for all 100 households:** both reviewing models judged the extra 80 not worth the build and audit cost.
- **A model leaderboard:** 24 tasks is a diagnostic suite, and scores across different CLIs do not isolate the model.
- **Codex and Antigravity runs:** added once the graders are stable.
- **API runs:** the CLI costs nothing extra during development. Revisit when quotas block repeats or reproducibility matters more.
- **Anthropic's advisor plugin as a comparison arm:** possible later, on its native host with identical evidence.
- **Tax year 2026:** a closed year has final rules. A small year-end pack follows the preview.
- **The 2,500-household book:** waits until all checks pass at that size, the hand audit shows no arithmetic defects, and the featured set has passed tax review.
- **State returns, and business, trust, foreign and derivative tax situations:** each multiplies the forms to get right.
- **529s, trusts, HSAs and donor-advised funds as standard accounts:** included only where a featured household needs one.
- **Simulating accounts from inception:** audited opening lots give the same realism at far less risk.
- **Blind practitioner review of outputs:** starts once a reviewer is on board.
- **Any use with real client data.**

* **Comparing raw files with WealthContext:** dropped, so the product stays independent of WealthContext.
* **Real tickers in public outputs:** legal clearance is unconfirmed, so aliases are the default.

## Words

One name per concept. "Site" means the web pages, because "casebook" would otherwise mean both the product and its web pages.

- **The Indus Casebook:** the whole product. Avoid: the lab, the bench, the casebook (alone).
- **Book:** the full set of synthetic households in one release. Avoid: dataset, corpus.
- **Sample book:** the 20 featured households as packaged in the plugin. Avoid: demo data.
- **Household:** one invented client unit with its people, accounts and source sets. Avoid: client, family, case.
- **Archetype:** one of the ten household templates. Avoid: persona, profile.
- **Pair:** a trap and its twin, sharing an archetype and most facts. Avoid: matched pair, couple.
- **Trap:** the household in a pair that contains a planted item.
- **Twin:** the household in a pair that is clean, a near miss or unresolved. Avoid: control.
- **Featured household:** one of the 20 with filled returns and hand-written notes. Avoid: showcase, core.
- **Background household:** one of the other 80.
- **Held-out pair:** a pair kept unpublished until the freeze.
- **Planted item:** a deliberate situation or source disagreement with a registry entry. Avoid: issue, bug, trap (for the item).
- **Registry:** the list of planted items. Avoid: manifest.
- **Source set:** one of the four groups of files per household: custodian, portfolio system, CRM, documents. Avoid: silo, feed.
- **Event log:** the generator's record of what happened. Never visible to the AI under test.
- **Truth layer:** one of three: events, source observations, justified conclusions.
- **Justified conclusion:** what the available evidence supports; it may be "unresolved". Avoid: ground truth.
- **Valuation date:** the date a figure describes.
- **Known-as-of date:** the date the figure became available. Avoid: as-of (alone).
- **Scenario date:** 15 April 2026, the day every task is set on.
- **Check:** an automated pass-or-fail test on a household. Avoid: invariant, validation.
- **Task:** one graded piece of advisor work.
- **Workflow:** one of the four groups of tasks. Avoid: family, category.
- **Answer key:** the expected result for a task, computed outside the generator. Avoid: solution, gold.
- **Grader:** the code that scores an output against the answer key. Avoid: judge (except the tone jury).
- **Critical fail:** an error that zeroes a task.
- **Arm:** one of three ways a task is attempted: basic prompt, checklist, skill. Avoid: condition, variant.
- **Checklist:** the generic advisor checklist used as the comparison arm.
- **Skill:** an advisor instruction package under test.
- **Run:** one attempt at one task under one arm. A **run record** is its stored evidence.
- **Freeze:** the recorded hashes of skills and graders before held-out pairs run.
- **Site:** the public web pages showing households, tasks and results. Avoid: casebook, viewer, explorer.
- **Plugin:** the Claude package of skills and the sample book.
- **Case packet:** a zip of one featured household's source sets.
- **Notice:** the unvalidated statement shown on every surface. Avoid: disclaimer.
- **Review:** the CPA or EA check of the tax work. Avoid: audit (reserved for the hand audit).
- **Hand audit:** the owner's line-by-line check of 15 households.
- **Preview:** release v0.1, unvalidated. **Release:** any tagged version.
- **Errata log:** the public list of corrections.

* **Alias:** the invented name a security appears under by default. Avoid: fake ticker.
* **Real-ticker mode:** the build that uses real identifiers with invented prices. Every run uses it; nothing published does.
* **Private set:** the 8 tasks that are never published. Avoid: hidden tests, held-out tasks.

## Open decisions

- [x] Choose the tax calculators and the form filler after the coverage check, within the licence rule. Chosen 13 November 2026 from probes: the in-house engine and Tax-Calculator (CC0) as the two calculators; the independent key code as the second calculator for loss carryforwards and IRA basis, which no outside tool computes; pypdf and reportlab as the form filler.
- [ ] Find the CPA or EA and agree the review scope.
- [ ] Check the USPTO trademark search, GitHub and the domain for The Indus Casebook.
