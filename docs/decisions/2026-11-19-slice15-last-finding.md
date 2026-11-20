# Decision needed: accept slice 15's last fix without another review round?

**What's stuck.** Slice 15's review has used its rounds: round 1, round 2 and the one targeted check `docs/REVIEW_PROTOCOL.md` allows. Reviewer B passed round 2. Reviewer A held its round-2 blocker at the targeted check, on a new trigger that the round-2 fix had introduced. The protocol sends a blocker still open after the targeted check to you, not to another round.

**How it got here.** These are steps in one line of the gate, which decides whether a prompt types one of the plugin's skills (`skill_in_prompt` in `plugin/hooks/gate.py`):

1. **Round 1 (A and B).** The line read only the prompt's first command. So a plugin skill stacked after another one (`/summarize /indus-casebook:tax-lot-rmd HH-4821 @/tmp/file`) left the session ungated. The fix looked for a skill anywhere in the prompt and added a second hold, the `UserPromptExpansion` hook.
2. **Round 2 (A).** Looking anywhere was too broad. A question that only names a skill ("What does /indus-casebook:tax-lot-rmd do?") gated the session, against your decision that the hooks act only once a skill is used. The fix read only the run of commands opening the prompt.
3. **Targeted check (A, `review/slice15-t1-a.md`).** That run allowed no space between commands. So a path such as `/summarize /Users/…/plugin/skills/tax-lot-rmd/SKILL.md` was read folder by folder as commands, and gated the session on `/tax-lot-rmd`.

**What the builder did.**

- **Confirmed it** with the reviewer's exact probe (it printed `True`).
- **Fixed it** as the reviewer asked:
  - a command is a whole word, ended by whitespace or the end of the prompt;
  - each command after the first must follow whitespace.

  So the folders of a path are never read as commands.
- **Tested it.** Three new cases pass and fail on the unfixed line: the reviewer's path, `/summarize/tax-lot-rmd` and `/tax-lot-rmd/SKILL.md`. Every earlier case still holds:
  - stacked skills still gate;
  - questions, prose, quoted examples and arguments still don't.
- **Ran the checks.** `make check` passes. No reviewer has seen this fix.

What this line can get wrong is narrow, in both directions:

- **A false gate** makes a session read the sample book only. That's an annoyance, never a leak.
- **A missed typed skill** is still caught by the expansion hook and the Skill tool's hook, which name the skill itself.

**Options.**

1. **Accept the fix as it stands.** Slice 15's review closes on this page. The whole-branch review (two reviewers, `docs/PLAN.md`) sees this line with everything else.
2. **Ask for one more targeted check of this line.** Reviewer A's session is still open, so it costs one short call.

**My recommendation.** Option 1. The defect is a missing whitespace requirement in one pattern, and the fix is what the reviewer asked for ("Require whitespace between successive command matches"). Tests pin both sides, and a mistake in this line can't let a file out of the sample book.

**If you don't decide.** The fix stays in, and slice 15's review is recorded as closed by this page, with the finding fixed but unreviewed.

**Decision.** <The owner's answer, with the date.>
