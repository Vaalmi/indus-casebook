I checked this against all three statements and the custodian, portfolio and CRM files. **There is a fee error. The household was overcharged by $290.25 for the quarter.**

**What was debited on 2 April 2026** (`custodian/transactions.csv`, rows T-4821-0048 to 0050)
- SYN-48210001 (joint): $2,121.59
- SYN-48210002 (Henrik's IRA): $1,032.35
- SYN-48210003 (Ngozi's individual account): $1,451.24
- **Total: $4,605.18**

**Why it's wrong**
- The firm's portfolio system (`portfolio/household.json`) still has two billing groups: the joint account and the IRA in BG-4821-1, and Ngozi's account alone in BG-4821-2. Neither group has changed since 14 September 2021.
- On 18 November 2024, all three account holders signed a householding letter, AGR-4821-3 (`crm/crm.json`). It says the three accounts "are billed together as one group from the next billing cycle." That change never reached the billing groups.
- Nothing in the files cancels or overrides that letter. The 14 October 2025 annual review note says "No changes requested."

**Quarter-end values on 31 March 2026** (each statement total matches `custodian/positions.csv` plus `custodian/cash.csv`; unsettled cash was zero in all three accounts)
- SYN-48210001: $892,625.50
- SYN-48210002: $434,343.77
- SYN-48210003: $580,497.60

**How the debit was calculated: two billing groups.** The fee schedule FS-STD (`portfolio/billing.json`) charges 1.00% a year on the first $1M, 0.80% on $1M to $2M and 0.60% above that, billed quarterly in arrears.
- Group BG-4821-1 is worth $1,326,969.27. The annual fee is $10,000 + ($326,969.27 × 0.8% = $2,615.75) = $12,615.75. A quarter of that is $3,153.94. Split in proportion to account value, that gives $2,121.59 and $1,032.35, matching the two debits.
- Group BG-4821-2 is worth $580,497.60. The quarterly fee is $580,497.60 × 1% ÷ 4 = $1,451.24, matching the third debit.
- So the system applied the schedule correctly to the wrong groups.

**What the agreements call for: one billing group**
- Combined value: $892,625.50 + $434,343.77 + $580,497.60 = $1,907,466.87
- Annual fee: $10,000 + ($907,466.87 × 0.8% = $7,259.73) = $17,259.73
- Quarterly fee: $17,259.73 ÷ 4 = **$4,314.93**
- Overcharge: $4,605.18 − $4,314.93 = **$290.25**

**Beyond this quarter:** the April 2025, July 2025, October 2025 and January 2026 debits (back to the first one on file) were also billed in two groups. They were probably overcharged too, but I didn't recalculate them. Separately, the billing groups in `portfolio/household.json` need updating to match AGR-4821-3, or the July 2026 debit will repeat the error.

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
    {"label": "Value 2026-03-31, SYN-48210001 (positions + cash)", "value": 892625.50, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "Value 2026-03-31, SYN-48210002 (positions + cash)", "value": 434343.77, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "Value 2026-03-31, SYN-48210003 (positions + cash)", "value": 580497.60, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "Settled cash 2026-03-31, SYN-48210001", "value": 28030.21, "source": "custodian/cash.csv"},
    {"label": "Settled cash 2026-03-31, SYN-48210002", "value": 4742.48, "source": "custodian/cash.csv"},
    {"label": "Settled cash 2026-03-31, SYN-48210003", "value": 11461.79, "source": "custodian/cash.csv"},
    {"label": "FS-STD tier 1 annual rate (up to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 2 annual rate (1,000,000 to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding letter AGR-4821-3 signed (all three accounts billed as one group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups last changed (still split BG-4821-1 / BG-4821-2)", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "BG-4821-1 value as billed (001 + 002)", "value": 1326969.27, "source": "documents/statement-SYN-48210001-2026Q1.pdf", "computed": true},
    {"label": "BG-4821-1 quarterly fee as billed (10,000 + 2,615.75) / 4", "value": 3153.94, "source": "portfolio/billing.json", "computed": true},
    {"label": "BG-4821-2 quarterly fee as billed (580,497.60 x 1% / 4)", "value": 1451.24, "source": "portfolio/billing.json", "computed": true},
    {"label": "Combined household billing value", "value": 1907466.87, "source": "documents/statement-SYN-48210003-2026Q1.pdf", "computed": true},
    {"label": "Annual fee on combined value (10,000 + 907,466.87 x 0.8%)", "value": 17259.73, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct quarterly fee (17,259.73 / 4)", "value": 4314.93, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled (4,605.18 - 4,314.93)", "value": 290.25, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The 2 April 2026 debits total $4,605.18. They match FS-STD applied to two billing groups (joint plus IRA, and Ngozi's account alone), which have not changed in the portfolio system since 2021. The householding letter AGR-4821-3, signed on 18 November 2024 by all three account holders, requires the three accounts to be billed as one group. On the combined 31 March 2026 value of $1,907,466.87, the quarterly fee is $4,314.93, so the household was overcharged $290.25."
}
```