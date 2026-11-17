"""A stand-in for the `claude` CLI as a tone juror, so the checks never call a model (docs/CODE_STANDARDS.md
rule 13).

It answers as `claude -p --output-format json` does: one JSON object whose "result" is the model's reply.
CASEBOOK_JURY_CLAUDE puts `--standin-config PATH` first on the command line. The JSON file there holds
"mode": vote (the default) replies {"score": <score>, "reason": <reason>}, or "reply" as written when the
file gives one; error exits 1 with is_error true; api_error reports is_error true but exits 0; timeout
sleeps 30 seconds. "log" names a file that gets one JSON line per call with the arguments, stdin and the
working folder.
"""

import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    settings = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    argv = argv[2:]
    stdin = sys.stdin.read()
    if settings.get("log"):
        with Path(settings["log"]).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "stdin": stdin, "cwd": str(Path.cwd())}) + "\n")
    mode = settings.get("mode", "vote")
    if mode == "timeout":
        time.sleep(30)
        return 0
    model = argv[argv.index("--model") + 1]
    reply = (
        settings["reply"]
        if "reply" in settings
        else json.dumps({"score": settings.get("score", 4), "reason": settings.get("reason", "Plain and calm.")})
    )
    failed = mode in ("error", "api_error")
    if "envelope" in settings:  # the whole stdout, as written
        print(settings["envelope"])
        return 0
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": failed,
                "result": "API Error: overloaded" if failed else reply,
                "modelUsage": {settings.get("reported_model", model): {}},
            }
        )
    )
    return 1 if mode == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
