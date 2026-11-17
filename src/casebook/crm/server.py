"""The CRM sandbox as an MCP server over stdio: `python -m casebook.crm.server --state <file>`.

Its tools read and write the state file and nothing else: none runs code, reads another file or
reaches the web. Each call reads the file afresh and a write replaces it whole, so the file is
always the CRM's current state.
"""

import argparse
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from casebook.crm import sandbox

SERVER_NAME = "crm"
INSTRUCTIONS = (
    "The firm's CRM. It holds every client household's contacts, notes, activities and agreements. "
    "Dates are written YYYY-MM-DD."
)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
HouseholdId = Annotated[str, Field(description="The household's ID, such as HH-1204, as list_households gives it.")]
Day = Annotated[str, Field(description="A date, written YYYY-MM-DD.")]


def build_server(state: Path) -> MCPServer:
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, log_level="WARNING")

    # The SDK runs each tool in a worker thread and a client may call several at once, so one
    # call at a time reads and replaces the file: two writes never lose one another.
    one_at_a_time = threading.Lock()

    def read[T](action: Callable[[dict[str, Any]], T]) -> T:
        with one_at_a_time:
            try:
                return action(sandbox.read_state(state))
            except sandbox.CrmError as error:
                raise ToolError(str(error)) from None

    def write(action: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        with one_at_a_time:
            current = sandbox.read_state(state)
            try:
                written = action(current)
            except sandbox.CrmError as error:
                raise ToolError(str(error)) from None
            sandbox.save_state(state, current)
            return written

    @server.tool(annotations=READ_ONLY)
    def list_households() -> list[dict[str, str]]:
        """List every client household in the CRM: its household ID and name."""
        return read(sandbox.list_households)

    @server.tool(annotations=READ_ONLY)
    def read_household(household_id: HouseholdId) -> dict[str, Any]:
        """Read one household's records: contacts, notes, activities and agreements."""
        return read(lambda s: sandbox.read_household(s, household_id))

    @server.tool(annotations=WRITE)
    def add_note(household_id: HouseholdId, date: Day, text: str) -> dict[str, Any]:
        """Add a note to a household's record. Returns the note with its new note ID."""
        return write(lambda s: sandbox.add_note(s, household_id, date, text))

    @server.tool(annotations=WRITE)
    def add_activity(
        household_id: HouseholdId,
        date: Day,
        kind: Annotated[str, Field(description="What kind of activity: call, meeting, task, message, and so on.")],
        summary: str,
        sent_to_client: Annotated[bool, Field(description="True when the activity is a message sent to the client.")],
    ) -> dict[str, Any]:
        """Log an activity for a household, such as a call, a meeting, a task or a message.

        Set sent_to_client to true when the activity is a message sent to the client, with the
        message's text as the summary. Returns the activity with its new activity ID.
        """
        return write(lambda s: sandbox.add_activity(s, household_id, date, kind, summary, sent_to_client))

    @server.tool(annotations=WRITE)
    def mark_activity_done(household_id: HouseholdId, activity_id: str, date: Day) -> dict[str, Any]:
        """Mark one of a household's activities done on a date. Returns the activity."""
        return write(lambda s: sandbox.mark_activity_done(s, household_id, activity_id, date))

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m casebook.crm.server", description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="the sandbox's state file, which the runner writes")
    state: Path = parser.parse_args(argv).state
    if not state.is_file():
        parser.error(f"no state file at {state}")
    build_server(state).run("stdio")


if __name__ == "__main__":
    main()
