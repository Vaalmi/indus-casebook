# Decision needed: how the plugin keeps to the sample book and shows the notice

**What's stuck.** Slice 15, the plugin. The plan gives it one row: "`plugin/`: the skills, the sample book, and a gate that accepts only sample-book household IDs". The spec says: "the runner and the plugin accept only household IDs listed in the book manifest. Nothing in the product reads a file from outside the book" (Rules). It also says "An advisor in the plugin: a choice of sample household, the skill's output with the sources it used, and the notice. No way to load their own files." Code standard 10 adds: "A prompt is never the only guard." The plan doesn't say how the gate works, and the choice shapes what the advisor installs.

**Evidence.** From Claude Code's plugin documentation, read on 19 November 2026 (code.claude.com/docs/en/plugins, hooks, skills; claude.com/docs/plugins/platform-support):

- A plugin can't ship permission rules. A skill's `allowed-tools` only pre-approves tools; it restricts nothing.
- A gate in a plugin has to be code. A hook can deny Read, Glob, Grep, Write and Edit by path; it sees Bash only as free command text. Or an MCP server can read files only by household ID. Either way, the advisor's machine needs a program to run it (`python3` or `node` on the PATH).
- A plugin's hooks fire in every session and every project once the plugin is installed, not only while its skills run.
- Cowork runs hooks when it runs on the advisor's computer. Claude.ai chat loads a plugin's skills and ignores its hooks.
- The advisor can always switch hooks off. So the gate guards against mistakes, not against the advisor, which is where the threat model draws the line ("someone points the plugin or runner at real records").
- The four skills are your approved bytes, and every published skill-arm result names their hash.

**Options.**

1. **A code gate in the plugin, with the skills unchanged.** The plugin ships:
   - the four approved skills byte for byte (a test compares them with the freeze);
   - the sample book: the 20 featured households' four source sets and the manifest, with no sealed file;
   - one small Python program using only the standard library, run by `python3` from the PATH.

   That program's hooks act only in a session where one of the plugin's skills has been invoked. In that session they:
   - name the sample book and its households;
   - refuse any file read, search or write outside the sample book, and any Bash or web call;
   - send the answer back if it doesn't start with the notice.

   Consequence: it's enforced in code, scoped to sessions that use the plugin, and the measured skills stay as they are. The advisor needs `python3` (macOS offers to install it on first use). The supported hosts are Claude Code, and Cowork on the advisor's computer. In claude.ai chat the skills would load with no gate, so the README names Claude Code.
2. **The skills carry it, with no code.** Edit the four skills to name the sample book, read only its files and print the notice. Consequence: it works in every Claude host and needs nothing installed. But the gate is a prompt only, against the spec rule and code standard 10. The skills also need your re-approval, and the plugin would ship skills that differ from the ones the results measured.
3. **Change the spec rule.** For example: "the plugin ships only the sample book and offers no tool to load other files", with no gate on what Claude itself reads. Consequence: it's the simplest build, but it drops a rule the spec states. The slice's third criterion ("a test passes a path outside the book") would also change.

**My recommendation.** Option 1. It meets the spec rule in code and keeps the plugin's skills identical to the ones the results measured. Its cost, `python3` and Claude Code as the host, falls on the people the spec names: advisors trying the plugin.

**If you don't decide.** Slice 15 waits, and so do slices 16 and 17, which depend on it. Nothing else in the plan is open to build. The owner items already in STATUS are unaffected.

**Decision.** <The owner's answer, with the date.>
