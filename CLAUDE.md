# internship-radar — operating doctrine for agents

Read this before changing anything. These are decisions with reasons, not preferences.
Read `AGENT_ONBOARDING.md` instead if your job is setting this up for a person.

## What this system is
A deterministic pipeline that finds early-career roles and emails three things: a
pre-network heads-up, a daily apply queue, and instant alerts. A model is used at exactly
FIVE joints and nowhere else — `radar/joints.py` is the registry, the only door to the
CLI, and the answer to "where does this system use judgment?". `tests/test_joints.py`
fails the moment a model call appears outside it. (The registry earned its keep the day it
was written: building it surfaced a fifth joint, `source_heal`, that every prose inventory
had missed.)

## The operating loop — how to verify anything here
Run it, then check the output against something you INDEPENDENTLY know to be true — a
company whose size you know, a count that should not have gone down, a file that should
have changed and did not. Every bug found on 2026-08-09 passed review and unit tests;
every one was caught by comparing output to reality. Corollaries:
- Paste the command and its exit code. Never claim "verified" without one.
- Test the REAL path. The defer guard was once "verified" by monkeypatching the check —
  the real check (`shutil.which`) had never fired. Break the real dependency instead.
- A zero/empty result gets a POSITIVE CONTROL before you report "none found". The missing
  `SSL_CERT_FILE` produced a confident, wrong "none of these have job boards".
- LLM joints CANNOT be smoke-tested from inside a Claude Code session — a nested
  `claude -p` is intercepted and returns prose. Test through launchd:
  clear `last_digest` from `data/digest_heartbeat.json`, `: > /tmp/internship-digest.log`,
  `launchctl kickstart -k gui/$(id -u)/com.internship-digest`, then read the log.
  This sends real email; that is the point.

## Model selection — a rule with its incident
Match the model to the job. Scoring rows against a fixed profile is a small-model task;
invoking a frontier model made it slower than its own 120s timeout, so every batch failed,
every failure silently fell back to keyword scores, and the feature had NEVER run across
1,313 rows while looking implemented. Heuristic: fixed schema + mechanical judgment →
small model; open-ended research, disambiguation, or writing → larger model. ALWAYS set
the model explicitly — never inherit a default. The registry enforces this: every entry in
`radar/joints.py` carries an explicit model and the test asserts it.

## Timeouts are a real parameter, not a constant
Set them from observed batch time (~30x), and cap rather than disable. An uncapped hang
costs the whole day's run: the digest's sent-today guard blocks every hourly retry behind
a stuck process. The registry carries each joint's cap; the test asserts one exists.

## When to fan out parallel agents
Fan out when items are independent and I/O-bound: the tier backfill over 551 companies,
discovery across 7 role families, probing ATS tokens across employers. Do NOT fan out a
dependent chain — the nightly stages feed each other (funding → tier bands → slug
resolution → discovery → observed → calendar) and must stay sequential. Rule: parallel iff
reordering the items changes nothing.

## "Degrades gracefully" and "fails silently" are the same sentence
Any fallback indistinguishable from success will hide a dead feature indefinitely. Every
fallback must REPORT quality and callers must INSPECT it — that is what
`eligibility.last_run_quality()` exists for, why `poll.discovered_postings()` logs its
count even at zero, and why `observed.capture()` returns match counts into the nightly
report. When adding any fallback, add its quality signal in the same commit.

## Naming is load-bearing
A function named for behaviour it no longer has is an active liability: `rerank` hid
resume-fit grading for hours because the name implied scoring, so nobody asked what it
scored ON. It is `eligibility.filter_ineligible` now. Rename on behaviour change, in the
same commit.

## Non-negotiables
- **Scoring is blind to the operator's history.** Role family and company caliber only.
  No fit inference, no resume wiring, no "angles" unless `profile.yaml` re-enables them
  (absent-means-off — score.py emits no `angle_pitch` key at all while off).
- **No prestige bypass.** Unmatched titles do not ship; T1/T2 drops are logged to
  `data/dropped_unmatched.jsonl` for pattern PROPOSALS, never auto-adds.
- **Nothing expires on age.** The queue is worked to zero; rows leave only when tapped.
- **Defer, don't degrade.** If the eligibility joint cannot run clean, do not send.
  Backstop 18:00. `_mark_deferred()` must record why, or the watchdog cries wolf.
- **A 404 is safe; a wrong 200 is not.** Every identity-bearing fetch goes through
  `radar/fetch.py:validated_fetch` — do not bypass it, extend it.
- **Dedup on normalised keys, never display strings.**
- **Never originate mail from a work domain.**

## Skills and tools (capability first — that is what routes)
- **Scrapling** (shipped: `skills/scrapling/`) — reads ANY publicly-viewable page past
  anti-bot layers, no key/credits/login; replaces paid enrichment vendors when the data is
  public. Used by tiers/fetch/local_scrape. Use when a fetch returns 403/JS-shell, when
  scoping any enrichment task, when a vendor wants money for public data.
- **Claude Code CLI** — headless judgment with web search on an existing subscription; the
  five joints. Any coding-agent CLI honoring the contracts in `joints.py` substitutes.
- **mailer** (shipped: `tools/mailer.py`) — headless SMTP as a SPECIFIC named account,
  Keychain-stored password; works from launchd where no MCP exists. Never send as the
  unspecified default — it may be a work mailbox.
- **gh CLI** — GitHub ops from the shell; self-heal issue closing, run logs, dispatch.
- **Composio / Gmail MCP** — in-chat email fallback only (`mcp.json`).
None of it needs a paid API key. Resolution details: `DEPENDENCIES.md` + `install.sh`.

## Failure signatures — what broken LOOKS like (real lines)
```
[eligibility] batch failed, keeping keyword scores: Expecting value: line 1 column 1 (char 0)
[defer] eligibility filter degraded (0 ok / 1 failed) — not sending        ← CLI outage; correct behavior
[defer] no network (likely just woke) — not sending; will retry            ← Mac woke without DNS
[tiers] rejected 'uber' for 'Uber': slug redirect: uber -> ubercreativedigitalagency   ← wrong-200 caught
[discovery] ingested 0 rows from data/discovered.jsonl                     ← file empty ≠ ingest dead; both log
[nightly] discovery: {"ok": true, "result": {"found": 0}, ...}             ← 0 found: run the positive control
[warn] newsletter <name>: HTTP Error 403: Forbidden                        ← that source dark, not the run
digest done: nothing sent                                                  ← after 18:00 this is the failure
```
An agent that cannot recognise a broken run will report success. When in doubt, compare
today's log to these shapes before believing either the log or yourself.

## Two checkouts
The checkout your launchd jobs point at (conventionally `~/.internship-radar`) is production. Dev clones are separate. Merging to
main deploys nothing until production pulls (`cd ~/.internship-radar && git pull`).
`digest.py` self-heals this each run; never rely on that while verifying a change.
