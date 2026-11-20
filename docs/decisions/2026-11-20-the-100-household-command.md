# Decision needed: which command counts as "one command with a seed builds the book: 100 households"

**What's stuck.** Slice 6's first criterion, unticked: "`uv run casebook build --seed 2026` builds 100 households: ten archetypes, five pairs each; the same seed and version give byte-identical files". STATUS said it would tick once the freeze moved the held-out pairs in. The docs-against-code check (`review/build-preview-docs.md`, item B2) found that it can't.

**Evidence.**
- After the freeze, `uv run casebook build --seed 2026` builds 92 households.
- The other eight are the private pairs that the private set runs on. They are drawn only with the private salt in `$CASEBOOK_PRIVATE/book/private_salt` (`cli.py:41-60`), so that the public repo cannot draw them. That is the slice 11 design, reviewed and passed.
- `CASEBOOK_PRIVATE=../indus-casebook-private uv run casebook build --held-out` builds all 100 into the private folder: 900 of 900 checks pass, and a second build is byte-identical (slice 6 and 11's evidence in STATUS).

**Options.**

1. **Count `casebook build --held-out` (with `$CASEBOOK_PRIVATE` set) as the one command for the whole book.** It is still one command with a seed. Only you can run it, since it needs the private salt. I would then rerun it, check the 100 and its byte-identity, and tick the criterion as "the whole book, from `--held-out`". The public command stays at 92.
2. **Make the public command build 100.** The private pairs would be drawn from the public seed. Consequence: anyone could rebuild the households the private set runs on, which undoes slice 11 ("Tuning to the published tasks" in the threat model).
3. **Narrow the spec line** to "the public book: 92 households; the whole book of 100 with the private salt".

**My recommendation.** Option 1. It keeps the private set's households private, and the spec's "one command with a seed" still holds for the person who holds the private set.

**If you don't decide.** The criterion stays unticked and is listed in STATUS. Nothing else waits on it.

**Decision.** <open>
