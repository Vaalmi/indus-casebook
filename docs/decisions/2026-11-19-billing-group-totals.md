# Decision needed: should the fabricated-figure rule accept a total over several of a household's accounts?

**What's stuck.** Slice 13's named results. The decided rule's sums, (b) on [the earlier page](2026-11-18-fabricated-figure-false-zeros.md), work inside one table, and pair two totals at most. So it accepts one account's positions plus its cash on a date, and all accounts' positions on a date. It does not accept **positions plus cash over two or more accounts but not all**. That is the fee basis the billing file states: "the quarter-end value of positions plus cash, per billing group".

**Evidence.** Found while reading the private pass's zeros on 19 November 2026; no reviewer has seen it.

- X-REC-02, skill arm, repeat 3: "BG-0744-1 was worth 1,242,991.05". That is SYN-07440001 and SYN-07440002, positions plus cash, at 2025-12-31, to the cent. The answer is zeroed for it (`fabricated figure: '1,242,991.05' in the answer is in no file and follows from none`). Repeat 2 shows the tier arithmetic "(10,000 + 242,991.05 × 0.80%) ÷ 4 = 2,985.98" and is zeroed on 242,991.05.
- An offline measure on the stored answers, with the widened sum patched in and nothing in the repo changed:

  | | zeroed now | zeroed if widened | of those, full marks otherwise |
  | --- | --- | --- | --- |
  | public, 211 runs | 38 | 31 | 25 → 23 |
  | private, 72 runs | 21 | 20 | 15 → 14 |

  The 7 public runs lifted are in T-MTG-03, T-MTG-04, T-MTG-06 and T-TAX-01. A household has at most a few accounts and seven dates, so the widening adds a few hundred values a household. That is the same order as (b) already holds.

The other zeros are the kinds the earlier page names: a derivation the answer doesn't show (for example Form 8606's nontaxable part, 7941.07), a rounding of a figure it never states, or a wrong sum. For example, "IJR 176,868.71 + SCHB 72,789.84 + SCHP 87,291.10 = 337012.49" really comes to 336,949.65.

**Options.**

1. **Widen (b)**: also accept positions, or positions plus cash, summed over any set of one household's accounts on one date. Consequence: a small grader change, with tests and a targeted review. You record the freeze again. I regrade both passes on their stored answers and jury votes, which needs `casebook regrade` to take the private pass too. No model runs. 7 public and 1 private run lifted.
2. **Keep the rule as decided** and publish now. Consequence: 7 public runs and 1 private run stay zeroed for a figure that is right. Each zero names its figure on the task page.

**My recommendation.** Option 1. The figure is the billing file's own fee basis, so a zero here marks a right answer wrong. That is the false zero you decided against on 18 November.

**If you don't decide.** The named results wait. Meanwhile I fix the site build's refusal of ten run files that quote a price without the word "synthetic", which is needed either way.

**Decision.** <The owner's answer, with the date.>
