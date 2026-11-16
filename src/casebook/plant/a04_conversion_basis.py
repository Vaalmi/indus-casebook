"""Archetype 4. Pre-RMD retiree: a Roth conversion from an IRA with after-tax basis.

The trap's basis, carried from old nondeductible contributions, makes part of the conversion
nontaxable, pro rata over every traditional IRA at year end (Form 8606, worked in archetype 1's
module). The custodian does not track basis, so its records show the whole conversion going out;
that is how custodians work, not a disagreement. The unresolved twin has no basis on file but a
CRM record of the client's belief that she made nondeductible contributions.
"""

from casebook.model.events import RothConversion
from casebook.model.files import ACCOUNTS_CSV, CRM_JSON, PORTFOLIO_TAX_PROFILE, TRANSACTIONS_CSV
from casebook.model.money import usd
from casebook.model.registry import RegistryEntry
from casebook.plant.a01_backdoor_roth import TAX_YEAR, YEAR_END, Form8606, form_8606, ira_basis
from casebook.plant.common import PlantContext, PlantError, Planting

ITEM_TYPE = "conversion_ira_basis"
# The twin's CRM record of a belief in basis no Form 8606 shows: its summary names both.
BELIEF_WORDS = ("nondeductible", "Form 8606")


def _converter(context: PlantContext) -> str:
    hh = context.script.household
    people = {
        hh.owners(e.account_id)[0] for e in context.events if isinstance(e, RothConversion) and e.date.year == TAX_YEAR
    }
    if len(people) != 1:
        raise PlantError(f"{context.script.source}: one person converts to a Roth IRA in {TAX_YEAR}")
    return people.pop()


def _conversion(context: PlantContext, form: Form8606) -> RothConversion:
    conversions = [
        e
        for e in context.events
        if isinstance(e, RothConversion) and e.date.year == TAX_YEAR and e.account_id in form.ira_ids
    ]
    if not conversions:
        raise PlantError(f"{context.script.source}: {form.person_id} converted nothing to a Roth IRA in {TAX_YEAR}")
    if len(conversions) > 1:
        raise PlantError(f"{context.script.source}: archetype 4 converts once in {TAX_YEAR}")
    return conversions[0]


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    spec, hh = script.planted, script.household
    person_id = spec.details["person_id"]
    person = hh.person(person_id).name
    form = form_8606(context, person_id)
    conversion = _conversion(context, form)
    if form.line2 <= 0:
        raise PlantError(f"{spec.item_id}: {person}'s tax profile carries no IRA basis")
    if form.line1 != 0:
        raise PlantError(f"{spec.item_id}: archetype 4's basis is carried in, with no {TAX_YEAR} contribution")
    if form.line10 >= 1:
        raise PlantError(f"{spec.item_id}: the basis covers the whole conversion, so nothing is prorated")
    conclusion = (
        f"{person} converted {usd(form.line8)} from the traditional IRA {conversion.account_id} to the Roth IRA "
        f"{conversion.to_account_id} on {conversion.date.isoformat()}. The 2024 return carries {usd(form.line2)} "
        f"of after-tax basis in {person}'s traditional IRAs from old nondeductible contributions (Form 8606 "
        f"line 2), so the conversion is not all taxable. Nor is the basis simply subtracted from it: under the "
        f"pro-rata rule of IRC § 408(d)(2), which Form 8606 Part I applies, the basis is spread over the value of "
        f"all {person}'s traditional IRAs on {YEAR_END.isoformat()} ({usd(form.line6)}, line 6) plus the amount "
        f"converted, so line 10 is {form.line10:.3f}. {usd(form.line11)} of the conversion is nontaxable and "
        f"{usd(form.line18)} is taxable income for {TAX_YEAR} (line 18); {usd(form.line14)} of basis carries to "
        f"2026 (line 14). The custodian's records show the whole {usd(form.line8)} going out of the IRA, because "
        f"custodians do not track IRA basis; the basis is on Form 8606, not in the custodian's files."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="situation",
        item_type=spec.item_type,
        title="Roth conversion from an IRA with after-tax basis, taxed pro rata",
        sources=(TRANSACTIONS_CSV, ACCOUNTS_CSV, PORTFOLIO_TAX_PROFILE, CRM_JSON),
        conclusion=conclusion,
        figures=(
            ("Converted", usd(form.line8)),
            ("Nontaxable part (Form 8606 line 17)", usd(form.line17)),
            ("Taxable amount (Form 8606 line 18)", usd(form.line18)),
            ("Basis carried to 2026 (Form 8606 line 14)", usd(form.line14)),
        ),
        table=form.table(),
        known_as_of=YEAR_END,
        references=(*form.conversion_ids, *form.ira_ids, conversion.to_account_id, person_id),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """An unresolved twin converts the same way with no basis on file, and a CRM record says the
    client believes she made nondeductible contributions that no Form 8606 shows."""
    where, hh = context.script.source, context.script.household
    if kind != "unresolved":
        raise PlantError(f"{where}: archetype 4's twin is unresolved, not {kind!r}")
    person_id = _converter(context)
    form = form_8606(context, person_id)
    _conversion(context, form)
    if ira_basis(context, person_id) != 0:
        raise PlantError(f"{where}: an unresolved twin has no IRA basis on file")
    if not any(all(word in a.summary for word in BELIEF_WORDS) for a in hh.crm_activities):
        raise PlantError(
            f"{where}: an unresolved twin has a CRM record of nondeductible contributions no Form 8606 shows"
        )
    return Planting()
