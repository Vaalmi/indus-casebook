# Rule readings for the tax review

UNVALIDATED SYNTHETIC RESEARCH PREVIEW. Household data, prices, transactions and document contents are invented. Securities appear under invented names by default; an optional mode uses real ticker identifiers with invented prices. Tax calculations, answer keys and workflow judgments have not been independently reviewed by qualified practitioners. This is not tax, investment or compliance advice and is unsuitable for filing, trading or client decisions. No performance claims are established.

Where the builder had to read a tax or RMD rule one way to build the book, its returns or its answer keys, the reading is listed here with where it is recorded. None of these readings has been reviewed. Each is a place where the CPA or EA review may disagree; a reading the review changes ships as a new book version with an errata entry.

Sources are the repo's own records: `docs/STATUS.md` ("Known gaps" and the owner's sections), `docs/PLAN.md` ("Choices and why") and the owner's decision pages in `docs/decisions/`.

## The tax summary and its two calculators

1. **"Bracket" is the marginal ordinary-income rate** (one of the seven 2025 rates) that applies to the tax unit's taxable ordinary income, not a dollar figure. Each calculator derives it from its own taxable income and its own thresholds, so agreement means the same rate. Source: `docs/PLAN.md`, "Choices and why", "Settled by probes".
2. **Loss carryforwards and IRA basis have no outside calculator.** Tax-Calculator computes neither, so for these two lines the second calculator is the independent code in `keys/` (its own Form 8606 and capital loss carryover worksheet), checked against IRS worked examples. Two in-house implementations agreeing is weaker than an outside tool. Every tax unit's two lines are in `boundary/in_house_lines.csv`. Source: `docs/PLAN.md`, "Choices and why".
3. **The facts are what happened, not what the custodian recorded.** Each tax unit's facts come from the true ledger (the event log, replayed), so the tax summary is the household's real liability; a planted error (an RSU basis of zero on a 1099-B, a QCD coded as a plain distribution) shows only in the custodian's documents. Source: `src/casebook/tax/facts.py`, its opening note.
4. **The book's tax simplifications,** which both calculators see: no interest income (every 1099-INT box 1 is $0.00); no state taxes or mortgage interest, so every household takes the standard deduction; no dependents or credits; wages equal Medicare wages; no W-2 withholding; no payer TIN on any form. Form 8606 line 4 (contributions made from 1 January to 15 April 2026) is zero. The engine refuses a married-filing-separately filer with Social Security, since the facts do not say whether the spouses lived apart; the book has none. Source: `docs/STATUS.md`, Known gaps, "The book's tax simplifications".
5. **A missed 2025 RMD's excise tax is not computed.** Archetype 7's trap missed an inherited IRA's 2025 distribution; the section 4974 excise goes on Form 5329, which the spec's list of forms does not name, and neither calculator figures it. Its return shows no Schedule 2 line 8. Source: `docs/STATUS.md`, Known gaps.

## The filled returns

6. **"As triggered" means only where triggered,** for every schedule and form after the 1040: a featured household gets Form 8606, 8949, 8960 or 8959 only when its facts call for it. Source: `docs/PLAN.md`, "Choices and why", reading U5 (the owner, 16 November 2026).
7. **Lines left for a preparer.** No household made estimated payments, so most returns show an amount owed, and line 38 (the estimated tax penalty) is blank. Form 8959's Part V withholding reconciliation is blank (the book's W-2s carry no box 6). The 1040's home address is blank (the book holds no addresses). Every sale is listed on Form 8949; Exception 1 (totals straight to Schedule D) is not used. Source: `docs/STATUS.md`, Known gaps, "The filled returns leave some lines for a preparer".
8. **What a return leaves out of each form's map:** the special-filing boxes, direct deposit, the third party designee, the signature and the paid preparer blocks. The returns are unsigned and unreviewed. Source: the comment heading each map in `src/casebook/tax/forms/maps/`.

## RMDs, QCDs and inherited IRAs

9. **Legal ages and dates.** The applicable ages are 70½, 72 and 75 by birth date; the QCD age is 70½; the ten-year age gap for a spouse and for a beneficiary; majority at 21. These are in the cited rules table. Two kinds of date stay as cited constants outside it: the 1 April required beginning date, and the birth dates where the applicable age changes (1 July 1949, 1951, 1960). Source: `docs/STATUS.md`, Known gaps, "Legal dates outside the rules table".
10. **Citations not checked against the regulation's text.** The builders cited, without reading the text: the paragraph of 26 CFR 1.408-8 on aggregating IRAs for the RMD; the rule that a 401(k)'s RMD must come from the plan itself; section 1.401(a)(9)-5(d) on annual RMDs after the required beginning date (archetype 7's inherited IRA under the ten-year rule); and Form 1040 lines 4a and 4b for a QCD. Source: `docs/STATUS.md`, Known gaps, "Some planter citations were not checked".
11. **What the RMD key does not cover, and refuses:** a sole spouse beneficiary more than ten years younger (the joint life table), an eligible designated beneficiary, a 401(k) owner still working, a year-of-death RMD, and a missing 31 December 2024 cash row. None occurs in the book; a household with one would fail its key, not be graded. Source: `docs/STATUS.md`, Known gaps.

## Wash sales and basis

12. **A wash sale's replacement counts from the seller's tax unit:** purchases by the seller and the seller's spouse, IRAs included, within 30 days either side. An adult child's purchase is not a wash sale. The draft task matrix asks T-TAX-06 about a replacement "in any household account"; no purchase outside a tax unit falls in any window in the book, so the answer is the same either way. Source: `docs/STATUS.md`, Known gaps, "A wash sale's replacement counts from the seller's tax unit".
13. **RSU releases count as acquisitions** for the wash-sale window: an arguable reading. Source: the same entry.
14. **A wash sale replaced in a taxable account is refused, not computed.** The replacement lot's basis would take the disallowed loss (section 1091(d)), which the replayed lots do not hold. The book's five wash sales all replace into IRAs. Source: `docs/STATUS.md`, Known gaps.

## The tasks' questions

15. **T-MTG-01 asks for the conversion's taxable amount (Form 8606 line 18),** not the tax in dollars: the key cannot work a whole return, and the firm in the tasks does not prepare returns. Source: `docs/STATUS.md`, "What the owner does for slice 5", the task matrix.
16. **T-MTG-06 names its three tax surprises:** a taxed backdoor Roth, an RMD not met, and a wash sale. It covers those three only. Source: the same section.
17. **T-CMP-01's concentration limit counts a single company's stock, not a fund.** Read literally, index funds cross it in five households, the clean twin among them. Source: the same section.
18. **The NIIT key reads wages from the W-2 PDFs** and refuses a household with income it does not cover (a 1099-R, Social Security, a loss carryforward). NIIT across the whole book would need every household's modified AGI. Source: `docs/STATUS.md`, Known gaps.

## What stays held until review

19. **Held:** every answer key for a tax-lot or RMD task, and for any other task whose key computes a tax figure (an RMD in reconciliation; a Form 8606 taxable amount, the NIIT, the SALT limit or the tax surprises in meeting; a released lot's basis and a sale's gain, a conversion's taxable amount, a loss a wash sale disallows, or the taxable part of IRA distributions, in any workflow); the graders' verdicts on those tasks; the tax summaries; and any combined score. 17 of the 24 public tasks are held. Source: `docs/PLAN.md`, "What stays held for tax and RMD"; `docs/STATUS.md`, slice 14.
20. **Not held:** the registry's justified conclusion for a tax or RMD planted item, which the household page shows with its figures, before review as after. A conclusion can state an amount a held key also states; the owner chose the fuller page knowing that. Source: `docs/PLAN.md`, reading U4 (the owner, 16 November 2026).
21. **A case packet's answer sheet** holds that conclusion with its figures, or the twin's explanation, and the published keys of the household's tasks that are not held; the tax summary and held keys stay out. Source: `docs/decisions/2026-11-19-slice16-release-choices.md`, choice 3(a).
