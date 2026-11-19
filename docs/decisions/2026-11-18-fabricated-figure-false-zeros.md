# Decided: the fabricated-figure rule zeroes most honest answers

**What's stuck.** Slice 13's named results. The full pass (`pass-20261118T080940Z-4471`) finished on 18 November 2026 at 23:22 UTC: 288 slots, 283 runs completed, 5 slots failed on the CLI's 40-turn limit (all whole-book tasks: T-CMP-05 once, T-CMP-06 four times), and all 36 follow-up runs have three jury votes. The runs are sound. Their grades are not fit to publish: the fabricated-figure rule, strict as decided on 18 November (option 1 of `2026-11-16-fabricated-figure-rule.md`), zeroes most of them.

**Evidence.** Each slot's final run, from its record under `$CASEBOOK_PRIVATE/runs/`:

| | completed | passed | zeroed (all by "fabricated figure") | of those, full marks on every other criterion |
| --- | --- | --- | --- | --- |
| Public tasks | 211 | 59 | 146 | 103 |
| Private tasks | 72 | 45 | 27 | 18 |

The public zeros by the figure that caused them (no private figure was read for this page):

- **Arithmetic on cited file values, shown in the answer** (61): "LQD unrealized gain (258,560.16 - 257,498.60) = 1061.56", "401(k) total: 40,391.34 + 136,123.20 + 1,824.06 = 178338.60", "taxable part of conversion (7000 - 7000*7000/228659.62) = 6785.71".
- **An age from a birth date in the files** (27): "Bernard's age at end of 2025 (2025 - 1947) = 78". Every arm of T-REC-03 and T-REC-04 is zeroed by it in every repeat.
- **Prose amounts** (27): some are a rules constant ("$3,000", the capital-loss limit), some rounded ("$430k", "$167k"), some I have not traced ("$28,761", "$1,436.39").
- **A count of what the folder holds** (19): "Households reviewed = 92", "Households with a signed householding agreement = 4". Every arm of T-REC-06 is zeroed by it.
- **A value that is not a number** (12): "No other income outside the accounts = confirmed", "IRA owner = Elena Castellanos".

T-MTG-05 and T-REC-01, whose answers cite only figures the files hold, pass 9 of 9. As the slice 2 decision warned, an honest derivation the key does not list zeroes the run, and the pass shows that this is most runs, not a few. As published now, the results page would compare the arms mostly on how many derived figures each one cites.

**Options.**

1. **Accept derivations from the files, then regrade.** A cited figure, or an amount in prose, is fabricated only when it is a number that is in no file, the key does not derive it, and it does not follow from the files in one of these ways: (a) the arithmetic the answer shows, over numbers in the files it cites; (b) a sum or difference of values in the cited files; (c) an age from a birth date in the files; (d) a count of the households, rows or records at the cited path; (e) a constant in the rules table. A value that is not a number is never a fabricated figure. Each pattern above becomes a regression test from the live answer that showed it, along with the invented amounts the grader must still zero. Then the 283 stored answers are regraded. No new model run is needed, and the follow-up runs keep their stored jury votes. You record the freeze again, since the graders' hashes change. Consequence: up to 103 public zeros may become passes (I have not checked every one; a rounded or untraced prose amount may still be a real fabrication), and a looser rule catches fewer invented figures that happen to equal a sum of file values.
2. **Keep the rule and publish as is.** Every zero names its figure on the task page. Consequence: the results page is honest about the rule but says little about the arms; 28% of public runs pass.

For the private set under option 1 there is a second choice. The freeze exists so that no grader is changed after held-out runs are seen:

- **1a. Rerun the 72 private runs** under the new freeze. About 5 hours on `claude`, plus the private follow-up runs' jury calls on `claude`, `codex` and `agy`. Every private result is then from a grader frozen before it ran.
- **1b. Regrade the 72 stored private answers** and disclose on the results page that their grader changed after they ran. The change comes from public evidence only. Consequence: no new runs, but "freeze before held-out runs" no longer holds for the private grades.

**My recommendation.** Option 1, with 1a for the private set.

**Decision.** Option 1, with 1a for the private set (the owner, 18 November 2026). Built to (a) to (e) as written, the rule still zeroed 62 of the 211 public answers. Two widenings, each asked with its count, the owner accepted the same day:

- **(b) adds up across the cited household's files, not only the cited ones.** An answer often cites one file and adds from two (a household total cited to `positions.csv` that counts `cash.csv`). It moved the public zeros from 62 to 54. An invented amount passed it by chance at most 0.8% of the time over all of one household's files (0.4% over the cited ones), measured on 2,000 random amounts per range.
- **(f) a rounding in prose.** An amount in prose counts when it rounds a figure the answer cites and the rule accepts, or one the key computes, to the places it is written to ("$1,062" for 1,061.56; "$440k", to ten thousand, for 437,776). It is never a rounding of any other number in the files. It moved the zeros from 54 to 38.

**As built** (`src/casebook/graders/derivations.py`, applied by `graders.common.Support`):

- (a) An operand of arithmetic shown may be in any of the task's files, a figure the key computes, a rules-table parameter, another of the answer's figures the rule accepts, a sum under (b), or a whole number up to 100 (a percentage's 100, "1 - x", "minus 3"). The decision named "the files it cites": answers show "7000 x (1 - 7000/228659.62)" citing `positions.csv` while 7000 sits in `transactions.csv`.
- (b) A record's two values added or subtracted; a field's total over the records of one table that share up to two values (an account, a date, a symbol, the year, quarter or month of a date); and two such totals under the same values added or subtracted, in one file or two. Always to the cent. A price is still read, never derived.
- (c) A whole number the label calls an age, equal to a year it names (or a year of the files' dates) less the year of a date in the cited files, or one less.
- (d) A whole number no larger than the files, the folders, or the rows and records at the cited path. A placeholder in a path (`households/<household ID>/...`) reads as any folder.
- (e) The parameters of the 2025 rules table, not its life-expectancy tables (whose hundreds of entries would make every small number a constant). A life-expectancy factor the key itself uses was already accepted when cited to IRS Publication 590-B; it is now accepted cited to any file.
- A text value is no figure; an amount written as money inside one is judged as an amount in prose. A run's CRM note may repeat what its answer derived.

**What it changes.** On the 211 stored public answers: 38 zeroed (from 146), 25 of them with full marks otherwise. What still zeroes them is figures worked out without the working shown (a conversion's taxable part, a hypothetical household fee), sums over some of a household's accounts, or a rounding of an uncited figure. Each zero names its figure. No key and no task changed. Every grader's hash changed, so the freeze is recorded again, then the public answers are regraded (`casebook regrade`) and the private set runs again (`casebook pass --private`).
