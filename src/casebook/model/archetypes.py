"""The ten archetypes (docs/SPEC.md, Archetypes)."""

from pathlib import Path

# docs/SPEC.md: "The featured pairs for archetypes 7 and 8 are absent from the repo and the site
# until the freeze is recorded." Slice 12's `casebook freeze` writes the record.
HELD_OUT_ARCHETYPES = (7, 8)
FREEZE_RECORD = Path(__file__).resolve().parents[3] / "published" / "freeze.json"


def frozen() -> bool:
    return FREEZE_RECORD.is_file()


ARCHETYPES: dict[int, str] = {
    1: "Dual-income accumulators",
    2: "High-income household near thresholds",
    3: "Concentrated executive",
    4: "Pre-RMD retiree",
    5: "First-RMD retiree",
    6: "Established RMD retiree with QCDs",
    7: "Inherited-IRA beneficiary",
    8: "Recently widowed investor",
    9: "Cross-account tax-loss harvester",
    10: "Fee and IPS drift household",
}

# A private pair is a background pair the private set runs on (docs/SPEC.md, Private set): drawn only with
# the private salt, which lives in $CASEBOOK_PRIVATE, into $CASEBOOK_PRIVATE, and never published. Its
# household IDs, archetype, pair and roles stay in the public ID ledger; its content is secret. The public
# repo stated the answers of these pairs' unsalted draw (owner's decision, 16 November 2026), so that draw
# is burned and never used. Keyed (archetype, pair).
PRIVATE_PAIRS = frozenset({(10, 3), (4, 2), (6, 4), (9, 2)})
