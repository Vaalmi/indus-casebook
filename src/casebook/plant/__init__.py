"""Planted items: check the situation a script claims really holds, and write its registry entry.

One module per archetype. Each names the planted item type its trap carries, plants it
(`plant_trap`), and checks that the twin is what its script says it is (`check_twin`): clean, a
near miss or unresolved.
"""

from types import ModuleType

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
    return planting
