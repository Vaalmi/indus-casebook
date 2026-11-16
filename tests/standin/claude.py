"""A stand-in for the `claude` CLI, so the checks never call a model (docs/CODE_STANDARDS.md rule 13).

It speaks the same stream-json as `claude -p --output-format stream-json --verbose`.
The runner gives the CLI a minimal environment, so the stand-in takes its settings from a
JSON file named by `--standin-config PATH`, which CASEBOOK_CLAUDE puts first on the command
line: "mode" is answer (default), error, timeout, quota, no_skill or leak; "answer" names a
file whose text becomes the final answer; "log" names a file that gets one JSON line per
call with the arguments, the working folder and the environment keys.
"""

import json
import os
import re
import sys
import time
from pathlib import Path


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def main(argv: list[str]) -> int:
    settings: dict[str, str] = {}
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
    emit(
        {"type": "system", "subtype": "init", "model": model, "cwd": str(Path.cwd()), "tools": ["Read", "Glob", "Grep"]}
    )
    if mode == "timeout":
        time.sleep(30)
        return 0
    if "--plugin-dir" in argv and mode != "no_skill":
        plugin = Path(argv[argv.index("--plugin-dir") + 1])
        skill = next((p.name for p in sorted((plugin / "skills").iterdir()) if p.is_dir()), "none")
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
