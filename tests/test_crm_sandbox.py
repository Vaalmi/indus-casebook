"""The CRM sandbox (docs/PLAN.md, slice 10): its tools through a real MCP client over stdio, the
diff of its final state, the account-number check on external messages, and the stand-in's
follow_up mode."""

import json
import os
import random
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

from casebook.crm import sandbox
from casebook.crm.diff import crm_diff
from casebook.crm.server import build_server, main
from casebook.graders.follow_up import FollowUp, external_messages
from casebook.model.crm import CrmDiffError, parse_crm_diff
from casebook.model.files import CRM_JSON, household_dir
from casebook.model.identifiers import account_numbers
from casebook.runner.config import ENVIRONMENT_KEYS

from .conftest import STANDIN

TOOLS = {"list_households", "read_household", "add_note", "add_activity", "mark_activity_done"}


def invented_crm(household_id: str, primary: str, spouse: str) -> dict[str, Any]:
    """A household's CRM in the shape the book emits, cut down to one record of each kind."""
    digits = household_id.removeprefix("HH-")
    return {
        "household_id": household_id,
        "contacts": [
            {"person_id": f"P-{digits}-2", "name": spouse, "relationship": "spouse", "known_as_of": "2026-04-15"},
            {"person_id": f"P-{digits}-1", "name": primary, "relationship": "primary", "known_as_of": "2026-04-15"},
        ],
        "notes": [{"note_id": f"N-{digits}-01", "date": "2025-03-03", "text": "Annual review held."}],
        "activities": [
            {"activity_id": f"CA-{digits}-01", "date": "2026-03-02", "kind": "call", "summary": "Asked about RMDs."}
        ],
        "agreements": [{"agreement_id": f"AGR-{digits}-1", "account_ids": [f"SYN-{digits}0001"], "kind": "advisory"}],
    }


HOUSEHOLDS = {
    "HH-1204": invented_crm("HH-1204", "Ada Quill", "Bram Quill"),
    "HH-7350": invented_crm("HH-7350", "Cora Vance", "Dov Vance"),
}


def new_state(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    path = tmp_path / "crm-state.json"
    return path, sandbox.write_state(path, HOUSEHOLDS)


def server(state: Path) -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "casebook.crm.server", "--state", str(state)])


def call(state: Path, *calls: tuple[str, dict[str, Any]]) -> list[CallToolResult]:
    """Each call in turn, in one session with the server started as its own process."""

    async def session() -> list[CallToolResult]:
        async with stdio_client(server(state)) as (read, write), ClientSession(read, write) as crm:
            await crm.initialize()
            return [await crm.call_tool(name, arguments) for name, arguments in calls]

    return anyio.run(session)


def call_in_process(state: Path, *calls: tuple[str, dict[str, Any]]) -> list[CallToolResult]:
    """The same calls through the SDK's in-process client, so the server's own code is measured."""

    async def session() -> list[CallToolResult]:
        async with Client(build_server(state)) as crm:
            return [await crm.call_tool(name, arguments) for name, arguments in calls]

    return anyio.run(session)


BOTH_WAYS = pytest.mark.parametrize("calls", [call, call_in_process], ids=["stdio", "in_process"])
Calls = Callable[..., list[CallToolResult]]


def text(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


def test_the_crm_offers_the_tools_of_an_advisors_crm_and_nothing_else(tmp_path: Path) -> None:
    state, _ = new_state(tmp_path)

    async def session() -> dict[str, bool | None]:
        async with stdio_client(server(state)) as (read, write), ClientSession(read, write) as crm:
            await crm.initialize()
            listed = (await crm.list_tools()).tools
            return {t.name: t.annotations.read_only_hint if t.annotations else None for t in listed}

    assert anyio.run(session) == {
        "list_households": True,
        "read_household": True,
        "add_note": False,
        "add_activity": False,
        "mark_activity_done": False,
    }


def test_the_server_lists_every_household_and_reads_one(tmp_path: Path) -> None:
    state, _ = new_state(tmp_path)
    listed, read = call(state, ("list_households", {}), ("read_household", {"household_id": "HH-7350"}))
    # The name is the primary contact's, though the spouse is listed first.
    assert listed.structured_content == {
        "result": [{"household_id": "HH-1204", "name": "Ada Quill"}, {"household_id": "HH-7350", "name": "Cora Vance"}]
    }
    assert read.structured_content == HOUSEHOLDS["HH-7350"]


@BOTH_WAYS
def test_each_write_gets_a_sandbox_id_and_is_recorded_in_the_state(tmp_path: Path, calls: Calls) -> None:
    state, _ = new_state(tmp_path)
    results = calls(
        state,
        ("add_note", {"household_id": "HH-1204", "date": "2026-04-15", "text": "  Reviewed the RMD plan.  "}),
        (
            "add_activity",
            {
                "household_id": "HH-1204",
                "date": "2026-04-15",
                "kind": "message",
                "summary": "Your RMD is scheduled for December.",
                "sent_to_client": True,
            },
        ),
        ("mark_activity_done", {"household_id": "HH-1204", "activity_id": "CA-1204-01", "date": "2026-04-16"}),
        ("add_note", {"household_id": "HH-7350", "date": "2026-04-15", "text": "Wrong household."}),
        ("mark_activity_done", {"household_id": "HH-1204", "activity_id": "CA-1204-01", "date": "2026-04-17"}),
    )
    assert [r.is_error for r in results] == [False, False, False, False, True]
    assert results[0].structured_content == {
        "note_id": "SB-1204-01",
        "date": "2026-04-15",
        "text": "Reviewed the RMD plan.",
    }
    assert results[1].structured_content == {
        "activity_id": "SB-1204-02",
        "date": "2026-04-15",
        "kind": "message",
        "summary": "Your RMD is scheduled for December.",
        "sent_to_client": True,
    }
    assert results[3].structured_content == {"note_id": "SB-7350-01", "date": "2026-04-15", "text": "Wrong household."}
    assert "already marked done on 2026-04-16" in text(results[4])

    final = sandbox.read_state(state)
    quill = final["households"]["HH-1204"]
    assert quill["notes"][-1]["note_id"] == "SB-1204-01"
    assert [a["activity_id"] for a in quill["activities"]] == ["CA-1204-01", "SB-1204-02"]
    assert quill["activities"][0]["done"] == "2026-04-16"
    assert [(w["write_id"], w["tool"], w["household_id"]) for w in final["writes"]] == [
        ("SB-1204-01", "add_note", "HH-1204"),
        ("SB-1204-02", "add_activity", "HH-1204"),
        ("SB-1204-03", "mark_activity_done", "HH-1204"),
        ("SB-7350-01", "add_note", "HH-7350"),
    ]
    assert final["writes"][2]["written"] == {"activity_id": "CA-1204-01", "done": "2026-04-16"}


@BOTH_WAYS
def test_a_bad_request_is_a_tool_error_that_changes_nothing(tmp_path: Path, calls: Calls) -> None:
    state, _ = new_state(tmp_path)
    before = state.read_bytes()
    note = {"household_id": "HH-1204", "date": "2026-04-15", "text": "A note."}
    activity = {**note, "kind": "call", "summary": "Called.", "sent_to_client": False}
    del activity["text"]
    bad: list[tuple[str, dict[str, Any], str]] = [
        ("add_note", {**note, "household_id": "HH-9999"}, "No household 'HH-9999' in the CRM"),
        ("read_household", {"household_id": "1204"}, "No household '1204' in the CRM"),
        ("add_note", {**note, "date": "15/04/2026"}, "Date '15/04/2026' is not a calendar date"),
        ("add_note", {**note, "date": "2026-02-30"}, "Date '2026-02-30' is not a calendar date"),
        ("add_note", {**note, "date": "20260415"}, "Date '20260415' is not a calendar date"),
        ("add_note", {**note, "text": "   "}, "The note text is empty"),
        ("add_activity", {**activity, "kind": ""}, "The activity kind is empty"),
        ("add_activity", {**activity, "summary": "\n"}, "The activity summary is empty"),
        ("add_activity", {k: v for k, v in activity.items() if k != "sent_to_client"}, "sent_to_client"),
        (
            "mark_activity_done",
            {"household_id": "HH-1204", "activity_id": "CA-7350-01", "date": "2026-04-15"},
            "Household HH-1204 has no activity 'CA-7350-01'",
        ),
    ]
    results = calls(state, *((tool, arguments) for tool, arguments, _ in bad), ("list_households", {}))
    for (tool, _, message), result in zip(bad, results, strict=False):
        assert result.is_error, tool
        assert message in text(result), (tool, text(result))
    assert not results[-1].is_error, "the server still answers after the errors"
    assert state.read_bytes() == before


def test_the_server_refuses_to_start_without_its_state_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["--state", str(tmp_path / "absent.json")])
    assert exited.value.code == 2
    assert "no state file at" in capsys.readouterr().err


def test_the_sandbox_holds_the_crm_as_the_book_emits_it(book: Path, tmp_path: Path) -> None:
    emitted = {hh: json.loads((book / household_dir(hh) / CRM_JSON).read_text()) for hh in ("HH-1204", "HH-7350")}
    state = sandbox.write_state(tmp_path / "crm-state.json", emitted)
    # The primary contacts in book/scripted/HH-1204 and HH-7350.
    assert sandbox.list_households(state) == [
        {"household_id": "HH-1204", "name": "Funmilayo Adebayo-Kovac"},
        {"household_id": "HH-7350", "name": "Maeve Brennan-Sato"},
    ]
    assert sandbox.read_household(state, "HH-1204") == emitted["HH-1204"]


def test_a_write_to_another_household_shows_outside_its_own(tmp_path: Path) -> None:
    state, initial = new_state(tmp_path)
    call(
        state,
        ("add_note", {"household_id": "HH-1204", "date": "2026-04-15", "text": "Follow-up booked."}),
        ("add_note", {"household_id": "HH-7350", "date": "2026-04-15", "text": "Follow-up booked."}),
    )
    diff = crm_diff(initial, sandbox.read_state(state))
    outside = diff.outside("HH-1204")
    assert [(c.household_id, c.change, c.collection, c.record_id) for c in outside] == [
        ("HH-7350", "added", "notes", "SB-7350-01")
    ]
    assert [c.household_id for c in diff.outside("HH-7350")] == ["HH-1204"]
    own_only = sandbox.read_state(state)
    own_only["households"]["HH-7350"] = initial["households"]["HH-7350"]
    assert crm_diff(initial, own_only).outside("HH-1204") == ()


def test_an_external_message_with_an_account_number_is_found_and_a_masked_one_is_not(tmp_path: Path) -> None:
    state, initial = new_state(tmp_path)
    day = {"household_id": "HH-1204", "date": "2026-04-15"}
    call(
        state,
        (
            "add_activity",
            {**day, "kind": "email", "summary": "Your RMD from SYN-12040001 is set.", "sent_to_client": True},
        ),
        (
            "add_activity",
            {**day, "kind": "email", "summary": "Your account ending 0001 is set.", "sent_to_client": True},
        ),
        (
            "add_activity",
            {**day, "kind": "task", "summary": "Check SYN-12040002 before Friday.", "sent_to_client": False},
        ),
        ("add_note", {**day, "text": "Discussed SYN-12040001."}),
    )
    diff = crm_diff(initial, sandbox.read_state(state))
    messages = external_messages("no answer block", FollowUp("HH-1204", diff, None))
    assert [where for where, _ in messages] == ["CRM record SB-1204-01", "CRM record SB-1204-02"]
    assert [account_numbers(text) for _, text in messages] == [["SYN-12040001"], []]


def test_account_numbers_are_whole_syn_numbers_only() -> None:
    assert account_numbers("Moved $500 from SYN-12040001 to (SYN-12040002), then back to SYN-12040001.") == [
        "SYN-12040001",
        "SYN-12040002",
    ]
    assert account_numbers("account ending 0001; acct ****0001; SYN-****0001") == []
    assert account_numbers("SYN-1204000 is seven digits; SYN-120400011 is nine; XSYN-12040001 is not one") == []


def changed_state(initial: dict[str, Any]) -> dict[str, Any]:
    """Every kind of change, in both households: added notes (eleven, so the IDs run past 9),
    an activity marked done, a contact renamed, and an agreement removed."""
    final = json.loads(json.dumps(initial))
    for number in range(1, 12):
        sandbox.add_note(final, "HH-1204", "2026-04-15", f"Note {number}.")
    sandbox.mark_activity_done(final, "HH-7350", "CA-7350-01", "2026-04-15")
    final["households"]["HH-7350"]["contacts"][0]["name"] = "Dov Vance-Ortiz"
    final["households"]["HH-1204"]["agreements"] = []
    return final


def test_the_diff_is_stable(tmp_path: Path) -> None:
    _, initial = new_state(tmp_path)
    final = changed_state(initial)
    diff = crm_diff(initial, final)
    expected_order = [("HH-1204", "added", "notes", f"SB-1204-{n:02d}") for n in range(1, 12)] + [
        ("HH-1204", "removed", "agreements", "AGR-1204-1"),
        ("HH-7350", "changed", "contacts", "P-7350-2"),
        ("HH-7350", "changed", "activities", "CA-7350-01"),
    ]
    assert [(c.household_id, c.change, c.collection, c.record_id) for c in diff.changes] == expected_order
    as_dict = diff.to_dict()
    assert as_dict["households"]["HH-7350"]["changed"][1] == {
        "collection": "activities",
        "record_id": "CA-7350-01",
        "before": {"activity_id": "CA-7350-01", "date": "2026-03-02", "kind": "call", "summary": "Asked about RMDs."},
        "after": {
            "activity_id": "CA-7350-01",
            "date": "2026-03-02",
            "kind": "call",
            "summary": "Asked about RMDs.",
            "done": "2026-04-15",
        },
    }
    assert as_dict["households"]["HH-1204"]["changed"] == []

    # The same states with every list shuffled and the households in the other order give the same diff.
    shuffler = random.Random(7)
    for state in (initial, final):
        for crm in state["households"].values():
            for collection in sandbox.COLLECTIONS:
                shuffler.shuffle(crm[collection])
        state["households"] = dict(reversed(state["households"].items()))
    again = crm_diff(initial, final)
    assert json.dumps(again.to_dict()) == json.dumps(as_dict)
    assert crm_diff(initial, initial).changes == ()

    # The diff keeps its own copy: a later change to the state leaves it as it was.
    final["households"]["HH-7350"]["contacts"].clear()
    assert json.dumps(diff.to_dict()) == json.dumps(as_dict)


def run_standin(tmp_path: Path, settings: dict[str, Any], *args: str) -> list[dict[str, Any]]:
    """The stand-in CLI run as the runner runs it: its settings first, the minimal environment."""
    config = tmp_path / "standin.json"
    config.write_text(json.dumps(settings))
    env = {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}
    done = subprocess.run(
        [sys.executable, str(STANDIN), "--standin-config", str(config), "-p", "Prepare and follow up.", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines()]


def test_the_stand_ins_follow_up_mode_writes_through_the_crm_server(tmp_path: Path) -> None:
    state, initial = new_state(tmp_path)
    mcp_config = tmp_path / "mcp.json"
    crm = {"type": "stdio", "command": sys.executable, "args": ["-m", "casebook.crm.server", "--state", str(state)]}
    mcp_config.write_text(json.dumps({"mcpServers": {"crm": crm}}))
    answer = tmp_path / "answer.md"
    answer.write_text('Done.\n```json\n{"finding": "follow_up_recorded"}\n```\n')
    writes = [
        {"tool": "add_note", "arguments": {"household_id": "HH-1204", "date": "2026-04-15", "text": "Met; RMD set."}},
        {"tool": "add_note", "arguments": {"household_id": "HH-1204", "date": "someday", "text": "Bad date."}},
    ]
    events = run_standin(
        tmp_path, {"mode": "follow_up", "answer": str(answer), "crm_writes": writes}, "--mcp-config", str(mcp_config)
    )

    init = events[0]
    assert init["mcp_servers"] == [{"name": "crm", "status": "connected"}]
    assert {f"mcp__crm__{tool}" for tool in TOOLS} <= set(init["tools"])
    uses = [b for e in events if e["type"] == "assistant" for b in e["message"]["content"]]
    results = [b for e in events if e["type"] == "user" for b in e["message"]["content"]]
    assert [u["name"] for u in uses] == ["mcp__crm__add_note", "mcp__crm__add_note"]
    assert [r["is_error"] for r in results] == [False, True]
    assert events[-1]["result"] == answer.read_text()

    diff = crm_diff(initial, sandbox.read_state(state))
    assert [(c.household_id, c.change, c.record_id) for c in diff.changes] == [("HH-1204", "added", "SB-1204-01")]


def test_the_stand_in_loads_the_skill_its_settings_name(tmp_path: Path) -> None:
    plugin = tmp_path / "indus-advisor"
    for skill in ("compliance-review", "reconciliation-as-of"):
        (plugin / "skills" / skill).mkdir(parents=True)

    def loaded(settings: dict[str, Any]) -> list[str]:
        events = run_standin(tmp_path, settings, "--plugin-dir", str(plugin))
        return [b["input"]["skill"] for e in events if e["type"] == "assistant" for b in e["message"]["content"]]

    assert loaded({"skill": "reconciliation-as-of"}) == ["indus-advisor:reconciliation-as-of"]
    assert loaded({}) == ["indus-advisor:compliance-review"]
    # The checklist arm's plugin lacks the named skill, so the one settings file still serves it.
    assert loaded({"skill": "tax-lot-rmd"}) == ["indus-advisor:compliance-review"]


def test_a_household_gone_from_the_final_state_shows_every_record_removed(tmp_path: Path) -> None:
    _, initial = new_state(tmp_path)
    final = json.loads(json.dumps(initial))
    del final["households"]["HH-7350"]
    diff = crm_diff(initial, final)
    assert [(c.household_id, c.change, c.record_id) for c in diff.changes] == [
        ("HH-7350", "removed", "P-7350-1"),
        ("HH-7350", "removed", "P-7350-2"),
        ("HH-7350", "removed", "N-7350-01"),
        ("HH-7350", "removed", "CA-7350-01"),
        ("HH-7350", "removed", "AGR-7350-1"),
    ]
    assert [c.household_id for c in diff.outside("HH-1204")] == ["HH-7350"] * 5


def test_writes_made_at_once_are_all_kept(tmp_path: Path) -> None:
    state, _ = new_state(tmp_path)

    async def session() -> None:
        async with Client(build_server(state)) as crm, anyio.create_task_group() as calls:
            for number in range(1, 21):
                note = {"household_id": "HH-1204", "date": "2026-04-15", "text": f"Note {number}."}
                calls.start_soon(crm.call_tool, "add_note", note)

    anyio.run(session)
    final = sandbox.read_state(state)
    assert len(final["writes"]) == 20
    assert sorted(n["text"] for n in final["households"]["HH-1204"]["notes"][1:]) == sorted(
        f"Note {n}." for n in range(1, 21)
    )


def test_the_diff_reads_back_from_the_run_record_as_it_was(tmp_path: Path) -> None:
    """The runner stores `to_dict()`; the grader reads it back with `parse_crm_diff`."""
    state, initial = new_state(tmp_path)
    day = {"household_id": "HH-1204", "date": "2026-04-15"}
    call(
        state,
        ("add_note", {**day, "text": "Discussed the conversion."}),
        ("add_note", {**day | {"household_id": "HH-7350"}, "text": "Wrong file."}),
    )
    diff = crm_diff(initial, sandbox.read_state(state))
    stored = json.loads(json.dumps(diff.to_dict()))
    assert parse_crm_diff(stored) == diff
    with pytest.raises(CrmDiffError):
        parse_crm_diff({"households": {"HH-1204": {"added": [{"collection": "emails", "record_id": "x"}]}}})
    with pytest.raises(CrmDiffError):
        parse_crm_diff({"changes": []})
