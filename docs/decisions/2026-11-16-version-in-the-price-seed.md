# Decision needed: should a new book version re-draw every price?

**What's stuck.** The rollback test in slice 1 needs a release `v0.0.2`, and any correction ships "as a new version". `docs/PLAN.md` (Choices and why, Determinism) seeds each random stream "from the seed, the version and the household ID"; the code does the same for prices and dividends (`src/casebook/securities/market.py`). So bumping the version re-draws every synthetic price.

**Evidence.** `casebook build --seed 2026` versus `--seed 2027` changes every price (`tests/test_build.py::test_another_seed_builds_other_prices`); the version enters the seed the same way. The trap's overbilling for the quarter to 31 March 2026 is $508.56 at version 0.0.1. The three published live runs of T-REC-01 answered against those prices, and `tests/test_key_fee_reconciliation.py` holds 508.56 as a literal.

**Options.**

1. **Keep the plan: the version is in the seed.** Consequence: every release, a one-line correction included, changes every price, fee and planted figure in the book; every published run must be redone (288 runs at the full pass) and every test literal tied to a figure rewritten. Results across releases do not compare.
2. **Leave the version out of the price and household seeds.** Seed each stream from the seed and the subject (security or household) only; a version changes only what its errata entry says changed. Consequence: one plan line changes; runs and literals stay valid across releases unless a correction touches their household; errata stay meaningful.

**My recommendation.** Option 2. A version is a release of corrections, and corrections should change what they correct.

**If you don't decide.** The book stays at version 0.0.1 for the whole build, so nothing is re-drawn. The `v0.0.2` rollback test waits; you can still push `v0.0.1` and check the site.

**Decision.** Option 2, the owner, 16 November 2026. The version left the price and dividend seeds the same day. Changing the seed's inputs re-drew the book once: the trap's overbilling for the quarter to 31 March 2026 is now $290.25, worked by hand in `tests/test_key_fee_reconciliation.py`. The three T-REC-01 live runs were rerun against it, and the seven earlier live answers are graded against a copy of the files they read (`tests/fixtures/live/HH-4821-first-draw/`).
