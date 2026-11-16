"""Planted items: check the situation a script claims really holds, and write its registry entry.

One module per archetype. Each names the planted item type its trap carries, plants it
(`plant_trap`), and checks that the twin is what its script says it is (`check_twin`): clean, a
near miss or unresolved.
"""

import dataclasses
from types import ModuleType

from casebook.model.registry import RealRange
from casebook.plant import (
    a01_backdoor_roth,
    a02_niit,
    a03_rsu_basis,
    a04_conversion_basis,
    a05_first_rmd,
    a06_qcd,
    a07_inherited_ira,
    a08_widowed,
    a09_wash_sale,
    a10_fee_breakpoint,
)
from casebook.plant.common import PlantContext, PlantError, Planting
from casebook.securities.real_ranges import real_ranges

__all__ = ["PlantContext", "PlantError", "Planting", "plant"]

ARCHETYPE_PLANTERS: dict[int, ModuleType] = {
    1: a01_backdoor_roth,
    2: a02_niit,
    3: a03_rsu_basis,
    4: a04_conversion_basis,
    5: a05_first_rmd,
    6: a06_qcd,
    7: a07_inherited_ira,
    8: a08_widowed,
    9: a09_wash_sale,
    10: a10_fee_breakpoint,
}


def plant(context: PlantContext) -> Planting:
    script = context.script
    module = ARCHETYPE_PLANTERS[script.household.archetype]
    if script.planted is not None:
        if script.planted.item_type != module.ITEM_TYPE:
            raise PlantError(
                f"{script.source}: archetype {script.household.archetype} plants {module.ITEM_TYPE!r}, "
                f"not {script.planted.item_type!r}"
            )
        planting: Planting = module.plant_trap(context)
    else:
        assert script.twin is not None
        planting = module.check_twin(context, script.twin.kind)
    return _with_real_range(context, planting)


def _with_real_range(context: PlantContext, planting: Planting) -> Planting:
    """The household's entry carries the cited real range of the security its task turns on, if any."""
    cited = real_ranges().get(context.script.household.household_id)
    if cited is None:
        return planting
    if len(planting.entries) != 1:
        raise PlantError(f"{context.script.household.household_id}: a cited real range needs the household's one entry")
    real = RealRange(
        task_id=cited.task_id,
        security_id=cited.security_id,
        security=context.label(cited.security_id),
        low=cited.low,
        high=cited.high,
        source=cited.source,
    )
    return dataclasses.replace(planting, entries=[dataclasses.replace(planting.entries[0], real_range=real)])
