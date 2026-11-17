"""A stand-in for the `codex` CLI as a tone juror, so the checks never call a model (docs/CODE_STANDARDS.md
rule 13).

It answers as `codex exec ... -o FILE -` does: the prompt on stdin, the reply written to FILE and printed,
and a header naming the model, effort and sandbox on stderr. CASEBOOK_JURY_CODEX puts
`--standin-config PATH` first on the command line. The JSON file there holds "mode": vote (the default)
replies {"score": <score>, "reason": <reason>}, or "reply" as written when the file gives one; error exits
1; timeout sleeps 30 seconds. "log" names a file that gets one JSON line per call with the arguments, stdin
and the working folder.
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
    effort = next(a.split("=", 1)[1].strip('"') for a in argv if a.startswith("model_reasoning_effort="))
    sandbox = argv[argv.index("-s") + 1]
    model = settings.get("reported_model", argv[argv.index("-m") + 1])
    print(f"model: {model}\nreasoning effort: {effort}\nsandbox: {sandbox}", file=sys.stderr)
    if mode == "error":
        print("ERROR: stream disconnected", file=sys.stderr)
        return 1
    reply = (
        settings["reply"]
        if "reply" in settings
        else json.dumps({"score": settings.get("score", 4), "reason": settings.get("reason", "Plain and calm.")})
    )
    Path(argv[argv.index("-o") + 1]).write_text(reply, encoding="utf-8")
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
