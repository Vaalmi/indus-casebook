> **UNVALIDATED SYNTHETIC RESEARCH PREVIEW.** Household data, prices, transactions and document contents are invented. Securities appear under invented names by default; an optional mode uses real ticker identifiers with invented prices. Tax calculations, answer keys and workflow judgments have not been independently reviewed by qualified practitioners. This is not tax, investment or compliance advice and is unsuitable for filing, trading or client decisions. No performance claims are established.

# The Indus Casebook plugin

The Indus Casebook's four advisor skills, and its sample book to try them on: the 20 featured households of the book, invented, with securities under invented names. A session that uses one of the skills works on the sample book only. It can't load your own files or anyone's real records.

## Install

In Claude Code:

```
/plugin marketplace add <owner>/<repo>
/plugin install indus-casebook@indus-casebook
```

The plugin needs `python3` on your PATH (macOS offers to install it the first time something asks for it). Without it, Claude Code refuses every tool call, in every session, until you install `python3` or remove the plugin: the gate fails closed. Its gate runs in Claude Code, and in Cowork on your own computer. Claude.ai chat loads the skills but not the gate, so use Claude Code.

## Use

Run a skill and name a sample household, for example `/indus-casebook:reconciliation-as-of HH-4821`. Without a household, Claude asks which one, listing the 20. The skills are:

- `reconciliation-as-of`: do the custodian files, the portfolio system, the CRM and the documents agree, as of a date?
- `tax-lot-rmd`: tax lots, realized gains and losses, wash sales and required minimum distributions.
- `meeting-follow-up`: what to raise at a client meeting, and the follow-up message. The plugin has no CRM to write the follow-up into, so the answer drafts it.
- `compliance-review`: holdings against the investment policy statement, the documents behind tax-reported figures, and facts two sources state differently.

Every answer starts with the notice above and names the sample-book files it used.

## What the gate does

The plugin's hooks fire in every session once it is installed, but they do nothing until one of its skills is used in that session. From then on, for the rest of the session, they:

- name the sample book and its households to Claude;
- refuse a prompt that names a household the sample book doesn't hold, or mentions (`@`) a file outside it;
- allow reading inside the sample book only (Read, Glob and Grep), plus the skills themselves, a to-do list and a question to you (Skill, TodoWrite, AskUserQuestion), and refuse every other tool: Bash, writes and edits, web fetches and searches, subagents and MCP tools;
- send an answer back once if it doesn't start with the notice, and show you the notice if it still doesn't.

Start a new session for other work. The gate guards against mistakes; hooks can be switched off, so it isn't a guard against you.

## Licences

Code: Apache-2.0 (`LICENSE`). Data: CC BY 4.0 (`LICENSE-DATA`).
