"""The filing status as the rules table spells it in parameter names."""

from casebook.model.tax import FILING_STATUSES


class EngineError(ValueError):
    pass


SUFFIX = dict(zip(FILING_STATUSES, ("single", "mfj", "mfs", "hoh"), strict=True))


def suffix(filing_status: str) -> str:
    if filing_status not in SUFFIX:
        raise EngineError(f"unknown filing status {filing_status!r}; expected one of {', '.join(FILING_STATUSES)}")
    return SUFFIX[filing_status]


def is_joint(filing_status: str) -> bool:
    return filing_status == "married_filing_jointly"


def is_separate(filing_status: str) -> bool:
    return filing_status == "married_filing_separately"


def is_married(filing_status: str) -> bool:
    return is_joint(filing_status) or is_separate(filing_status)
