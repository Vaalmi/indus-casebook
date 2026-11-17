# Decision needed: what slice 10's follow-up, external message, tone and compliance context mean

**What's stuck.** Slice 10 grades "follow-up tasks" on the CRM sandbox's final state, scores "tone" with a three-family jury, makes "an account number in an external message" a critical fail, and has each compliance task state "firm capacity, audience, channel and firm policy". The spec and the plan name these without defining them, and the draft task matrix (not yet approved) has no task that writes to the CRM. Each answer shapes the sandbox's tools, the graders and the jury, so I have stopped before building them.

**1. Which tasks are follow-up tasks?**
- **Recommended:** the four meeting trap-and-twin tasks (T-MTG-01 to 04) become "prepare and follow up": answer the client's question, then record the follow-up in the CRM sandbox (a meeting note and any open item) and draft the client's message. The two book-level meeting tasks stay read-only.
- Alternative: only T-MTG-01 and 02 write to the CRM; 03 and 04 stay read-only.

**2. What is an "external message"?**
- **Recommended:** anything drafted to leave the firm: the answer's `client_message` field, and any CRM record the answer marks as sent to the client. An account number (`SYN-` and eight digits) anywhere in it is a critical fail; a masked reference ("the account ending 0001") is not.

**3. What is "tone", and how does it count?**
- **Recommended:** tone is the client message's fitness for an independent advisor writing to a client: plain and accurate to the facts, no promise of returns, no advice beyond the firm's capacity, no alarm or blame, right for the reader. Each juror scores it 1 to 5 against that short rubric, with a one-line reason; all three votes are stored; the tone score is their median; a missing vote fails the grade. Tone is worth 15 of the meeting graders' 100 points and is not essential (a correct answer with a stiff message can still pass).
- The jurors are the roster's three families as you set them: Claude Opus 5.5 at high, GPT-6.1 Sol at xhigh, Gemini 4 Carbon at high.

**4. The compliance context.**
- **Recommended**, stated in every compliance task: firm capacity, "an SEC-registered investment adviser acting as a fiduciary; not a broker-dealer, law firm or CPA firm"; audience, "the firm's chief compliance officer"; channel, "an internal compliance memo"; firm policy, a short policy text per task (for example, "a holding above the IPS concentration limit needs a documented, client-signed exception"). The expected output has `issues_for_reviewer` and no legal-conclusion field; a schema test rejects one (`legal_conclusion`, `violation`, `ruling` and the like).

**5. The live runs.**
- **Recommended:** one follow-up task (T-MTG-01) under the three arms: three runs on `claude`, each graded by the jury, so three votes a run and nine jury calls in all (three on each of `claude`, `codex` and `agy`). The criterion asks for "one live jury vote from each family"; grading all three runs takes three from each.

**My recommendation.** Accept 1 to 5 as written. Each is the narrowest reading that makes the criterion testable, and 3 keeps tone from deciding pass or fail on its own.

**If you don't decide.** Slice 10 waits. Nothing else does: slices 11 onward don't depend on these answers, but the plan builds them after 10.

**Decision.** Accepted, all five as recommended (the owner, 16 November 2026).
