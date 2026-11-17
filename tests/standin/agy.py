"""A stand-in for the `agy` CLI as a tone juror, so the checks never call a model (docs/CODE_STANDARDS.md
rule 13).

It answers as `agy -p PROMPT --output-format json` does: one JSON object whose "response" is the model's
reply. CASEBOOK_JURY_AGY puts `--standin-config PATH` first on the command line. The JSON file there holds
"mode": vote (the default) replies {"score": <score>, "reason": <reason>}, or "reply" as written when the
file gives one; error exits 1; timeout sleeps 30 seconds. "log" names a file that gets one JSON line per
call with the arguments, stdin and the working folder. Like the real CLI it writes the model it resolved and its
label to the --log-file it is given; "reported_model" or "reported_label" makes it report another.
"""

import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    settings = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    argv = argv[2:]
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    if settings.get("log"):
        with Path(settings["log"]).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "stdin": stdin, "cwd": str(Path.cwd())}) + "\n")
    mode = settings.get("mode", "vote")
    if mode == "timeout":
        time.sleep(30)
        return 0
    if mode == "error":
        print("Error: quota exhausted", file=sys.stderr)
        return 1
    if "--log-file" in argv:
        model = settings.get("reported_model", argv[argv.index("--model") + 1])
        effort = argv[argv.index("--effort") + 1].capitalize()
        name = settings.get("reported_label", f"Gemini 4 Carbon ({effort})")
        log = f'I1117 Resolving model {model}\nI1117 Selected model label="{name}"\n'
        Path(argv[argv.index("--log-file") + 1]).write_text(log, encoding="utf-8")
    reply = (
        settings["reply"]
        if "reply" in settings
        else json.dumps({"score": settings.get("score", 4), "reason": settings.get("reason", "Plain and calm.")})
    )
    print(json.dumps({"response": reply, "conversation_id": "standin"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
