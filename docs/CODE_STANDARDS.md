# Code standards

The rules for code in Indus Casebook (Python 3.13, `docs/TECH_STACK.md`). A rule in the hard-constraint table below can block a review (`docs/REVIEW_PROTOCOL.md` §3); every other rule is guidance a reviewer may note.

## General

1. Keep it simple. Don't build for a need the spec doesn't state.
2. Comments only when the code can't say it: why, not what.
3. Handle an error only where there is something useful to do with it. No defensive code for states that can't happen.
4. Code you add or change follows these standards. Don't clean up unrelated code in the same change, even in the same file: note it in the review log instead.

## Structure

5. **One way to do each thing.** Each outside service is reached through one module, which holds its address and settings. Nothing else reaches it.
6. **Each module has one job, and its name says what it is.** A helper two modules need goes in a module of its own. No circular imports.
7. **Name a shared literal once,** in the module that owns it.
8. **Use the framework's own way** before writing your own. Check the documentation for the installed version.
9. **Make illegal states unrepresentable.** Parse outside data at the boundary into types the rest of the code can trust.
10. **The code enforces every business rule** in the spec, whatever a model, a user or a client does. A prompt is never the only guard.

## Tests

11. Tests check what a user or caller can observe, so they fail when that behavior breaks and keep passing when only the internals change.
12. Expected values come from the spec, a worked example or a known-good literal, never recomputed the way the code does.
13. No real model, network or outside service in the checks. Use the stand-ins.
14. **A gate on published content is tested in every form the content takes.** Its test plants what it refuses in each form of `tests/forms.py` (`FORMS`): a file kind, a container, an encoding, page source as well as visible text, a folder depth, a letter case. A form a review finds goes into `FORMS`, so every gate's test meets it, not into a one-off test for the gate that missed it.
15. **A fix answers the rule a finding breaks, not the probe.** Before fixing a confirmed blocker, write down the rule it breaks and the other inputs that break it the same way; test those too. A fix that adds an exemption or a special case names, in the round-2 prompt, what else the exemption lets through.

## Lessons

Every mistake the owner has corrected, so a repeat is visible. A lesson is guidance a reviewer may note. It becomes a hard constraint only when the owner marks it so, in the table below.

"When" names the kind of situation, so the lesson fires on a different case: not "the invoice export", but "any export another system imports". "Observed result" is what happened the last time that situation came up (`docs/PROCESS.md`, Correcting): "not yet observed" until it does.

| Lesson | When | From (the correction, with its date) | Prevention | Observed result |
| --- | --- | --- | --- | --- |
| A gate on published content misses a form the content takes (37 misses: an HTML entity, a tag inside a name, a comment in the page source, a Markdown fence, a zip and a zip in a zip, base64 in JSON, a JSON list, a CSV cell, a flattened PDF, a folder not walked, lower and mixed case, a glued quantity) | Any check that refuses content before it is published: the site's gates, the release's, the sample book's, the private set's | Reviews of slices 1, 2, 4, 5, 8, 9, 11, 13, 14, 15 and 16 and the whole branch (`docs/STATUS.md`, review log); the `correct` pass of 23 November 2026 | Rule 14. A check: `tests/forms.py` and the forms tests in `tests/test_gates.py` and `tests/test_release_gates.py`, in `make check`. Against the site's gate before the whole-branch review (`d1479d1^`) it fails on a ticker in lower and mixed case, the branch review's H1. On its first run it found seven forms the release's gate still let a held key through in (a CSV cell, a PDF's text, a string inside JSON, base64 in JSON, a tag inside each word, lower and mixed case); the gate now reads every text the shared reader gives and folds case and spacing (`publish/release_gates.py`), and the published `v0.1.0` bundle passes it with no problem | A catch: the check found seven open forms the day it was written (23 November 2026). Slice 17 (23 November 2026): the matrix did not yet hold a held verdict or a combined score, and reviewers found both slipping through as text (round 1, S3) and a score as spaced JSON (round 2, D4); both are now contents of the matrix, so the instruction reached the builder but the matrix had to grow by what the gate refuses, not only by where it hides |
| A fix for a confirmed blocker fixes the probe, not the rule, and brings in a new defect (about 20, among them every finding still open after a targeted check: slices 5, 9, 12, 13, 15 and the branch) | Fixing any confirmed review finding | The review log, slices 3 to 16 and the whole branch; the `correct` pass of 23 November 2026 | Rule 15, a written rule for the builder and the reviewer: judgment no check can make | Escaped twice in slice 17 (23 November 2026), with the rule in the builder's context (the builder wrote it that day): a fix for round 1's S3 left a run record to the record checks by its run ID alone, which let a graded copy of it through (round 2, S3); new code let a packet ship any `tax-answer-sheet.json` unchecked (round 2, D3). The reviewers caught both, citing the rule. The cause is reopened: the rule reached the builder and did not change what was written |
| A run's state or provenance is read at the wrong moment: after the CLI ended, from an earlier attempt, before a resume, across an interrupted regrade (8) | Any step that can stop part-way: a quota stop, a retry, a resume, a regrade | Slices 12 and 13, the whole branch (P14, P15, P20 in the `correct` pass of 23 November 2026) | Written: a test stops the step at each point it can stop and resumes it; state is read when it is used | Not yet observed |
| A test shares the code's derivation or assumes its state, so it agrees with the code's mistake (5) | Any test of a key, a calculation or a stored record | Slices 2, 6, 7 and 16, the derivation fix (the `correct` pass of 23 November 2026) | Rule 12 (hard, review only); no check can tell a recomputed value from a literal | Escaped 5 times in this build; rule 12 stays the guard |
| The copier and the gate walk different sets of files, so a file the gate never read is published (4) | Anything that copies files into a site, a bundle or a sample book and gates them | Slices 8, 11, 13 and 16 | The gate reads what the copier wrote: the site's gates run on the staging folder (`publish/site_build.py`), the release's on the staged bundle | No escape since slice 16 |
| A list kept by hand falls out of step with what it lists (3) | A word list, a list of compared facts, a layout literal written in two places | Slices 4 and 5 (`vig` missing from the word list; comparisons not added for new facts); the slice 16 note on `release.py` and `release_gates.py` | Rule 7: name a shared literal once; a test that the list covers what it lists, where one is cheap | Not yet observed |

## Hard constraints and what enforces them

The rules a review may block on. Mechanical ones get a check whose error names the fix; a rule that needs judgment says why it can't be checked. The `correct` skill adds rows. Drop a row once its mistake can't happen.

| Rule | HARD because | Enforced by | Added after |
| --- | --- | --- | --- |
| `checks` imports only `model` | A check that reused the ledger would agree with the ledger's mistakes (threat model: a wrong answer that looks right) | import-linter contract in `pyproject.toml`; `tests/test_project.py` fails when a new module is missing from its forbidden list | `docs/PLAN.md`, import contract 2 |
| `keys` and `graders` import none of `generate`, `replay`, `plant`, `sources`, `build`, `tax.engine` | Spec rule "Independent keys" | import-linter contract "keys and graders import no generator code" in `pyproject.toml` | `docs/PLAN.md`, import contract 1 |
| Each outside program is reached through one module: the CLI under test through `runner/cli.py`, Tax-Calculator through `tax/crosscheck.py`, the jury CLIs through `graders/jury.py` | Rule 5; the seal and the equal arms depend on one place starting the CLI | `tests/test_outside_programs.py`: only `runner/cli.py` and `graders/jury.py` start a process, and only `tax/crosscheck.py` imports Tax-Calculator (a test, not an import-linter contract) | `docs/PLAN.md`, import contract 3 |
| No float in `model`, `replay`, `tax` or `keys` | Money rounds one declared way, half-up to the cent | `tools/check_no_float.py` in `make check`; `tax/crosscheck.py`, the boundary with Tax-Calculator (which computes in float), is the one file excepted, by name | `docs/PLAN.md`, Choices and why |
| No GPL or AGPL package is installed | Spec rule "Licence hygiene" | `tools/check_licences.py` in `make check`, with a deny-list by name | Spec; the `tenforty` probe |
| The README, every site page and the data metadata carry the notice; price files carry "synthetic"; no published file holds a real ticker or security name | Spec rules "Notice everywhere", "Synthetic prices", "Aliases in public" | `src/casebook/publish/gates.py`, run by `casebook site` before anything is published; `tests/test_gates.py` | Spec |
| A default build writes no real ticker or security name | Spec, "Aliases, private set and licences" | `refuse_real_identifiers` in `src/casebook/build.py`; `tests/test_build.py` | Spec |
| A run starts only sealed: no sealed file or link in the workspace, no row or document known after the cutoff, a household in the manifest, the shared tools | Spec rules "Sealed answer material", "No future evidence", "Synthetic households only" | `src/casebook/runner/preflight.py` and `run.py`, named errors; `tests/test_runner.py`; the live canary (`casebook canary`) for the CLI's own confinement | Spec |
| The three arms share one configuration; only the instruction differs, and a run whose transcript shows no instruction loaded fails | Spec rule "Equal arms" | `src/casebook/runner/config.py` and `cli.py`; `tests/test_runner.py` compares the stand-in's logged arguments and environment | Spec |
| A failed run is never graded; a run is judged failed by `is_error` and the exit code, never by `subtype` | Spec, Running it; the planning probe that saw `is_error: true` beside `subtype: "success"` | `src/casebook/runner/transcript.py` and `run.py`; `tests/test_runner.py` | `docs/PLAN.md`, Settled by probes |
| A household that fails a check is never published | Spec rule "No household with a failed check enters a release" | `src/casebook/publish/site_build.py` runs the checks first; `tests/test_gates.py` | Spec |
| Expected values in tests come from the spec, a worked example or a hand-worked literal, never recomputed the way the code does (rule 12) | A key, check or ledger tested against itself proves nothing | Review only: needs judgment | `docs/PLAN.md` |
| `make check` calls no model and reaches no network (rule 13) | Checks must be free, repeatable and leak nothing | Every run in the checks goes to the stand-in CLI `tests/standin/claude.py` through `CASEBOOK_CLAUDE`; review only for the rest until slice 6's test that blocks the network | `docs/PLAN.md` |

## For master

Mistakes whose cause is master's own text: a doc this product copied from the template, or a skill (`docs/PROCESS.md`, Correcting). Each is fixed here first. Master decides separately whether it changes.

- **Fixing a confirmed review finding** (process version: master `4878883`). The `cross-review` skill, step 4, says "Confirmed: fix it, with a test that fails before the fix". Fixes here answered the probe the reviewer gave, and about 20 brought in a new defect, among them every finding still open after a targeted check. Local fix: rule 15 in this file. For master to weigh: ask the fix to name the rule the finding breaks and test the other inputs that break it, and the round-2 prompt to name what any new exemption lets through.
