# Audit of 15 households, book 0.0.1

## Who

A Claude subagent (Opus 5.5, high effort) did this audit at the owner's direction on 17 November 2026. It stands in for the owner's hand audit that the spec describes ("the owner's line-by-line check of 15 households"). The owner did not do it by hand.

## What

- Book 0.0.1, seed 2026. Manifest `out/book/0.0.1/manifest.json`, sha256 `7c7e1f32588ef555a5a8224563ce06fdcf1d025f7f5cb22f5c4885f927cff6de`.
- Worksheet `out/audit/0.0.1/worksheet.csv`, sha256 `729e2374ccb9cc16e042bfb9ae697bcf1cc4aeec23ce84897205085973e06597`. It has 2,112 lines.
- The 15 households, which cover archetypes 1 to 10: HH-0608 (1), HH-2316 (2), HH-0376 and HH-0420 (3), HH-0562 (4), HH-0371 and HH-0410 (5), HH-0190 and HH-6590 (6), HH-0330 and HH-0491 (7), HH-0737 (8), HH-9234 and HH-9571 (9), HH-0478 (10).
- Before the audit, the 295 book files it reads were hashed: each household file of the 15, plus `securities/`. Every hash matched the manifest.

## How

- **Independent checker.** The checker is a new script that uses only the Python standard library (`csv`, `json`, `decimal`), plus `pypdf` for the statement PDFs. It imports nothing from the project and reuses no other script.
- **Each figure checked at its cited source.** For every figure and stated result, the checker opened the place the line cites and compared the value there with the figure. A CSV line is read as the file's physical line, with the header as line 1. `positions[i]` and `fee_schedules[i].tiers[j]` are read from the JSON. A PDF figure is read from the statement's page 1: the header total, a holdings row, the Cash row or the Total row. The checker also confirmed that each cited record is the one the line names, by its account, security, transaction, lot and date.
- **Each sum recomputed with `Decimal`, rounding as the statement words it.**
  - Units × price, rounded half-up to the cent: custodian and portfolio-system positions, and statement holdings.
  - Units × dividend per unit, with the per-unit amount read from the transaction's description.
  - Signed trade amounts.
  - Proceeds − basis.
  - Opening lots + acquisitions − disposals = closing units.
  - Opening settled cash + signed flows settled in (opening, closing] = closing settled cash.
  - Each tier's rate on the part of the billing group's value inside the tier, summed, ÷ 4, rounded once, against the sum of the fees debited.
  - Holdings + cash = the statement's header total and its Total row.
- **Completeness, as a hand auditor would check it.**
  - Each roll-forward lists every opening lot, and every unit-changing or settled cash transaction in its period.
  - Each fee line lists every position and cash row of the group's accounts on the quarter end, and every fee debited for that quarter.
  - The billing group's accounts and schedule match `portfolio/household.json`, and the named agreements in `crm/crm.json` cover the group's accounts.
  - Each statement total lists every holdings row.
- **A test of the checker.** In a mutation test, one figure, stated result or citation was altered or dropped in each of 625 lines, spread across all nine kinds. The checker flagged all 625 and raised no alarm on any unaltered line.
- **Read by eye.** At least five lines of different kinds in each household were read straight from the source files, without the checker, and their sums were redone by hand:

| Household | Lines read by eye |
| --- | --- |
| HH-0190 | 1 (position value), 49 (dividend), 55 (trade value), 99 (realized lot), 109 (statement total) |
| HH-0330 | 48 (position value, portfolio system), 88 (cash roll-forward), 100 (realized lot), 101 (quarterly fee, two agreements), 106 (statement holding value) |
| HH-0371 | 81 (trade value), 82 (dividend), 133 (units roll-forward), 143 (cash roll-forward), 173 (statement holding value) |
| HH-0376 | 79 (position value, portfolio system), 98 (trade value), 131 (units roll-forward, RSU vests), 160 (realized lot, zero basis), 170 (statement total) |
| HH-0410 | 2 (position value), 81 (dividend), 114 (units roll-forward), 124 (cash roll-forward), 150 (quarterly fee, second tier) |
| HH-0420 | 71 (position value, portfolio system), 90 (trade value), 122 (units roll-forward), 151 (realized lot), 157 (statement holding value) |
| HH-0478 | 1 (position value), 57 (dividend), 92 (units roll-forward), 99 (cash roll-forward), 122 (quarterly fee, second billing group), 130 (statement total) |
| HH-0491 | 49 (trade value), 52 (dividend), 82 (units roll-forward), 100 (realized lot), 106 (statement holding value) |
| HH-0562 | 56 (position value, portfolio system), 78 (trade value), 110 (cash roll-forward, Roth conversion), 119 (realized lot), 128 (statement total) |
| HH-0608 | 49 (trade value), 76 (units roll-forward), 94 (cash roll-forward, conversion), 106 (quarterly fee, a zero fee), 114 (statement total) |
| HH-0737 | 57 (dividend), 87 (units roll-forward), 94 (cash roll-forward, step-up), 112 (quarterly fee, second tier), 121 (statement total) |
| HH-2316 | 64 (position value, portfolio system), 65 (trade value), 102 (units roll-forward), 128 (realized lot), 134 (statement holding value) |
| HH-6590 | 53 (trade value), 84 (cash roll-forward, QCD), 89 (realized lot), 91 (quarterly fee), 99 (statement total) |
| HH-9234 | 90 (trade value), 112 (units roll-forward to no row), 137 (realized lot), 138 (quarterly fee, second tier), 147 (statement total) |
| HH-9571 | 69 (dividend), 112 (units roll-forward to no row), 119 (cash roll-forward), 142 (quarterly fee, second tier), 153 (statement holding value) |

Two worksheet conventions were read as presentation, not as defects:

- A sale in a units roll-forward is shown with a negative sign (for example −847). The source records the units as positive, on a SELL.
- A fee debited is shown as a positive amount. The source records a negative FEE amount.

## Result

- **2,112 lines checked: 2,112 ok, 0 defect.**
- Every figure is at its cited source and reads the same there, and every sum holds as worded. `uv run casebook audit-log --check` reports 0 problems.
- The log is `published/audit/audit-log.csv`: the worksheet's rows in order, with `checked` set to `yes`, `result` set to `ok`, and `note` and `fixed_in` left empty.

Some things in the book are worth knowing, though none is an arithmetic defect:

- **HH-0737** writes some units with a trailing `.0`, such as `9369.0` and `531.0`, in its positions and transactions after the March 2025 step-up. Its tax lots hold half units (`4684.5`, `265.5`). The values are equal, but the format differs from the rest of the book.
- **HH-0608** writes two cash flows as `7000` and `-7000`, without cents.
- **Archetype 10's fee lines (HH-0478)** check each billing group on its own, as the portfolio system bills them. The planted householding item is the trap, not an arithmetic error, so those lines read as correct arithmetic.

## What this audit does not cover

- **Tax figures.** The 1099s, 1099-Rs, SSA-1099s, the filled returns and the tax summaries belong to the CPA or EA review.
- **Anything the worksheet does not list.** That includes:
  - unsettled cash, which is 0.00 on every cash row of these 15 households
  - statements other than each account's 2026 Q1 statement
  - CRM facts other than the agreements a fee line names
  - whether a planted trap is correctly planted
  - the other 73 public households
- **Clauses with no case in these households:**
  - "Splits applied": no split occurs in these 15 households, so this clause was not exercised.
  - "Held from the acquired date to the sold date" on realized lots: the line states no holding period or term, so only the two dates were checked at their source.
