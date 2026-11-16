The 2 April 2026 fees were wrong: the household was **overbilled by $508.56**. $5,453.41 was debited, but the agreements and schedule call for $4,944.85.

**Why.** The firm signed a householding letter (AGR-4821-3) with all three household members on 18 November 2024. It says the joint account, Henrik's IRA and Ngozi's individual account are billed together as one group from the next billing cycle. The portfolio system was never updated to match. It still has two billing groups, both last changed on 14 September 2021: BG-4821-1 holds accounts 0001 and 0002, and BG-4821-2 holds 0003 alone. Because of that split, Ngozi's account was charged at the 1.00% tier on its own instead of being combined with her parents' accounts and reaching the cheaper tiers.

**Quarter-end values (31 March 2026).** The custodian's positions and cash files agree with the Q1 statements to the cent.

| Account | Positions + cash | Statement total |
|---|---|---|
| SYN-48210001 | 972,242.83 + 51,340.38 | 1,023,583.21 |
| SYN-48210002 | 545,621.18 + 6,815.97 | 552,437.15 |
| SYN-48210003 | 709,833.60 + 10,713.51 | 720,547.11 |

**What was debited.** The schedule (FS-STD) charges 1.00% a year on the first $1M, 0.80% to $2M and 0.60% above that, billed quarterly in arrears.
- BG-4821-1 (accounts 0001 and 0002): 1,576,020.36 in total. The fee is 1,000,000 × 0.01/4 = 2,500.00, plus 576,020.36 × 0.008/4 = 1,152.04, giving 3,652.04. That matches the debits of 2,371.90 + 1,280.14.
- BG-4821-2 (account 0003): 720,547.11 × 0.01/4 = 1,801.37, which matches the debit.
- So the system applied the schedule correctly to its own groups. The total debited was **5,453.41**.

**What it should have been.** All three accounts form one group of 2,296,567.47.
- First tier: 1,000,000 × 0.0025 = 2,500.00
- Second tier: 1,000,000 × 0.0020 = 2,000.00
- Third tier: 296,567.47 × 0.0015 = 444.85
- That gives **4,944.85**, and 5,453.41 − 4,944.85 = **508.56** overbilled.

Nothing in the CRM or the agreements reverses or delays the householding letter. The October 2025 annual review note records "No changes requested." This quarter isn't the only one affected: earlier fee debits in the transactions file match the same two-group billing (for example, Q4 2025 account 0003: 675,216.44 × 0.0025 = 1,688.04). That suggests the overbilling has repeated since the letter took effect. I only recomputed Q1 2026 in full.

```json
{
  "finding": "fee_error",
  "debited_fee": 5453.41,
  "correct_fee": 4944.85,
  "amount_misbilled": 508.56,
  "figures": [
    {"label": "Fee debited SYN-48210001, 2026-04-02", "value": 2371.90, "source": "custodian/transactions.csv"},
    {"label": "Fee debited SYN-48210002, 2026-04-02", "value": 1280.14, "source": "custodian/transactions.csv"},
    {"label": "Fee debited SYN-48210003, 2026-04-02", "value": 1801.37, "source": "custodian/transactions.csv"},
    {"label": "Total fee debited 2026-04-02", "value": 5453.41, "source": "custodian/transactions.csv", "computed": true},
    {"label": "Tier 1 annual rate (to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "Tier 2 annual rate (to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "Tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts billed as one group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups last changed (BG-4821-1: 0001+0002; BG-4821-2: 0003)", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "SYN-48210001 positions value 2026-03-31", "value": 972242.83, "source": "custodian/positions.csv", "computed": true},
    {"label": "SYN-48210001 settled cash 2026-03-31", "value": 51340.38, "source": "custodian/cash.csv"},
    {"label": "SYN-48210001 total 2026-03-31", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf"},
    {"label": "SYN-48210002 positions value 2026-03-31", "value": 545621.18, "source": "custodian/positions.csv", "computed": true},
    {"label": "SYN-48210002 settled cash 2026-03-31", "value": 6815.97, "source": "custodian/cash.csv"},
    {"label": "SYN-48210002 total 2026-03-31", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf"},
    {"label": "SYN-48210003 positions value 2026-03-31", "value": 709833.60, "source": "custodian/positions.csv", "computed": true},
    {"label": "SYN-48210003 settled cash 2026-03-31", "value": 10713.51, "source": "custodian/cash.csv"},
    {"label": "SYN-48210003 total 2026-03-31", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf"},
    {"label": "BG-4821-1 billed value (0001+0002)", "value": 1576020.36, "source": "portfolio/household.json", "computed": true},
    {"label": "BG-4821-1 recomputed fee (2500.00 + 576020.36*0.008/4)", "value": 3652.04, "source": "portfolio/billing.json", "computed": true},
    {"label": "BG-4821-2 recomputed fee (720547.11*0.01/4)", "value": 1801.37, "source": "portfolio/billing.json", "computed": true},
    {"label": "Combined household billing value per AGR-4821-3", "value": 2296567.47, "source": "crm/crm.json", "computed": true},
    {"label": "Correct fee (2500.00 + 2000.00 + 296567.47*0.006/4)", "value": 4944.85, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled (5453.41 - 4944.85)", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The November 2024 householding letter (AGR-4821-3) requires all three accounts to be billed as one group, but the portfolio system still bills them as two groups (last changed in 2021), so Ngozi's account was charged at the 1.00% tier on its own. Applying FS-STD to the combined 31 March 2026 value of $2,296,567.47 gives $4,944.85 against $5,453.41 debited. The household was overbilled by $508.56."
}
```