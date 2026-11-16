The fees debited on 2 April 2026 were wrong. The household was overbilled by **$508.56**: $5,453.41 was taken when the agreements call for $4,944.85.

**What went wrong**
- The firm's portfolio system (`portfolio/household.json`) still bills the household as two separate groups. The joint account (SYN-48210001) and Henrik's IRA (SYN-48210002) are in one group, and Ngozi's account (SYN-48210003) is billed on its own. Both groups were last changed on 2021-09-14.
- On 2024-11-18 all three people signed a householding letter (`crm/crm.json`, AGR-4821-3). It says all three accounts are to be "billed together as one group from the next billing cycle." The billing groups were never updated to match.
- Because Ngozi's $720,547.11 is billed alone, it is charged entirely at the top 1.00% rate. Billed together, the household's $2,296,567.47 would reach the 0.80% and 0.60% tiers.

**Checking the numbers**
- The 31 March 2026 values on the three statements match the custodian's position and cash files exactly.
- The amounts debited are exactly what the two-group setup produces:
  - Joint account plus IRA: $1,576,020.36 × the tiered rate ÷ 4 = $3,652.04. That matches the $2,371.90 + $1,280.14 debited.
  - Ngozi's account: $720,547.11 × 1% ÷ 4 = $1,801.37. That matches the debit.
- So the error is the grouping, not the arithmetic.
- Correct fee for the single group: ($10,000 + $8,000 + $296,567.47 × 0.6%) ÷ 4 = $4,944.85.
- If that fee is split across the accounts in proportion to their value, the rounded shares are $2,203.93, $1,189.48 and $1,551.45. These add up to $4,944.86 because of a one-cent rounding difference.

**Follow-up**
- "Next billing cycle" after 18 November 2024 would be the quarter that ended 31 December 2024. That suggests the earlier 2025 debits and the January 2026 debit were also overcharged. Someone should recalculate those quarters and refund the difference.
- The billing groups in the portfolio system need to be merged into one before the next billing run.

```json
{
  "finding": "fee_error",
  "debited_fee": 5453.41,
  "correct_fee": 4944.85,
  "amount_misbilled": 508.56,
  "figures": [
    {"label": "Fee debited 2026-04-02, SYN-48210001", "value": 2371.90, "source": "custodian/transactions.csv"},
    {"label": "Fee debited 2026-04-02, SYN-48210002", "value": 1280.14, "source": "custodian/transactions.csv"},
    {"label": "Fee debited 2026-04-02, SYN-48210003", "value": 1801.37, "source": "custodian/transactions.csv"},
    {"label": "Total fee debited 2026-04-02", "value": 5453.41, "source": "custodian/transactions.csv", "computed": true},
    {"label": "SYN-48210001 value 2026-03-31 (positions plus cash)", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "SYN-48210002 value 2026-03-31 (positions plus cash)", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "SYN-48210003 value 2026-03-31 (positions plus cash)", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "Cash 2026-03-31 SYN-48210001 / 0002 / 0003 (matches statements)", "value": "51340.38 / 6815.97 / 10713.51", "source": "custodian/cash.csv"},
    {"label": "FS-STD tier 1 annual rate up to 1,000,000", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 2 annual rate 1,000,000 to 2,000,000", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 3 annual rate above 2,000,000", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts billed as one group from next cycle)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups on file (BG-4821-1: 0001+0002; BG-4821-2: 0003), last changed", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "BG-4821-1 value as billed (0001+0002)", "value": 1576020.36, "source": "portfolio/household.json", "computed": true},
    {"label": "BG-4821-1 quarterly fee as billed", "value": 3652.04, "source": "portfolio/billing.json", "computed": true},
    {"label": "BG-4821-2 quarterly fee as billed", "value": 1801.37, "source": "portfolio/billing.json", "computed": true},
    {"label": "Household combined billable value 2026-03-31", "value": 2296567.47, "source": "documents/index.json", "computed": true},
    {"label": "Correct annual fee on combined value", "value": 19779.40, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct quarterly fee", "value": 4944.85, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The householding letter AGR-4821-3 (signed 2024-11-18) requires all three accounts to be billed as one group, but the portfolio system still bills them as two groups, so Ngozi's account is charged entirely at the 1% tier. On the combined 31 March 2026 value of $2,296,567.47, schedule FS-STD gives a quarterly fee of $4,944.85, while $5,453.41 was debited, an overcharge of $508.56. Earlier quarters since the letter were probably overbilled the same way and should be recalculated."
}
```