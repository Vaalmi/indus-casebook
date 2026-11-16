> **UNVALIDATED SYNTHETIC RESEARCH PREVIEW.** Household data, prices, transactions and document contents are invented. Securities appear under invented names by default; an optional mode uses real ticker identifiers with invented prices. Tax calculations, answer keys and workflow judgments have not been independently reviewed by qualified practitioners. This is not tax, investment or compliance advice and is unsuitable for filing, trading or client decisions. No performance claims are established.

# The Indus Casebook

A seeded book of invented households, with the evidence for each spread across custodian files, a portfolio system, CRM notes and documents, so that anyone can see whether an AI assistant handles a client's messy records safely. This is an early build: one pair of households so far.

## Use it

```bash
make setup                          # install everything, once
uv run casebook build --seed 2026   # build the book into out/book/
uv run casebook check               # run every check on every household
uv run casebook site                # build the public site into out/site/
```

`make check` runs every check the project has: lint, types, tests with the coverage floor, the import contracts, the licence check and the end-to-end tests.

## Licences

Code: Apache-2.0 (`LICENSE`). Data: CC BY 4.0 (`LICENSE-DATA`).
