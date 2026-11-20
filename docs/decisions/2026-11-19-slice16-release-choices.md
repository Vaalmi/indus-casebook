# Decision needed: six choices the preview release leaves open

**What's stuck.** Slice 16, the preview release v0.1. Its criteria name what the release must hold and refuse. They don't say six things that decide what gets built and published. Each is below with my recommendation. Nothing in slice 16 is built yet; slice 17 depends on it. The facts come from a read of the code on 19 November 2026.

## 1. Which version the tag carries

- **The facts.** The criterion says "the owner pushes tag `v0.1.0`". The book's version is the package version, 0.0.1. Every published run, key and the audit were made on book 0.0.1. The Pages workflow refuses a tag that isn't `v` plus the package version.
- **Option (a).** Move everything to 0.1.0. The book files would be the same bytes, but the runs and the audit would name a book version the release doesn't ship, and about 13 tests and `published/keys/0.0.1` would move.
- **Option (b), recommended.** The package and the tag become 0.1.0, and the book keeps its own version, 0.0.1. Tag v0.1.0 then ships book 0.0.1, the book the runs and the audit used. A later correction bumps the book's version with an errata entry, as the stable-IDs rule says.

## 2. What "a file with no notice" means

- **The facts.** The spec's rule names "the README, any site page, the data metadata or any filled form" (Rules, "Notice everywhere"). The plan's criterion says the release fails on "a file with no notice". CSV files and the book's own JSON can't carry the notice without changing book bytes, which would change every manifest hash.
- **Recommended reading:**
  - pages, Markdown and text files carry it in their text;
  - every page of a PDF carries it;
  - a JSONL file carries it on its first line;
  - JSON the release writes or copies from `published/` gets a `notice` field;
  - CSV and the book's own JSON are covered by a `metadata.json` or `NOTICE.txt` at the root of the folder they ship in;
  - a zip has a `NOTICE.txt` at its root, and every file inside it follows the same rules.

## 3. What a case packet's answer sheet holds

- **The facts.** The spec: "one zip per featured household with its source files and a separate answer sheet. Tax answer sheets are absent until review." The code already treats a household's tax summary as its held "tax answer sheet". 18 of the 20 featured households are tax or RMD archetypes.
- **Option (a), recommended.** Each packet gets an answer sheet holding:
  - the planted item's justified conclusion with its figures (what the household page already shows, by your decision on U4), or the twin's explanation;
  - the published keys of the household's tasks that aren't held.

  The tax summaries and held keys stay out. Every packet has an answer sheet, and none of them holds tax answers.
- **Option (b).** No answer sheet in a tax or RMD household's packet at all. That leaves 18 of 20 packets without one.

## 4. What the review packet holds

The spec: "ten featured returns, every tax and RMD boundary case, the mapping from inputs to form lines, and five further household files." "Boundary case" appears nowhere in the code. I recommend:

- **Ten returns:**
  - **What:** the ten traps' returns, one per archetype.
  - **Where:** written to `out/review/`, not into the public release, since the packet must hold the tax summaries the release refuses. A test refuses the packet if it's copied in.
- **Every tax and RMD boundary case.** The list includes:
  - every planted tax or RMD item and its near-miss or unresolved twin, with its tax summary;
  - the two lines only in-house code computes (loss carryover and IRA basis, plan "Choices and why");
  - a written list of the rule readings I made in building (the ones STATUS records).
- **The mapping:**
  - the twelve forms' line-to-field maps as one table;
  - each of the ten returns read back line by line;
  - each return's tax unit's facts.
- **Five further households:** five background households of tax archetypes, drawn with the seed, outside the 15 you audited and outside the private pairs, with their tax summaries.

## 5. Your home folder in the published run records

- **The facts.** All 226 published run records name absolute paths on this Mac, for example `<home>/projects/indus-casebook/out/real/0.0.1`, for the book, the skill and the checklist they ran with. The site and the release would publish them.
- **Option (a), recommended.** Before the release, rewrite these paths in the published records relative to the repo (`out/real/0.0.1`, `skills/indus-advisor`). The runner then writes them that way from now on, and a gate refuses a published file holding a home-folder path. No grade changes. Each record's own hashes of its skill and book stay as they are.
- **Option (b).** Leave them as they are.

## 6. Where the packets are served

- **Option (a), recommended.** On the site, under `packets/`, built from the same tag, so a reader downloads them with no account.
- **Option (b).** Attached to a GitHub Release. That needs the workflow to have write access to the repo, which the Pages workflow doesn't have today.

## Also worth knowing before you tag

The featured households' CRM notes are still template notes, which you were to write (slice 5). If you tag v0.1.0 first, your notes then ship as a correction: a new book version and 20 errata entries.

**My recommendation.** Options 1(b), 2 as written, 3(a), 4 as written, 5(a) and 6(a). Say "as recommended" or name the ones you'd change.

**If you don't decide.** Slice 16 waits, and slice 17 after it. Nothing is published either way.

**Decision.** As recommended: 1(b), 2 as written, 3(a), 4 as written, 5(a) and 6(a) (the owner, 19 November 2026). The owner added, in the same answer: "we need a really good readme with good visuals, not only mermaid diagrams but more". That joins slice 16's README criterion.
