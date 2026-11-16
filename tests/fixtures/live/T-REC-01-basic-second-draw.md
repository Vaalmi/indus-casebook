No. The 2 April 2026 debits came to **$4,605.18**. The agreements call for **$4,314.93**, so the household was **overbilled by $290.25** for the quarter.

**What went wrong.** On 18 November 2024 all three household members signed a householding letter (AGR-4821-3 in `crm/crm.json`). It says the joint account, Henrik's IRA and Ngozi's individual account are "billed together as one group from the next billing cycle." The portfolio system was never updated. `portfolio/household.json` still has the two billing groups set up in 2021 (`last_changed: 2021-09-14`):
- BG-4821-1 holds the joint account and the IRA.
- BG-4821-2 holds Ngozi's account on its own.

Because Ngozi's account is billed alone, all of its value is charged at the 1.00% first tier. Combined billing would have charged the household's value above $1M at 0.80%.

**Check against the 31 March 2026 values.** The statement totals match the custodian's position and cash files exactly. The fee schedule (FS-STD) is billed quarterly in arrears: 1.00% on the first $1M, 0.80% from $1M to $2M, and 0.60% above $2M.

| | Value at 31 Mar 2026 | Quarterly fee |
|---|---|---|
| SYN-48210001 (joint) | $892,625.50 | |
| SYN-48210002 (IRA) | $434,343.77 | |
| **What was billed** | | |
| Group 1 (accounts 0001 and 0002) | $1,326,969.27 | $3,153.94 (debited as $2,121.59 + $1,032.35) |
| Group 2 (account 0003) | $580,497.60 | $1,451.24 (debited) |
| **Debited total** | | **$4,605.18** |
| **What the agreements call for** | | |
| One household group | $1,907,466.87 | (10,000 + 907,466.87 × 0.008) ÷ 4 = **$4,314.93** |

The debits match the two-group calculation to the cent. So the arithmetic was right; the setup it ran on was wrong.

**Earlier quarters.** Each fee debit since April 2025 is in line with the same two-group calculation, so this has probably been going on since the letter took effect. Those quarters should be recalculated as well; I only computed the Q1 2026 figure. The billing groups in the portfolio system also need to be merged before the next fee run.

```json
{
  "finding": "fee_error",
  "debited_fee": 4605.18,
  "correct_fee": 4314.93,
  "amount_misbilled": 290.25,
  "figures": [
    {"label": "Fee debited 2026-04-02, SYN-48210001", "value": 2121.59, "source": "custodian/transactions.csv"},
    {"label": "Fee debited 2026-04-02, SYN-48210002", "value": 1032.35, "source": "custodian/transactions.csv"},
    {"label": "Fee debited 2026-04-02, SYN-48210003", "value": 1451.24, "source": "custodian/transactions.csv"},
    {"label": "Total fee debited 2026-04-02", "value": 4605.18, "source": "custodian/transactions.csv", "computed": true},
    {"label": "SYN-48210001 total value 2026-03-31", "value": 892625.50, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "SYN-48210002 total value 2026-03-31", "value": 434343.77, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "SYN-48210003 total value 2026-03-31", "value": 580497.60, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "SYN-48210001 cash 2026-03-31", "value": 28030.21, "source": "custodian/cash.csv"},
    {"label": "SYN-48210002 cash 2026-03-31", "value": 4742.48, "source": "custodian/cash.csv"},
    {"label": "SYN-48210003 cash 2026-03-31", "value": 11461.79, "source": "custodian/cash.csv"},
    {"label": "FS-STD tier 1 annual rate (up to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 2 annual rate (1,000,000 to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts one billing group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups in portfolio system last changed", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "As-billed group BG-4821-1 value (SYN-48210001 + SYN-48210002)", "value": 1326969.27, "source": "portfolio/household.json", "computed": true},
    {"label": "As-billed BG-4821-1 quarterly fee", "value": 3153.94, "source": "portfolio/billing.json", "computed": true},
    {"label": "As-billed BG-4821-2 quarterly fee", "value": 1451.24, "source": "portfolio/billing.json", "computed": true},
    {"label": "Householded value, all three accounts 2026-03-31", "value": 1907466.87, "source": "documents/index.json", "computed": true},
    {"label": "Correct householded annual fee", "value": 17259.73, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct householded quarterly fee", "value": 4314.93, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled", "value": 290.25, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The householding letter AGR-4821-3, signed 2024-11-18, requires all three accounts to be billed as one group, but the portfolio system still bills them as two groups set up in 2021, so Ngozi's $580,497.60 account was charged entirely at the 1.00% first tier. On the combined 31 March 2026 value of $1,907,466.87, the FS-STD schedule gives a quarterly fee of $4,314.93, against $4,605.18 debited, an overcharge of $290.25. Every quarterly fee since April 2025 matches the same two-group calculation, so earlier quarters probably need correcting too."
}
```