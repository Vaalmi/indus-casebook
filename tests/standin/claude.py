"""A stand-in for the `claude` CLI, so the checks never call a model (docs/CODE_STANDARDS.md rule 13).

It speaks the same stream-json as `claude -p --output-format stream-json --verbose`.
The runner gives the CLI a minimal environment, so the stand-in takes its settings from a
JSON file named by `--standin-config PATH`, which CASEBOOK_CLAUDE puts first on the command
line: "mode" is answer (default), error, timeout, quota, no_skill, leak or follow_up; "answer"
names a file whose text becomes the final answer; "log" names a file that gets one JSON line
per call with the arguments, the working folder and the environment keys; "skill" names the
skill to load from `--plugin-dir` when the plugin holds it (otherwise the plugin's first,
alphabetically). In follow_up mode it starts the `crm` server that `--mcp-config` names, over
stdio with the MCP client, makes the calls "crm_writes" lists (`[{"tool": ..., "arguments":
{...}}]`), then answers as answer mode.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

CRM_SERVER = "crm"


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def crm_calls(argv: list[str], writes: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, object]]]:
    """Start the crm server that --mcp-config names, make each write, and return the server's tools
    (as the CLI names them) and the stream-json events of the calls."""
    # Imported here so the other modes start without loading the MCP SDK.
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import TextContent

    given = argv[argv.index("--mcp-config") + 1]
    config = json.loads(given if given.lstrip().startswith("{") else Path(given).read_text(encoding="utf-8"))
    server = config["mcpServers"][CRM_SERVER]
    params = StdioServerParameters(command=server["command"], args=server.get("args", []), env=server.get("env"))
    prefix = f"mcp__{CRM_SERVER}__"
    tools: list[str] = []
    events: list[dict[str, object]] = []

    async def session() -> None:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as crm:
            await crm.initialize()
            tools.extend(prefix + tool.name for tool in (await crm.list_tools()).tools)
            for number, call in enumerate(writes, start=1):
                use_id = f"crm{number}"
                result = await crm.call_tool(call["tool"], call["arguments"])
                text = "".join(block.text for block in result.content if isinstance(block, TextContent))
                use = {"type": "tool_use", "id": use_id, "name": prefix + call["tool"], "input": call["arguments"]}
                done = {"type": "tool_result", "tool_use_id": use_id, "content": text, "is_error": result.is_error}
                events.append({"type": "assistant", "message": {"content": [use]}})
                events.append({"type": "user", "message": {"content": [done]}})

    anyio.run(session)
    return tools, events


def main(argv: list[str]) -> int:
    settings: dict[str, Any] = {}
    if argv[:1] == ["--standin-config"]:
        settings = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        argv = argv[2:]
    if argv == ["--version"]:
        print("0.0.0 (stand-in)")
        return 0
    mode = settings.get("mode", "answer")
    log = settings.get("log")
    if log:
        with Path(log).open("a", encoding="utf-8") as handle:
            entry = {"argv": argv, "cwd": str(Path.cwd()), "env": sorted(os.environ)}
            handle.write(json.dumps(entry) + "\n")
    model = argv[argv.index("--model") + 1] if "--model" in argv else "unknown"
    tools = ["Read", "Glob", "Grep"]
    crm_events: list[dict[str, object]] = []
    init: dict[str, object] = {"type": "system", "subtype": "init", "model": model, "cwd": str(Path.cwd())}
    if mode == "follow_up":
        crm_tools, crm_events = crm_calls(argv, settings.get("crm_writes", []))
        tools += crm_tools
        init["mcp_servers"] = [{"name": CRM_SERVER, "status": "connected"}]
    emit({**init, "tools": tools})
    if mode == "timeout":
        time.sleep(30)
        return 0
    if "--plugin-dir" in argv and mode != "no_skill":
        plugin = Path(argv[argv.index("--plugin-dir") + 1])
        held = sorted(p.name for p in (plugin / "skills").iterdir() if p.is_dir())
        # One settings file serves every arm, so a named skill the plugin lacks (the checklist's) falls back too.
        skill = settings.get("skill") if settings.get("skill") in held else next(iter(held), "none")
        name = f"{plugin.name}:{skill}"
        emit(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": name}}]},
            }
        )
        emit(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "loaded"}]},
            }
        )
    for event in crm_events:
        emit(event)
    if mode == "leak":
        prompt = argv[argv.index("-p") + 1]
        path = re.search(r"absolute path (\S+) and", prompt)
        text = Path(path.group(1)).read_text() if path else ""
        emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": text}]}})
    usage = {"input_tokens": 120, "output_tokens": 45, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    if mode == "error":
        emit(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "API Error: overloaded",
                "usage": usage,
            }
        )
        return 1
    if mode == "quota":
        emit(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "Claude AI usage limit reached|1794830400",
                "usage": usage,
            }
        )
        return 1
    answer_file = settings.get("answer")
    answer = Path(answer_file).read_text(encoding="utf-8") if answer_file else "No answer."
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": answer,
            "usage": usage,
            "modelUsage": {model: {}},
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
