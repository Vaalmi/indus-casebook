# Status

<!-- Kept current as each ticket or phase lands (docs/PROCESS.md). The first thing a new session reads after AGENTS.md. -->

Nothing built yet. The owner approved `docs/SPEC.md` and `docs/PLAN.md` on 16 November 2026. Next: the owner says "Please implement the plan", and building starts at slice 1 on branch `build/<name>`.

## Running it

Nothing to run yet. Slice 1 of the plan creates `make setup`, `make check` and `uv run casebook build --seed 2026`, and fills this section in.

## Where things stand

| Ticket or phase | State | Evidence |
| --- | --- | --- |
| Spec | approved by the owner, 16 November 2026 | `docs/SPEC.md` (uncommitted); read-back of the earlier text in `review/spec-paraphrase.md` |
| Plan, slices 1 to 17 | approved by the owner, 16 November 2026; reviewed (both reviewers pass at round 2, and pass the 16 November amendment); not started | `docs/PLAN.md` (uncommitted); `review/plan-r1-*.md`, `review/plan-r2-*.md`, `review/plan-amend-*.md` |

## Known gaps

- **Spec, open decisions.** The first (tax calculators and form filler) is ticked in the spec with the probes' result. Finding the CPA or EA and the name check stay open there as the owner's errands (owner, 13 November 2026).
- **Spec, six lines a first-time reader took two ways** (U1 to U6 in `review/spec-paraphrase.md`). The owner settled them on 16 November 2026: U1 from the preview; U2 every row and document; U3 decide after the preview (slice 17 waits on it); U4 the household page shows a tax or RMD justified conclusion with its figures, while task-page verdicts and keys stay held; U5 only where triggered; U6 outcome counts only. The plan's "Choices and why" carries each. The spec was edited on 16 November 2026, on the owner's word, for all but U3, and for the advisor-skills line (builder drafts, owner edits). The read-back and the plan review ran on the earlier spec text; the owner approved the edited spec on 16 November 2026. The owner's spec document on claude.ai does not have these edits.
- **The `claude` CLI was signed out on this machine during planning,** so the sealed-workspace test did not run. It is the first criterion of slice 2.
- **Template placeholders** remain in `AGENTS.md`, `review.config.yaml` and `docs/CODE_STANDARDS.md`. Slice 1 fills them in.

## Review log

One line per unit of work (`docs/REVIEW_PROTOCOL.md`).

| Unit | Opened | Closed | Reviewer (session) | Rounds and verdicts | Proven blockers | Notes kept |
| --- | --- | --- | --- | --- | --- | --- |
| Plan (`docs/PLAN.md`), two reviewers because it covers release and evaluation gates | 2026-11-13 22:13 | 2026-11-13 22:22 | reviewer_a, GPT-6 Astra xhigh (`01a1d80b-c6cd-77b3-9717-b84879527a15`); reviewer_b, GPT-6.1 Sol high (`01a1d80b-c6cd-76e0-8dc5-f717c28f2d64`) | A: R1 BLOCK, R2 PASS. B: R1 BLOCK, R2 PASS | S1, from both independently: slice 7 left the bracket out of the two-calculator agreement (`docs/SPEC.md:84-85`). Confirmed by reading; fixed in slice 7 and "Choices and why". Uncommitted: the owner has not asked for a commit | None left. reviewer_a's two notes (what resume skips; the watermark after review) were acted on |
| Plan amendment: the owner's answers on U1 to U6 (U4 changes what is held; slices 14 and 16 gain criteria). One targeted check, same sessions, since the plan's two rounds were spent | 2026-11-16 05:06 | 2026-11-16 05:08 | reviewer_a, GPT-6 Astra xhigh (`01a1d80b-c6cd-77b3-9717-b84879527a15`); reviewer_b, GPT-6.1 Sol high (`01a1d80b-c6cd-76e0-8dc5-f717c28f2d64`) | A: PASS. B: PASS | None | None |

## Milestones

The dates the process is judged by. Write each once, when it happens.

- Spec approved: 2026-11-16, by the owner, with the plan. Paraphrase run 2026-11-13 by reviewer_b (GPT-6.1 Sol, high): no difference in the must-do, must-not or not-building lines; six lines it could not settle (U1 to U6). The owner settled five on 16 November 2026 and the spec was edited to say so (U1, U2, U4, U5, U6); U3 is deferred to after the preview by the owner's choice. The reader was not rerun after the edits (`docs/PROCESS.md`).
- First usable in the real environment (slice 1 merged and used by the owner): <date>
- First release to someone other than the owner: <date>
