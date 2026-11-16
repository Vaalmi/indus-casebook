The fees debited on 2 April 2026 were too high. They were billed as two separate groups, but the householding agreement says all three accounts should be billed as one group. The household was overcharged **$508.56**.

**What was debited (custodian/transactions.csv)**
- SYN-48210001 (joint account): $2,371.90
- SYN-48210002 (Henrik's IRA): $1,280.14
- SYN-48210003 (Ngozi's account): $1,801.37
- **Total: $5,453.41**

**What the agreements require**
- AGR-4821-1 and AGR-4821-2 put all three accounts on the standard fee schedule, FS-STD. Its annual rates are 1.00% on the first $1M, 0.80% from $1M to $2M, and 0.60% above $2M. The fee is charged quarterly after the quarter ends, on positions plus cash, per billing group.
- AGR-4821-3, the householding letter signed 18 November 2024, says the three accounts "are billed together as one group from the next billing cycle."
- The portfolio system was never updated to match. `portfolio/household.json` still has two billing groups, BG-4821-1 (accounts 0001 and 0002) and BG-4821-2 (account 0003), both last changed in 2021.

**Values on 31 March 2026**
Each statement total matches the custodian's position and cash files.
- SYN-48210001: $1,023,583.21
- SYN-48210002: $552,437.15
- SYN-48210003: $720,547.11
- Household total: $2,296,567.47

**How the debit was calculated:** I reproduced it exactly using the old two-group setup.
- Group 1, on $1,576,020.36: ($10,000 + $576,020.36 × 0.8%) ÷ 4 = $3,652.04, which equals $2,371.90 + $1,280.14.
- Group 2, on $720,547.11: × 1% ÷ 4 = $1,801.37.

**Correct fee (one group, $2,296,567.47):** ($10,000 + $8,000 + $296,567.47 × 0.6%) ÷ 4 = $19,779.40 ÷ 4 = **$4,944.85**

**Overcharge:** $5,453.41 − $4,944.85 = **$508.56**

The householding letter took effect from the cycle after November 2024, so the quarterly fees debited since then were probably also too high. I only checked this quarter, so those earlier amounts still need to be calculated before any refund.

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
    {"label": "FS-STD tier 1 annual rate (up to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 2 annual rate (1,000,000 to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding letter AGR-4821-3 signed (all three accounts billed as one group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups in portfolio system last changed (still two groups)", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "SYN-48210001 value 2026-03-31 (positions plus cash)", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "SYN-48210002 value 2026-03-31 (positions plus cash)", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "SYN-48210003 value 2026-03-31 (positions plus cash)", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "SYN-48210001 cash 2026-03-31", "value": 51340.38, "source": "custodian/cash.csv"},
    {"label": "SYN-48210002 cash 2026-03-31", "value": 6815.97, "source": "custodian/cash.csv"},
    {"label": "SYN-48210003 cash 2026-03-31", "value": 10713.51, "source": "custodian/cash.csv"},
    {"label": "Household billable value 2026-03-31", "value": 2296567.47, "source": "documents/index.json", "computed": true},
    {"label": "Fee as billed, group BG-4821-1 (1,576,020.36)", "value": 3652.04, "source": "portfolio/household.json", "computed": true},
    {"label": "Fee as billed, group BG-4821-2 (720,547.11)", "value": 1801.37, "source": "portfolio/household.json", "computed": true},
    {"label": "Correct annual fee, single household group", "value": 19779.40, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct quarterly fee, single household group", "value": 4944.85, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The 2 April 2026 debits of $5,453.41 match the standard schedule applied to two separate billing groups (joint account plus IRA, and Ngozi's account on its own), which is how the portfolio system has been set up since 2021. The householding letter AGR-4821-3, signed 18 November 2024, puts all three accounts in one billing group, and on the combined 31 March 2026 value of $2,296,567.47 the schedule gives a quarterly fee of $4,944.85. The household was overbilled by $508.56 this quarter, and the quarters since the letter took effect probably need checking too."
}
```