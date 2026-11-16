# Tech stack

Why each part is what it is. Versions are pinned in `pyproject.toml` and `uv.lock`, not here.

## Language and packaging

- **Python 3.13, managed by uv with a lockfile.** One package, `casebook` under `src/`, and one command, `casebook`. Carried from WealthContext's stack, so the owner runs one toolchain. Turned down: Node for the generator, since the tax cross-check (Tax-Calculator) and the form filler (pypdf) are Python.
- **Money is `Decimal`, rounded half-up to the cent** in `src/casebook/model/money.py` only. `tools/check_no_float.py` fails the check on any float in `model` and `replay` (and in `tax` and `keys` once they exist). Turned down: integer cents, which would make every emitted file and every test literal harder to read.
- **Determinism without floats.** The synthetic market draws integers from a stream seeded by the seed, the version and the security, and steps prices in Decimal, so every platform builds the same bytes. JSON is written with sorted keys; PDFs use ReportLab's invariant mode.

## The book

- **Household scripts are TOML** (`book/scripted/`), read with the standard library. Turned down: YAML, which needs a dependency, and JSON, which is noisy to write by hand.
- **Document PDFs are drawn with ReportLab (BSD).** Its invariant mode fixes the dates and IDs inside the PDF. **pypdf (BSD)** reads PDF text back for the gates, and fills the official IRS forms in slice 8 (docs/PLAN.md, Settled by probes).

## The site

- **Jinja2 templates, static files, no build step.** `casebook site` renders the pages from a built, checked book and copies the published files beside them. The pages work from `file://` and need no JavaScript yet. Turned down: a static-site generator, which would add a second toolchain for three kinds of page.
- **GitHub Pages, published from a release tag** by `.github/workflows/pages.yml` (the owner's decision, 13 November 2026). Rolling back is running the same workflow on the previous tag.

## Checks

- **`make check`** runs ruff (lint and format), pyright in strict mode, import-linter, the float check, the licence check and pytest with an 85% coverage floor. The pytest run includes the end-to-end tests: a seeded build, the checks, the site build with its gates, and Playwright on the built site.
- **import-linter** holds the import contracts in `docs/PLAN.md`. Slice 1 has contract 2: `checks` imports only `model`.
- **The licence check** (`tools/check_licences.py`) reads every installed package's declared licence and also refuses known offenders by name, since `tenforty` declares MIT and bundles GPL code. LGPL passes: the rule names GPL and AGPL, and an LGPL library may be imported. A package that declares no licence fails until someone checks it by hand.
- **Playwright (Apache-2.0)**, Chromium only, from pytest against a local server. Turned down: Node Playwright, a second toolchain.
- **A pre-commit hook** (`.githooks/pre-commit`, installed by `make setup`) and **a GitHub Action** (`.github/workflows/check.yml`, on every push) both run `make check`.

## Running locally

```bash
make setup                          # uv sync, Playwright's Chromium, the git hook
make check                          # the one check command
uv run casebook build --seed 2026   # the book, into out/book/<version>/
uv run casebook check               # pass or fail per check per household
uv run casebook site                # the site, into out/site/
```

## Costs

Nothing in the build, the checks or the site costs money. The checks call no model and no network. Live runs (from slice 2) use the owner's Claude subscription through the `claude` CLI; the tone jury (slice 10) uses the owner's Codex and Antigravity sign-ins. GitHub Pages and Actions are free for a public repo.
