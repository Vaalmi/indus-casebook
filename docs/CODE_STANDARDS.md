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

## Lessons

Every mistake the owner has corrected, so a repeat is visible. A lesson is guidance a reviewer may note. It becomes a hard constraint only when the owner marks it so, in the table below.

"When" names the kind of situation, so the lesson fires on a different case: not "the invoice export", but "any export another system imports". "Observed result" is what happened the last time that situation came up (`docs/PROCESS.md`, Correcting): "not yet observed" until it does.

None yet: the owner's first correction adds the first row.

| Lesson | When | From (the correction, with its date) | Prevention | Observed result |
| --- | --- | --- | --- | --- |

## Hard constraints and what enforces them

The rules a review may block on. Mechanical ones get a check whose error names the fix; a rule that needs judgment says why it can't be checked. The `correct` skill adds rows. Drop a row once its mistake can't happen.

| Rule | HARD because | Enforced by | Added after |
| --- | --- | --- | --- |
| `checks` imports only `model` | A check that reused the ledger would agree with the ledger's mistakes (threat model: a wrong answer that looks right) | import-linter contract in `pyproject.toml`; `tests/test_project.py` fails when a new module is missing from its forbidden list | `docs/PLAN.md`, import contract 2 |
| `keys` and `graders` import none of `generate`, `replay`, `plant`, `sources`, `build`, `tax.engine` | Spec rule "Independent keys" | import-linter contract, added with the first grader (slice 2); review only until then | `docs/PLAN.md`, import contract 1 |
| Each outside program is reached through one module: the CLI under test through `runner/cli.py`, Tax-Calculator through `tax/crosscheck.py`, the jury CLIs through `graders/jury.py` | Rule 5; the seal and the equal arms depend on one place starting the CLI | import-linter contract, added with each module (slices 2, 7, 10) | `docs/PLAN.md`, import contract 3 |
| No float in `model`, `replay`, `tax` or `keys` | Money rounds one declared way, half-up to the cent | `tools/check_no_float.py` in `make check` | `docs/PLAN.md`, Choices and why |
| No GPL or AGPL package is installed | Spec rule "Licence hygiene" | `tools/check_licences.py` in `make check`, with a deny-list by name | Spec; the `tenforty` probe |
| The README, every site page and the data metadata carry the notice; price files carry "synthetic"; no published file holds a real ticker or security name | Spec rules "Notice everywhere", "Synthetic prices", "Aliases in public" | `src/casebook/publish/gates.py`, run by `casebook site` before anything is published; `tests/test_gates.py` | Spec |
| A default build writes no real ticker or security name | Spec, "Aliases, private set and licences" | `refuse_real_identifiers` in `src/casebook/build.py`; `tests/test_build.py` | Spec |
| A household that fails a check is never published | Spec rule "No household with a failed check enters a release" | `src/casebook/publish/site_build.py` runs the checks first; `tests/test_gates.py` | Spec |
| Expected values in tests come from the spec, a worked example or a hand-worked literal, never recomputed the way the code does (rule 12) | A key, check or ledger tested against itself proves nothing | Review only: needs judgment | `docs/PLAN.md` |
| `make check` calls no model and reaches no network (rule 13) | Checks must be free, repeatable and leak nothing | Review only until slice 2 brings the stand-in CLIs and slice 6 a test that blocks the network | `docs/PLAN.md` |

## For master

Mistakes whose cause is master's own text: a doc this product copied from the template, or a skill (`docs/PROCESS.md`, Correcting). Each is fixed here first. Master decides separately whether it changes.

None yet.
