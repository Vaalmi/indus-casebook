No, the fees were wrong. The household was **overcharged by $508.56** for the quarter ended 31 March 2026.

**What went wrong.** The householding letter in the CRM (AGR-4821-3, signed 18 Nov 2024) says all three accounts are "billed together as one group from the next billing cycle". The portfolio system was never updated to match. It still splits them into two billing groups, both last changed on 2021-09-14:
- BG-4821-1 is the joint account (SYN-48210001) and Henrik's IRA (SYN-48210002).
- BG-4821-2 is Ngozi's individual account (SYN-48210003).

Because of the split, Ngozi's account was charged the full 1.00% first-tier rate on its own. If the accounts had been grouped, the household's combined value would have reached the 0.80% and 0.60% tiers.

**What was debited (values at 31 March 2026, quarterly fee = annual ÷ 4).** These amounts match the two-group setup exactly:
- **BG-4821-1:** $1,023,583.21 + $552,437.15 = $1,576,020.36. The annual fee is 1% on the first $1M ($10,000) plus 0.80% on $576,020.36 ($4,608.16), so the quarter is $3,652.04. That matches the debits of $2,371.90 + $1,280.14.
- **BG-4821-2:** 1% of $720,547.11 gives $1,801.37 for the quarter, which matches the debit.
- **Total debited:** $5,453.41

**What the agreements call for (one group).**
- Combined value: $2,296,567.47
- Annual fee: $10,000 + $8,000 + 0.60% × $296,567.47 ($1,779.40) = $19,779.40
- Quarterly fee: **$4,944.85**
- Overcharge: $5,453.41 − $4,944.85 = **$508.56**

Each account's holdings and cash in the custodian files match its Q1 statement. The two-group split also shows in every fee debit on file since then (April 2025 through January 2026). Those quarters were probably overcharged too, but I haven't calculated them.

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
    {"label": "SYN-48210001 value 2026-03-31 (positions + cash)", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "SYN-48210002 value 2026-03-31 (positions + cash)", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "SYN-48210003 value 2026-03-31 (positions + cash)", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "SYN-48210001 cash 2026-03-31", "value": 51340.38, "source": "custodian/cash.csv"},
    {"label": "SYN-48210002 cash 2026-03-31", "value": 6815.97, "source": "custodian/cash.csv"},
    {"label": "SYN-48210003 cash 2026-03-31", "value": 10713.51, "source": "custodian/cash.csv"},
    {"label": "FS-STD tier 1 rate (to $1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 2 rate (to $2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "FS-STD tier 3 rate (above $2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts one billing group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups in portfolio system last changed", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "Combined household billable value 2026-03-31", "value": 2296567.47, "source": "documents/statement-SYN-48210001-2026Q1.pdf", "computed": true},
    {"label": "Annual fee on combined value", "value": 19779.40, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct quarterly fee (one group)", "value": 4944.85, "source": "portfolio/billing.json", "computed": true},
    {"label": "Quarterly fee as billed, BG-4821-1", "value": 3652.04, "source": "portfolio/household.json", "computed": true},
    {"label": "Quarterly fee as billed, BG-4821-2", "value": 1801.37, "source": "portfolio/household.json", "computed": true},
    {"label": "Amount overbilled", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The November 2024 householding letter (AGR-4821-3) requires all three accounts to be billed as one group, but the portfolio system still bills them as two groups. As a result, Ngozi's account was charged 1.00% on its own instead of reaching the lower tiers with the rest of the household. Billed as one group on the 31 March 2026 value of $2,296,567.47, the quarterly fee is $4,944.85, not the $5,453.41 debited, so the household was overcharged $508.56."
}
```