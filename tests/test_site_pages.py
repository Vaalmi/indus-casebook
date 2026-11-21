"""Slice 5: every public featured household has its page, with its item and three truth layers."""

import html as markup
import json
import re
from pathlib import Path

import pytest

from .conftest import FEATURED


@pytest.mark.parametrize("household", FEATURED)
def test_each_public_featured_household_has_a_page_with_its_item_and_layers(site: Path, household: str) -> None:
    html = (site / "households" / f"{household}.html").read_text()
    sealed = json.loads(next((site / "data").rglob("sealed/households.json")).read_text())["households"]
    role = next(h for h in sealed if h["household_id"] == household)["role"]
    layers = re.findall(r'data-truth-layer="(\w+)"', html)
    assert layers == ["events", "observations", "conclusion"]
    events = html.split('data-truth-layer="events"')[1].split("</table>")[0]
    assert events.count("<tr>") > 1, "the events layer shows the events behind the item"
    observations = html.split('data-truth-layer="observations"')[1].split('data-truth-layer="conclusion"')[0]
    assert '<ul class="records">' in observations
    if role == "trap":
        registry = json.loads(next((site / "data").rglob("sealed/registry.json")).read_text())["entries"]
        entry = next(e for e in registry if e["household_id"] == household)
        assert f"{entry['item_id']}: " in html
    else:
        assert "This household is the twin in pair 1" in html


@pytest.mark.parametrize("household", FEATURED)
def test_a_partly_planted_archetype_s_pages_say_what_this_book_leaves_out(site: Path, household: str) -> None:
    """Archetype 10 plants the missed fee breakpoint only (the owner's decision of 21 November 2026); its two
    pages say so, and no other archetype's page carries the line."""
    html = (site / "households" / f"{household}.html").read_text()
    shown = [markup.unescape(line) for line in re.findall(r'<p class="partly-planted">([^<]*)</p>', html)]
    if household in ("HH-4821", "HH-7350"):
        assert shown == [
            "This book version plants the missed fee breakpoint only. The archetype's other half, an approved IPS "
            "exception against real drift, comes in a later book version."
        ]
    else:
        assert shown == []


def test_the_index_lists_the_public_featured_households(site: Path) -> None:
    index = (site / "index.html").read_text()
    assert sorted(set(re.findall(r"households/(HH-\d{4})\.html", index))) == list(FEATURED)


def test_archetype_7_s_events_layer_shows_the_inherited_ira_s_events(site: Path) -> None:
    """Its trap is a distribution that never left the inherited IRA, so no kind of event carries it: the layer
    shows the inherited IRA's own events, among which no 2025 distribution appears."""
    if not (site / "households" / "HH-7126.html").exists():
        pytest.skip("archetype 7's featured pair is held out until the freeze moves it in")
    html = (site / "households" / "HH-7126.html").read_text()
    events = html[html.index("<h3>1. Events</h3>") : html.index("</tbody>", html.index("<h3>1. Events</h3>"))]
    rows = re.findall(r"<tr><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>", events)
    assert rows and {account for _, _, account in rows} == {"SYN-71260002"}
    assert ("2025-01-01", "opening", "SYN-71260002") in rows
    assert not [r for r in rows if r[0].startswith("2025") and r[1] in ("rmd", "withdrawal", "distribution")]
