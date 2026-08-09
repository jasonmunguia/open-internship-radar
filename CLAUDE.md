# internship-radar — operating doctrine

Read before changing anything here. These are decisions with reasons, not preferences.

## What this system is
A deterministic pipeline that finds early-career roles and emails three things: a
pre-network heads-up, a daily apply queue, and instant alerts. A model is used at four
specific joints (see `TOOLS.md`) and nowhere else.

## Non-negotiables

**Scoring is blind to the operator's history.** It grades role family and company caliber
only. The operator maintains one resume per family and chooses the angle themselves. Do not
add fit inference, do not wire in their experience, do not rank companies by "fit". This was
violated repeatedly during the 2026-08-08 build and corrected each time.

**No prestige bypass.** If a title does not match one of the 7 families or a genuine variant
of one, it does not ship — a T1 logo does not buy a role onto the apply list.

**Nothing expires on age.** The apply list is a queue worked to zero. Rows leave only when
tapped. The day counter is the pressure; silent expiry loses applications.

**Defer, don't degrade.** If the re-rank cannot run, do not send. A 10/10 email at 9am beats
a 7/10 at 7:20. Backstop at 18:00 — no email is worse than a late one.

**A 404 is safe; a wrong 200 is not.** Any external lookup that can silently return the wrong
entity needs a validation gate. Errors are recoverable; plausible wrong data is not.

**Dedup on normalised keys, never display strings.**

**Never originate mail from a work domain.**

## Before claiming a change works
Run it. Every phase of the 2026-08-08 build surfaced a defect that unit-level reasoning
missed: a redirect that defeated a name gate, a rolling window mistaken for a history, a
funding threshold that ranked capital intensity as prestige, a workflow on the wrong branch,
and two checkouts where only one was deployed. State the command and its exit code.

## Two checkouts
`~/.internship-radar` is production (launchd runs it). A dev clone is separate. Merging to
main deploys nothing until production pulls. `radar/digest.py` self-heals this on each run,
but do not rely on it when verifying a change.
