The fee was wrong. **$5,453.41** was debited on 2 April 2026, but the agreements call for **$4,944.85**, so the household was overcharged by **$508.56**.

**Why it's wrong:** The householding letter (AGR-4821-3, signed 18 Nov 2024) says all three accounts are to be billed together as one group "from the next billing cycle." The portfolio system never made that change. `portfolio/household.json` still has the two billing groups set up in 2021 (`last_changed: 2021-09-14`):
- BG-4821-1 holds the joint account (…0001) and Henrik's IRA (…0002).
- BG-4821-2 holds Ngozi's account (…0003) on its own.

So Ngozi's whole balance was charged at the 1.00% first tier. Billed as one group, the household's combined value reaches the 0.80% and 0.60% tiers.

**Quarter-end values at 31 March 2026:** The statements match the custodian's position and cash files exactly.
- Joint account (…0001): $1,023,583.21
- Henrik's IRA (…0002): $552,437.15
- Ngozi's account (…0003): $720,547.11
- Combined: $2,296,567.47

**What was debited:** Both of the old groups were billed correctly under the schedule. The error is how the accounts were grouped, not the arithmetic.
- BG-4821-1, on $1,576,020.36: (10,000 + 576,020.36 × 0.8%) ÷ 4 = $3,652.04. This matches the debits of $2,371.90 + $1,280.14.
- BG-4821-2, on $720,547.11: 720,547.11 × 1% ÷ 4 = $1,801.37. This matches the debit.

**What it should have been:** On the combined $2,296,567.47: (10,000 + 8,000 + 296,567.47 × 0.6%) ÷ 4 = 19,779.40 ÷ 4 = **$4,944.85**.

**Follow-up:**
- Merge the billing groups in the portfolio system and refund the overcharge.
- The same grouping was used for every fee since the letter took effect. The quarterly fees from April 2025 to January 2026 were probably overcharged too, and possibly the January 2025 fee for Q4 2024. I didn't recalculate those quarters, so they need checking.
- Ngozi may only be told about her own account (…0003), so any message to her about the refund should mention only that account.

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
    {"label": "Quarter-end value 2026-03-31, SYN-48210001 (positions plus cash)", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "Quarter-end value 2026-03-31, SYN-48210002 (positions plus cash)", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "Quarter-end value 2026-03-31, SYN-48210003 (positions plus cash)", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "Cash 2026-03-31, SYN-48210001", "value": 51340.38, "source": "custodian/cash.csv"},
    {"label": "Cash 2026-03-31, SYN-48210002", "value": 6815.97, "source": "custodian/cash.csv"},
    {"label": "Cash 2026-03-31, SYN-48210003", "value": 10713.51, "source": "custodian/cash.csv"},
    {"label": "Tier 1 annual rate up to 1,000,000", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "Tier 2 annual rate 1,000,000 to 2,000,000", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "Tier 3 annual rate above 2,000,000", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts billed as one group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups last changed in portfolio system (still two groups)", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "Old group BG-4821-1 value (0001+0002)", "value": 1576020.36, "source": "portfolio/household.json", "computed": true},
    {"label": "Fee under old grouping, BG-4821-1", "value": 3652.04, "source": "portfolio/billing.json", "computed": true},
    {"label": "Fee under old grouping, BG-4821-2", "value": 1801.37, "source": "portfolio/billing.json", "computed": true},
    {"label": "Combined household billing value 2026-03-31", "value": 2296567.47, "source": "documents/index.json", "computed": true},
    {"label": "Annual fee on combined value", "value": 19779.40, "source": "portfolio/billing.json", "computed": true},
    {"label": "Correct quarterly fee (combined group)", "value": 4944.85, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The householding letter AGR-4821-3, signed 18 Nov 2024, says the joint account, Henrik's IRA and Ngozi's account are to be billed as one group, but the portfolio system still bills them as two groups set up in 2021. Billed as one group on the combined 31 March 2026 value of $2,296,567.47, the tiered FS-STD schedule gives a quarterly fee of $4,944.85, against $5,453.41 debited, an overcharge of $508.56. Fees for earlier quarters since the letter took effect were probably overcharged too and should be checked."
}
```