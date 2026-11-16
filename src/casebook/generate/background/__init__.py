"""The 80 background households: pairs 2 to 5 of every archetype, drawn from the seed.

Each archetype's module draws a trap and its twin (`generate_pair`). A drawn pair must pass the same
planter as the featured pair, so a draw whose situation does not hold (a sale too small to cross a
threshold, a loss that is a gain) is drawn again from the same stream; the result depends only on
the seed. Background households take IDs from HH-0100 to HH-0999, a range no scripted household
uses, so no draw can collide with a featured or held-out ID.
"""

from types import ModuleType

from casebook.generate.background import (
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
from casebook.generate.background.common import PairSpec
from casebook.generate.script import HouseholdScript, ScriptError, validate_script
from casebook.generate.simulate import simulate
from casebook.model.archetypes import ARCHETYPES
from casebook.model.dates import QUARTER_ENDS, SCENARIO_DATE
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import overdrawn, replay
from casebook.securities.market import Market
from casebook.seeding import derive_rng

BACKGROUND_PAIRS = range(2, 6)
SNAPSHOT_DAYS = (*QUARTER_ENDS, SCENARIO_DATE)
FIRST_ID, LAST_ID = 100, 999
ATTEMPTS = 40

GENERATORS: dict[int, ModuleType] = {
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


class BackgroundError(RuntimeError):
    pass


def background_ids(seed: int) -> list[str]:
    """Two IDs for every background pair, drawn without repeats from HH-0100 to HH-0999."""
    rng = derive_rng("background-ids", seed)
    numbers = rng.sample(range(FIRST_ID, LAST_ID + 1), 2 * len(ARCHETYPES) * len(BACKGROUND_PAIRS))
    return [f"HH-{n:04d}" for n in numbers]


def _holds(script: HouseholdScript, market: Market) -> None:
    """Refuse a drawn household its planter or twin check refuses."""
    validate_script(script)
    simulation = simulate(script, market)
    replayed = replay(simulation.events, SNAPSHOT_DAYS)
    overdrafts = overdrawn(replayed)
    if overdrafts:
        raise ScriptError(script.source, "; ".join(overdrafts))
    plant(PlantContext(script, simulation.events, replayed, simulation.quarters, market))


def draw_pair(
    seed: int, archetype: int, pair: int, trap_id: str, twin_id: str, market: Market
) -> tuple[HouseholdScript, HouseholdScript]:
    rng = derive_rng("background", seed, archetype, pair)
    item_id = f"PI-{archetype:02d}{pair:02d}"
    problems: list[str] = []
    for _ in range(ATTEMPTS):
        spec = PairSpec(archetype, pair, trap_id, twin_id, item_id, rng)
        try:
            trap, twin = GENERATORS[archetype].generate_pair(spec, market)
            _holds(trap, market)
            _holds(twin, market)
        except (PlantError, ScriptError) as error:
            problems.append(str(error))
            continue
        return trap, twin
    raise BackgroundError(
        f"archetype {archetype}, pair {pair}: no draw held in {ATTEMPTS} attempts; the last: {problems[-1]}"
    )


def generate_background(seed: int, market: Market, archetypes: frozenset[int] | None = None) -> list[HouseholdScript]:
    """Every background pair, or those of the archetypes named (IDs stay where the full draw puts them)."""
    ids = iter(background_ids(seed))
    drawn: list[HouseholdScript] = []
    for archetype in sorted(ARCHETYPES):
        for pair in BACKGROUND_PAIRS:
            trap_id, twin_id = next(ids), next(ids)
            if archetypes is None or archetype in archetypes:
                drawn += draw_pair(seed, archetype, pair, trap_id, twin_id, market)
    return drawn
