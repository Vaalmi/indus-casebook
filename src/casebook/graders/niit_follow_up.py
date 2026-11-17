"""The grader for T-MTG-03 and T-MTG-04: the year-end planning call on the net investment income tax, the SALT
limit and asset location, then the follow-up in the CRM and the client's message, scored against `keys.niit`
on the sandbox's diff and the jury.

Points: output parses 10, finding 20, net investment income tax 15, modified AGI 10, planning 10 (the SALT
deduction limit within a dollar, and asset location naming exactly the fixed-income funds the taxable
accounts hold), follow-up 20 (a note stating the tax, or where none is owed modified AGI; and an activity),
tone 15. The finding and the tax are essential. The tax found on the twin, which stays under the threshold,
is a false alarm.
"""

from pathlib import Path

from casebook.graders.common import Grade, close, counts_for
from casebook.graders.follow_up import CLIENT_MESSAGE, FollowUp
from casebook.graders.meeting_follow_up import Result, amount_result, grade_meeting, output_parses, read_answer
from casebook.keys.niit import NIIT_OWED, NO_NIIT, ZERO, NiitKey
from casebook.model.money import fmt

FINDINGS = (NIIT_OWED, NO_NIIT, "unresolved")
NIIT, MODIFIED_AGI, SALT_LIMIT, ASSET_LOCATION = "niit", "modified_agi", "salt_limit", "asset_location"
REQUIRED_FIELDS = (
    "finding",
    NIIT,
    MODIFIED_AGI,
    SALT_LIMIT,
    ASSET_LOCATION,
    "figures",
    "explanation",
    CLIENT_MESSAGE,
)
FINDING, PLANNING = "finding", "planning"
POINTS = {FINDING: 20, NIIT: 15, MODIFIED_AGI: 10, PLANNING: 10}


def _planning(data: dict[str, object], salt_limit_ok: bool, key: NiitKey) -> Result:
    raw = data.get(ASSET_LOCATION)
    named = {str(s) for s in raw} if isinstance(raw, list) else None
    expected = set(key.bonds_in_taxable) if key.asset_location_point else set()
    location_ok = named == expected
    detail = (
        f"SALT limit {'right' if salt_limit_ok else 'wrong'} (key {fmt(key.salt_limit)}); asset location names "
        f"{sorted(named) if named is not None else 'no list'} (key {sorted(expected)})"
    )
    return (PLANNING, POINTS[PLANNING], salt_limit_ok and location_ok, detail)


def grade(output_text: str, key: NiitKey, fixtures: Path, follow_up: FollowUp) -> Grade:
    answer = read_answer(output_text, REQUIRED_FIELDS, FINDINGS, (NIIT, MODIFIED_AGI, SALT_LIMIT), (ASSET_LOCATION,))
    results = [
        output_parses(answer),
        (
            FINDING,
            POINTS[FINDING],
            answer.finding == key.finding,
            f"answer {answer.finding or 'none'}, key {key.finding}",
        ),
        amount_result(NIIT, POINTS[NIIT], answer, key.niit, null_ok=True),
        amount_result(MODIFIED_AGI, POINTS[MODIFIED_AGI], answer, key.modified_agi, null_ok=False),
        _planning(answer.data, close(answer.amounts[SALT_LIMIT], key.salt_limit), key),
    ]
    note = (key.niit, "the net investment income tax") if key.niit > ZERO else (key.modified_agi, "modified AGI")
    return grade_meeting(
        output_text,
        answer,
        results,
        essential=(FINDING, NIIT),
        counts=counts_for(answer.finding, key.finding, alarm=(NIIT_OWED,), clean=(NO_NIIT,)),
        headline=[(name, answer.amounts[name]) for name in (NIIT, MODIFIED_AGI, SALT_LIMIT)],
        computed=[f.value for f in key.computed_figures],
        fixtures=fixtures,
        follow_up=follow_up,
        note=note,
    )
