**No, the fees were wrong. The household was overcharged by $508.56.** On 2 April 2026, $5,453.41 was debited. Under the signed agreements, the fee should have been $4,944.85.

**Why it's wrong.** On 18 November 2024, all three parties signed a householding letter (AGR-4821-3, in `crm/crm.json`). It says the joint account, Henrik's IRA and Ngozi's account "are billed together as one group from the next billing cycle." The firm's portfolio system never put that in place. `portfolio/household.json` still has two billing groups: BG-4821-1 (…0001 and …0002) and BG-4821-2 (…0003 alone). Both were last changed on 14 September 2021, before the letter was signed. So Ngozi's account was billed on its own and paid the 1.00% top tier on all of its value. Nothing in the files reverses the letter or approves an exception. The annual review on 14 October 2025 records "No changes requested."

**Quarter-end values at 31 March 2026.** Custodian positions plus settled cash. The quarterly statements show the same totals, and there was no unsettled cash.
- …0001: 972,242.83 positions + 51,340.38 cash = **1,023,583.21**
- …0002: 545,621.18 positions + 6,815.97 cash = **552,437.15**
- …0003: 709,833.60 positions + 10,713.51 cash = **720,547.11**

**What was debited, rebuilt from the two groups the system used:**
- BG-4821-1, valued at 1,576,020.36: (1,000,000 × 1.00% + 576,020.36 × 0.80%) ÷ 4 = 3,652.04. The debits were 2,371.90 + 1,280.14 = 3,652.04, so they match.
- BG-4821-2, valued at 720,547.11: 720,547.11 × 1.00% ÷ 4 = 1,801.37. The debit was 1,801.37, so it matches.
- Total debited: **5,453.41**

The system calculated each of its groups correctly. The mistake is in how the accounts were grouped.

**What the agreements call for: one group valued at 2,296,567.47**
- (1,000,000 × 1.00% + 1,000,000 × 0.80% + 296,567.47 × 0.60%) ÷ 4
- = (10,000 + 8,000 + 1,779.40) ÷ 4
- = **4,944.85**

**Amount overbilled:** 5,453.41 − 4,944.85 = **508.56**

**Things to follow up:**
- The custodian's records show the same split billing for every quarter in 2025 and for Q4 2025. Earlier quarters were probably overbilled too, depending on when the "next billing cycle" began.
- The fee schedule file is dated 15 April 2026. I assumed the same tiers applied at 31 March, because the agreements refer to the "standard fee schedule."
- How a refund is split across the accounts is a separate question. Ngozi can only be told about her own account (…0003), which matters when you talk to the family about the correction.

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
    {"label": "SYN-48210001 positions value 2026-03-31", "value": 972242.83, "source": "custodian/positions.csv", "computed": true},
    {"label": "SYN-48210001 settled cash 2026-03-31", "value": 51340.38, "source": "custodian/cash.csv"},
    {"label": "SYN-48210001 total value 2026-03-31", "value": 1023583.21, "source": "documents/statement-SYN-48210001-2026Q1.pdf", "computed": true},
    {"label": "SYN-48210002 positions value 2026-03-31", "value": 545621.18, "source": "custodian/positions.csv", "computed": true},
    {"label": "SYN-48210002 settled cash 2026-03-31", "value": 6815.97, "source": "custodian/cash.csv"},
    {"label": "SYN-48210002 total value 2026-03-31", "value": 552437.15, "source": "documents/statement-SYN-48210002-2026Q1.pdf", "computed": true},
    {"label": "SYN-48210003 positions value 2026-03-31", "value": 709833.60, "source": "custodian/positions.csv", "computed": true},
    {"label": "SYN-48210003 settled cash 2026-03-31", "value": 10713.51, "source": "custodian/cash.csv"},
    {"label": "SYN-48210003 total value 2026-03-31", "value": 720547.11, "source": "documents/statement-SYN-48210003-2026Q1.pdf", "computed": true},
    {"label": "Tier 1 annual rate (to 1,000,000)", "value": 0.0100, "source": "portfolio/billing.json"},
    {"label": "Tier 2 annual rate (to 2,000,000)", "value": 0.0080, "source": "portfolio/billing.json"},
    {"label": "Tier 3 annual rate (above 2,000,000)", "value": 0.0060, "source": "portfolio/billing.json"},
    {"label": "Householding agreement AGR-4821-3 signed (all three accounts billed as one group)", "value": "2024-11-18", "source": "crm/crm.json"},
    {"label": "Billing groups in portfolio system last changed", "value": "2021-09-14", "source": "portfolio/household.json"},
    {"label": "BG-4821-1 value (SYN-48210001 + SYN-48210002)", "value": 1576020.36, "source": "custodian/positions.csv", "computed": true},
    {"label": "BG-4821-1 quarterly fee as billed", "value": 3652.04, "source": "portfolio/billing.json", "computed": true},
    {"label": "BG-4821-2 quarterly fee as billed (SYN-48210003 alone)", "value": 1801.37, "source": "portfolio/billing.json", "computed": true},
    {"label": "Householded group value (all three accounts)", "value": 2296567.47, "source": "custodian/positions.csv", "computed": true},
    {"label": "Correct householded quarterly fee", "value": 4944.85, "source": "portfolio/billing.json", "computed": true},
    {"label": "Amount overbilled", "value": 508.56, "source": "custodian/transactions.csv", "computed": true}
  ],
  "explanation": "The householding letter AGR-4821-3, signed 2024-11-18, requires all three accounts to be billed as one group, but the portfolio system still bills SYN-48210003 in its own group (unchanged since 2021). Ngozi's account was therefore charged the 1.00% top tier on all of its value instead of sharing the household's combined value of $2,296,567.47. Charged as one group, the quarterly fee is $4,944.85, so the $5,453.41 debited is $508.56 too much."
}
```