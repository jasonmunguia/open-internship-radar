# open-internship-radar

An always-on job radar you run yourself. It polls ~164 sources every two hours, scores what it
finds against role families and company caliber, and emails you three things: **what opens soon**
(so you can network before the posting exists), **what is open now** (as a queue you work to zero,
not a feed you skim), and **anything urgent, within the hour**.

It runs on **your own LLM subscription** — no API keys, no per-token cost, no vendor account. The
deterministic parts run free in GitHub Actions whether your laptop is open or not.

**Setup: 30–60 minutes.** Most of that is deciding what you actually want, which is the part worth
your time.

**Have a coding agent? Paste it this single instruction and it can do the rest:**
> Read `METHODOLOGY.md`, then `CLAUDE.md`, then `AGENT_ONBOARDING.md`, then run
> `bash install.sh` and bring me online per the onboarding doc. Treat unedited example
> config as unfinished setup, and end with a real run I can see.

---

## Why this exists

Two things move an early-career outcome more than anything else you control: **applying in the
first days a posting is live**, and **a referral**. Competitive roles review on a rolling basis and
fill before their stated deadline — the deadline is marketing.

Noticing that a req exists, on the day it exists, across hundreds of employers, is a task a person
loses to a machine. Writing the application is not. So this system does only the first part, and
does it well, and stays out of the rest.

> **Read [`METHODOLOGY.md`](METHODOLOGY.md) before you configure anything.** It explains *why*
> each decision was made — including the ones that were wrong first. It is written to be handed
> to your coding agent so it can adapt the system rather than just run it.

---

## What you get

**Three emails, each with a job**

- **Pre-network** — programs opening in the next ~14 days, with a pre-filtered people search per
  company. Repeats daily until you mark it done, because a heads-up shown once on a busy morning
  is a heads-up that never happened.
- **Apply queue** — everything open you have not applied to, grouped Today / This week / Last week
  / This month. Tap a link and it never appears again. Do not tap it and it never disappears — it
  accrues a visible day counter instead.
- **Burning alert** — anything above threshold within one poll cycle, after verifying the posting
  is still live.

**A scorer that grades the role and the company, not you.** It does not model your resume. That is
deliberate: scoring fit against one resume steers the whole funnel toward roles that resume
already fits. The system widens; you narrow at application time.

**Company tiering from public signals.** Audience size, headcount, and capital raised, taking the
best of the three — so a well-funded 40-person startup with no audience still surfaces.

---

## Architecture in one picture

```
GitHub Actions (every 2h, no laptop)        Your machine (daily + nightly)
├─ 120 direct ATS APIs                      ├─ 07:20 digest, retried hourly to 18:20
├─ 25 community job-list repos              │   └─ defers rather than sending a worse email
├─ VC portfolio boards                      └─ 02:10 deep pass
├─ watch pages (no-API employers)               ├─ funding history
├─ SEC funding filings                          ├─ company tier backfill (scraper)
└─ score → burning alert if urgent              ├─ resolve what the scraper could not
                                                ├─ open-web discovery
                                                └─ refresh the release calendar (LLM + web)
```

**Deterministic spine, LLM at the joints.** Fetching, parsing, scoring, and delivery are plain
code — same input, same output, debuggable, free. A model is invoked at exactly five registered joints (`radar/joints.py` — enforced by
`tests/test_joints.py`) where the alternative would be a heuristic that is wrong. Full reasoning in `METHODOLOGY.md` §2.

---

## Setup

Follow [`SETUP.md`](SETUP.md). The short version:

1. Clone; `bash install.sh` (installs requirements + Scrapling, ships the skills and
   the mailer, verifies every dependency in `DEPENDENCIES.md`)
2. `cp config/person.example.yaml config/person.yaml` — who you are, where mail goes
3. `cp config/profile.example.yaml config/profile.yaml` — **the file that matters.** Role
   families, eligibility gates, tier thresholds
4. Edit `config/sources.yaml` — ships with a strong default set
5. Push to GitHub; Actions starts polling
6. Install the launchd/cron jobs from `docs/`
7. Optional: deploy `api/a.js` to Vercel for tap-to-clear links

**Do the calibration run before going live.** Score ~20 organisations you already have an opinion
about and check the bands match your instinct. Twenty minutes, and it is the highest-value step in
the whole setup — untuned thresholds either flood you or hide everything.

---

## Retargeting it

Nothing here is specific to internships. Rewrite the role families and eligibility gates, repoint
the sources, re-tune the thresholds. `METHODOLOGY.md` §9 walks through it. The parts that transfer
are the architecture, the source-discovery method, and the failure catalogue; the parts that do
not are one person's patterns and thresholds for one market at one moment.

---

## Documentation

| File | What it is for |
|---|---|
| [`METHODOLOGY.md`](METHODOLOGY.md) | **Start here.** Why every decision was made, the failure catalogue, how to adapt it |
| [`SETUP.md`](SETUP.md) | Step-by-step install |
| [`TOOLS.md`](TOOLS.md) | Every tool, the job it does, the LLM joints, the failure modes |
| [`CLAUDE.md`](CLAUDE.md) | Operating doctrine for a coding agent working in this repo |
| [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md) | How an agent brings a HUMAN online — the three jobs, the four questions |
| [`DEPENDENCIES.md`](DEPENDENCIES.md) | Every external tool: capability, what it is load-bearing for, where to get it |

## Honesty about maturity

Built and run by one person against one job market. The architecture and the failure catalogue are
the durable parts. The specific thresholds, patterns, and company lists are one set of judgments
and you should replace them with your own. Several components have run for days, not months.

Issues and PRs welcome, particularly source additions with a live probe result attached.

MIT.
