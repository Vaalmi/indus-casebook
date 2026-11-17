"""The grader for T-MTG-01 and T-MTG-02: what a 2025 backdoor Roth conversion costs in tax, then the follow-up
in the CRM and the client's message, scored against `keys.backdoor_roth` on the sandbox's diff and the jury.

Points: output parses 10, finding 25, taxable amount 20 (Form 8606 line 18), basis carried 10 (line 14),
follow-up 20 (a note stating the taxable amount, or on a conversion with nothing taxable the amount
converted tax-free, line 17; and an activity), tone 15. The finding and the taxable amount are essential.
A pro-rata tax found on the twin, whose conversion is all nontaxable, is a false alarm.
"""

from pathlib import Path

from casebook.graders.common import Grade, counts_for
from casebook.graders.follow_up import CLIENT_MESSAGE, FollowUp
from casebook.graders.meeting_follow_up import amount_result, grade_meeting, output_parses, read_answer
from casebook.keys.backdoor_roth import NO_PRO_RATA_TAX, PRO_RATA_TAX, ZERO, BackdoorRothKey

FINDINGS = (PRO_RATA_TAX, NO_PRO_RATA_TAX, "unresolved")
TAXABLE_AMOUNT, BASIS_CARRIED = "taxable_amount", "basis_carried"
REQUIRED_FIELDS = ("finding", TAXABLE_AMOUNT, BASIS_CARRIED, "figures", "explanation", CLIENT_MESSAGE)
FINDING = "finding"
POINTS = {FINDING: 25, TAXABLE_AMOUNT: 20, BASIS_CARRIED: 10}


def grade(output_text: str, key: BackdoorRothKey, fixtures: Path, follow_up: FollowUp) -> Grade:
    answer = read_answer(output_text, REQUIRED_FIELDS, FINDINGS, (TAXABLE_AMOUNT, BASIS_CARRIED))
    results = [
        output_parses(answer),
        (
            FINDING,
            POINTS[FINDING],
            answer.finding == key.finding,
            f"answer {answer.finding or 'none'}, key {key.finding}",
        ),
        amount_result(TAXABLE_AMOUNT, POINTS[TAXABLE_AMOUNT], answer, key.taxable_amount, null_ok=True),
        amount_result(BASIS_CARRIED, POINTS[BASIS_CARRIED], answer, key.basis_carried, null_ok=True),
    ]
    if key.taxable_amount > ZERO:
        note = (key.taxable_amount, "the taxable amount")
    else:
        note = (key.backdoor.form.line_17 or ZERO, "the amount converted tax-free")
    return grade_meeting(
        output_text,
        answer,
        results,
        essential=(FINDING, TAXABLE_AMOUNT),
        counts=counts_for(answer.finding, key.finding, alarm=(PRO_RATA_TAX,), clean=(NO_PRO_RATA_TAX,)),
        headline=[(name, answer.amounts[name]) for name in (TAXABLE_AMOUNT, BASIS_CARRIED)],
        computed=[f.value for f in key.computed_figures],
        fixtures=fixtures,
        follow_up=follow_up,
        note=note,
    )
