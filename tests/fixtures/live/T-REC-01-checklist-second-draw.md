No. The fees debited on 2 April 2026 add up to **$4,605.18**. The agreements call for **$4,314.93**, so the household was overcharged by **$290.25**.

**What went wrong**
- On 18 November 2024 all three household members signed a householding letter (AGR-4821-3, in `crm/crm.json`). It says the joint account (…0001), Henrik's IRA (…0002) and Ngozi's individual account (…0003) are "billed together as one group from the next billing cycle."
- The portfolio system was never updated. `portfolio/household.json` still has two billing groups, both last changed on 14 September 2021: BG-4821-1 for …0001 and …0002, and BG-4821-2 for …0003 on its own.
- Because Ngozi's account was billed on its own, her $580,497.60 was charged at the 1.00% first tier. In the combined group it falls in the 0.80% tier.

**Quarter-end values (31 March 2026)**
The custodian's positions and cash agree with the Q1 statements for all three accounts.

| Account | Value |
|---|---|
| …0001 joint | $892,625.50 |
| …0002 IRA | $434,343.77 |
| …0003 Ngozi | $580,497.60 |
| Combined | $1,907,466.87 |

**What was debited**
The debits exactly match the fee schedule (FS-STD) applied to the old two-group setup:
- Group 1 is worth $1,326,969.27. The fee is (1,000,000 × 1.00% + 326,969.27 × 0.80%) ÷ 4 = $3,153.94. It was debited as $2,121.59 + $1,032.35.
- Group 2 is worth $580,497.60. The fee is 580,497.60 × 1.00% ÷ 4 = $1,451.24.
- The total is $4,605.18.

**What the agreements call for**
One group worth $1,907,466.87. The fee is (1,000,000 × 1.00% + 907,466.87 × 0.80%) ÷ 4 = **$4,314.93**.

**Follow-up**
- **Billing setup:** Merge the three accounts into one billing group in the portfolio system before the next billing run.
- **Earlier quarters:** "Next billing cycle" after November 2024 means every quarter from Q4 2024 onwards was probably billed the same wrong way. The files show the same split pattern in the four 2025 fee debits, so those need recalculating and refunding too. There is no fee debit for Q4 2024 in these files (the transaction history starts in February 2025), so that quarter has to be checked elsewhere.
- **Refund split:** The agreements don't say how a refund should be split between the accounts. Pro rata by value is one option.
- **Disclosure:** Ngozi can only be told about her own account (…0003), so any message to her about the refund should cover only that account.

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
    {"label": "Total value 2026-03-31, SYN-48210001", "value": 892625.50, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "Total value 2026-03-31, SYN-48210002", "value": 434343.77, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "Total value 2026-03-31, SYN-48210003", "value": 580497.60, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "Cash 2026-03-31, SYN-48210001", "value": 28030.21, "source": "custodian/cash.csv"},
    {"label": "Cash 2026-03-31, SYN-48210002", "value": 4742.48, "source": "custodian/cash.csv"},
    {"label": "Cash 2026-03-31, SYN-48210003", "value": 11461.79, "source": "custodian/cash.csv"},
    {"label": "Tier 1 annual rate (up to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "Tier 2 annual rate (1,000,000 to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "Tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts one billing group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups last changed (still split BG-4821-1 / BG-4821-2)", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "Old group BG-4821-1 value (0001 + 0002)", "value": 1326969.27, "source": "documents/statement-SYN-48210001-2026Q1.pdf", "computed": true},
    {"label": "Old group BG-4821-1 quarterly fee", "value": 3153.94, "source": "portfolio/billing.json", "computed": true},
    {"label": "Old group BG-4821-2 quarterly fee", "value": 1451.24, "source": "portfolio/billing.json", "computed": true},
    {"label": "Householded billable value 2026-03-31", "value": 1907466.87, "source": "documents/statement-SYN-48210003-2026Q1.pdf", "computed": true},
    {"label": "Householded annual fee", "value": 17259.73, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct quarterly fee", "value": 4314.93, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled", "value": 290.25, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The November 2024 householding letter (AGR-4821-3) requires the joint account, Henrik's IRA and Ngozi's account to be billed as one group, but the portfolio system still bills them as two groups, so Ngozi's $580,497.60 was charged at the 1.00% first tier instead of 0.80%. On the combined 31 March 2026 value of $1,907,466.87 the FS-STD fee is $4,314.93 for the quarter, against $4,605.18 debited, an overcharge of $290.25. Earlier quarters billed since the letter took effect are probably affected the same way and should be recalculated."
}
```