**Answer: no, the fees were wrong.** The 2 April 2026 debits total **$5,453.41**. The agreements call for **$4,944.85**, so the household was **overbilled by $508.56**.

**Why.** The firm's portfolio system (`portfolio/household.json`) still bills two separate groups: the joint account and Henrik's IRA as one, and Ngozi's account as the other. That setup was last changed on 2021-09-14. But in the CRM (`crm/crm.json`) there is a householding letter, AGR-4821-3, signed on 2024-11-18 by Adaeze, Henrik and Ngozi. It says all three accounts "are billed together as one group from the next billing cycle." Nothing in the files reverses that letter, so it covers the March 2026 quarter. The billing groups were never updated to match it.

**The numbers.** The fee schedule (FS-STD) is billed quarterly in arrears on positions plus cash at quarter end. Annual rates are 1.00% on the first $1M, 0.80% from $1M to $2M, and 0.60% above $2M. The 31 March 2026 values on the statements match the custodian's position and cash files exactly:

| Account | 31 Mar 2026 value | Debited 2 Apr 2026 |
|---|---|---|
| SYN-48210001 (joint) | $1,023,583.21 | $2,371.90 |
| SYN-48210002 (Henrik's IRA) | $552,437.15 | $1,280.14 |
| SYN-48210003 (Ngozi) | $720,547.11 | $1,801.37 |
| **Total** | **$2,296,567.47** | **$5,453.41** |

- **What was charged:** the debits match the two-group billing to the cent.
  - Joint account plus IRA: $1,576,020.36, giving ($10,000 + $4,608.16) ÷ 4 = $3,652.04.
  - Ngozi's account: $720,547.11 × 1% ÷ 4 = $1,801.37.
  - So the schedule was applied correctly, just to the wrong groups.
- **What should have been charged:** one group of $2,296,567.47, giving ($10,000 + $8,000 + $1,779.40) ÷ 4 = **$4,944.85**.

**Follow-up:**
- **Earlier quarters:** the billing groups were never updated after the letter, so the earlier quarters it covers were probably overbilled too. I haven't recalculated those.
- **Refund split:** the files don't say how a combined fee should be split across the three accounts, so the $508.56 can't yet be allocated by account.
- **Fix the system:** the billing groups in the portfolio system need to be changed to match AGR-4821-3.

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
    {"label": "Quarter-end value 2026-03-31, SYN-48210001 (positions + cash)", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "Quarter-end value 2026-03-31, SYN-48210002 (positions + cash)", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "Quarter-end value 2026-03-31, SYN-48210003 (positions + cash)", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "Cash 2026-03-31, SYN-48210001", "value": 51340.38, "source": "custodian/cash.csv"},
    {"label": "Cash 2026-03-31, SYN-48210002", "value": 6815.97, "source": "custodian/cash.csv"},
    {"label": "Cash 2026-03-31, SYN-48210003", "value": 10713.51, "source": "custodian/cash.csv"},
    {"label": "Tier 1 annual rate (up to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "Tier 2 annual rate (1,000,000 to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "Tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts billed as one group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Portfolio-system billing groups last changed", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "Combined household billable value 2026-03-31", "value": 2296567.47, "source": "documents/index.json", "computed": true},
    {"label": "Two-group fee as billed: BG-4821-1 (1,576,020.36)", "value": 3652.04, "source": "portfolio/household.json", "computed": true},
    {"label": "Two-group fee as billed: BG-4821-2 (720,547.11)", "value": 1801.37, "source": "portfolio/household.json", "computed": true},
    {"label": "Correct quarterly fee, single householded group", "value": 4944.85, "source": "crm/crm.json", "computed": true},
    {"label": "Amount overbilled", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The householding letter AGR-4821-3 (signed 2024-11-18) requires all three accounts to be billed together as one group, but the portfolio system still bills them as two groups and was last changed in 2021. On the combined 31 March 2026 value of $2,296,567.47, the tiered schedule gives $4,944.85 for the quarter, against $5,453.41 debited. The household was overbilled by $508.56, and earlier quarters since the letter are probably affected too."
}
```