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
