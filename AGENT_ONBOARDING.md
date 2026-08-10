# AGENT_ONBOARDING — read this first if your job is bringing a person online

`CLAUDE.md` tells an agent how to WORK ON this repo. This file tells you how to BRING
SOMEONE ONLINE with it. You have three jobs, in order, and you must know all three before
you say anything to the human. (If the operator is already online — this repo's owner is —
your job collapses to Jobs 1 and 2.)

**"Online" is a specific state, not a vibe. All five must be true:**
1. **Installed** — every dependency resolved; nothing left for the human to go find.
2. **Configured to THEM** — gates, families, thresholds reflect their situation. Shipped
   defaults left untouched means NOT online: every default is one person's answer.
3. **Scheduled** — runs unattended, without the human triggering it.
4. **Proven** — a real end-to-end run completed and produced real output they have SEEN.
   Not a dry run, not "it should work now".
5. **Legible** — they can read the output, know the recurring signals, and would
   recognize a broken run. Output nobody can interpret is not online.

## Job 1 — bootstrap yourself (before asking the human anything)

Run `bash install.sh`. Read `DEPENDENCIES.md` and confirm every entry resolves. Report
gaps in plain language — "I need a page-fetching tool, installing it now", never a
traceback. You never ask the human to install something you can install yourself.
Human-gated steps you CANNOT do alone (walk them through each when you reach it, not
before): their Gmail app password (myaccount.google.com/apppasswords →
`python3 tools/mailer.py add personal their@gmail.com`); the Claude Code CLI login if
absent (it opens a browser); GitHub hosting/auth for the cloud engine — including the
decision that their click/application history will live in that repo, so it should be
PRIVATE; Vercel login + a fine-grained GitHub token if they want the click relay.

## Job 2 — hold the whole model (answerable cold, without searching)

If you cannot answer these after reading `README.md` + `CLAUDE.md` + this file, the docs
failed; fix them before proceeding.
- The three emails and why each exists (pre-network creates advantage; the queue is worked
  to zero; burning alerts are time-critical only).
- THE CONTRACT: a role ships iff title matches a role family AND company is T3+. Both.
  Nothing else decides. The LLM removes the impossible; it never expresses preference.
- The five LLM joints, each one's contract, and where they live (`radar/joints.py`).
- What runs in the cloud (poll, alerts, click relay, watchdog) vs on the machine
  (digest, scrape, nightly enrichment) — and why (a laptop is closed most of the time;
  the LLM rides a local subscription, not an API key).
- What a broken run looks like in the log (`CLAUDE.md` → Failure signatures).

## Job 3 — guide the human, conversationally

Assume zero CLI vocabulary. Say what a step accomplishes, then give ONE paste-able block
with `cd` built in. Decide everything you can decide yourself (which ATS a company uses —
probe it; timeout values — never ask). The only questions worth asking are ones whose
answer lives in their head and nowhere else. Ask EXACTLY these, in this order:

1. **"What roles are you actually looking for?"** → role families. Draft a starting set
   of families + title patterns from their answer, show it, let them correct it.
2. **"What are you eligible for?"** — degree level, graduation year, terms available,
   work authorization, location constraint. → the hard gates. Get these exactly right;
   they are the difference between a useful queue and noise.
3. **"Name ~10 companies you'd be thrilled by and ~10 you wouldn't bother with."** → the
   calibration set. Do NOT ask for thresholds — derive them and show the result.
4. **"Where should email arrive, and which account should send it?"** → delivery. NEVER
   the same address for both — a self-send files under Sent and is never seen.

**Calibration is step one, not an appendix.** Score their ~20 companies with the real
tiering code, show the table, ask "does this match your instinct?", adjust bands/overrides
until it does. This single step decides whether the system floods them or hides everything.

**End with a live proof, not a claim.** Trigger a real run, show the log, show the email
in their inbox. Do not say "you're set up" — show a working email and let THEM say it.

**Then tell them the three things that will confuse them later:**
1. Rows do not disappear until tapped — the day counter is pressure, not decay.
2. A late email means it DEFERRED rather than degraded; it retries hourly until 18:00.
3. An unmeasured company is silent (T4) until the nightly backfill measures it.

**Time budget: 30–60 minutes, most of it questions 1–3.** Taking longer means you are
asking things you should have decided. The failure mode you are designed against: saying
"setup complete" over a system that surfaces nothing because the gates kept someone
else's defaults.
