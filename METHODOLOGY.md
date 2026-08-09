# METHODOLOGY — why this works, and how to rebuild it for yourself

This document is written for **you and your coding agent together.** It explains the reasoning,
not the steps. If you hand your agent this file, it should be able to adapt the system to a
different field, a different country, or a different kind of role — because it will understand
what each decision was *for*, and therefore when to break it.

Every claim below came out of building the thing and watching it fail. Where a rule exists, the
incident that produced it is named. Rules without their incident get deleted by the next person
who finds them inconvenient.

---

## 1. The premise: what actually determines the outcome

Two variables move an early-career application outcome more than anything else you control:

1. **Applying in the first days of a posting**, because most competitive roles review on a
   rolling basis and fill before their stated deadline. The deadline is marketing.
2. **A referral**, which mostly determines whether a human reads your resume at all.

Everything in this system serves the first, and its pre-network email serves the second. Notice
what is *not* here: no resume optimiser, no cover-letter generator, no application autofill.
Those optimise the part of the funnel you are already spending time on. The unattended part —
noticing a req exists, on the day it exists — is where an always-on system beats a person.

**Corollary that reshaped the design:** detection latency matters far less than you would guess.
The gap between two-hour and one-day detection rarely decides a req that fills over three weeks.
Knowing the date a req opens *before* it opens is worth more than any speed improvement. That is
why a whole email exists just to say "this opens in nine days, go meet someone there now."

---

## 2. Architecture: deterministic spine, LLM at the joints

The single most useful structural decision. **Fetching, parsing, scoring, and delivery are plain
code. A model is invoked only where the alternative is a heuristic that would be wrong.**

Why not let a model do more? Three reasons, in order of importance:

- **Reproducibility.** A deterministic scorer gives the same answer twice. When your results look
  wrong you can diff a config, not re-litigate a prompt.
- **Cost and availability.** The spine runs in free CI on a schedule. If your model access dies,
  you still get email — degraded, but not nothing.
- **Debuggability.** When a model is inside the loop everywhere, every bug is a prompt bug and
  none of them are reproducible.

Why use a model at all, then? Because four specific questions have no regex answer:

| Joint | The question | Why code cannot do it |
|---|---|---|
| Semantic re-rank | "Is this borderline row actually relevant?" | Rule scores are blunt at the margin by construction |
| Slug resolution | "Which of these same-named companies is the real one?" | Requires world knowledge and cross-checking |
| Title-variant discovery | "Is this unfamiliar title actually the role I want?" | The whole point is that no pattern matches it yet |
| Collision adjudication | "Two signals disagree — which is lying?" | Judgment, not arithmetic |

**The decision rule to give your agent:** *use code when the same input must always produce the
same output; use a model when the input is prose, ambiguous, or requires knowing something not
present in the data. If a model is used, verify its output through the same gates a deterministic
path would face — a model's answer earns no free trust.*

That last clause is load-bearing. When our slug resolver asks a model which LinkedIn page belongs
to a company, the returned slug is re-fetched and re-validated exactly like a guessed one.

---

## 3. When to reach for Scrapling vs a paid API vs a model

This one cost us real money-shaped mistakes, so the rule is blunt:

```
Need data about a company or a job?
│
├─ Is it visible on a public web page to a logged-out visitor?
│   └─ YES → Scrapling. Free, no key, no credits. This covers far more than people expect:
│            follower counts, headcount, descriptions, pricing, directories, search results,
│            job boards with no API. CHECK THIS FIRST, ALWAYS.
│
├─ Is there a free official API? (SEC EDGAR, USAJOBS, ATS boards)
│   └─ YES → use it. Structured, stable, polite.
│
├─ Is it behind a login you legitimately hold?
│   └─ Consider carefully. If the account belongs to an employer or a shared org, the audit
│      trail may disclose your job search. We built a YC Bookface integration and then
│      deliberately did not ship it for exactly this reason. Access is not permission.
│
└─ Only now: a paid enrichment vendor.
```

**The mistake this prevents:** the first version of company tiering was going to call a paid
enrichment API for headcount and revenue. A logged-out LinkedIn company page shows follower count
and employee count to anyone, and Scrapling reads it in two seconds. The reasoning error was
thinking of Scrapling as "the scraping tool" rather than as its actual capability: *reach any
publicly viewable page past anti-bot defenses.* **Describe your tools by capability, not by use
case, or you will not recognise when they apply.**

---

## 4. How the source list was actually built

Not "we found some job boards." The method, in the order that matters:

**Tier 1 — direct ATS APIs.** Most companies run Greenhouse, Ashby, Lever, or Workday, and all of
them expose a public JSON endpoint keyed by a company token:

```
https://boards-api.greenhouse.io/v1/boards/<token>/jobs
https://api.ashbyhq.com/posting-api/job-board/<token>
https://api.lever.co/v0/postings/<token>?mode=json
```

The token is usually the company name lowercased. **Probe it before adding it.** A guessed token
returns nothing and looks exactly like a company that posted nothing — silent dead coverage. Our
probe script tries each platform per company and records the live job count as proof.

> Incident: our first probe returned 0 out of 17 companies. The cause was a missing
> `SSL_CERT_FILE`, not an absence of boards. Reporting "none of these have public boards" would
> have been a confident, well-formatted, completely wrong answer. **Always sanity-check a
> negative result against a case you know should be positive.**

**Tier 2 — community job-list repos.** Volunteer-maintained GitHub repos that aggregate postings,
several updating hourly. These are how you reach the walled employers — the largest companies
often have no pollable board at all, and a repo that polls thousands of endpoints is the only
practical route. One good aggregator repo can be worth more than fifty direct feeds.

**Tier 3 — VC portfolio boards.** Getro and Consider power most venture firms' talent pages, and
one URL exposes every portfolio company's jobs. Excellent leverage: you cover thousands of
startups you have never heard of without naming any of them.

**Tier 4 — watch pages.** Organisations that publish to their own HTML on short, hard windows.
Government and intelligence agencies are the archetype: no API, no consistency, and a window that
may last days. Watch the page, do not wait for an aggregator to notice.

**Tier 5 — open web discovery.** Query templates against a search engine, filtered to the hosts
postings actually live on (`site:boards.greenhouse.io`, `site:jobs.ashbyhq.com`). This answers
"what exists?" rather than "what did the boards I already know publish?" — it is how you find
postings from a company nobody put on a list.

**Rotate your search instances.** A single public search endpoint rate-limits or disappears, and
if you treat one as reliable your discovery pass silently returns zero forever.

---

## 5. Scoring: grade the role and the company, never the candidate

The first scorer graded *fit to the operator's resume*. It was wrong, and the reason generalises.

If you score fit against a resume, you encode one snapshot of one self-presentation. A serious
candidate maintains several resumes and reframes the same experience per role family. Scoring
against one of them quietly steers the whole funnel toward roles that resume already fits — the
opposite of what a discovery system is for. **The system's job is to widen the funnel; you narrow
it, at application time, with the right resume.**

So the score is `role-family weight + company-tier points`, and nothing else.

**Role families.** Group titles by the job they describe, not by their words. "Deployment
Strategist", "Solutions Intern", and "Implementation Consultant" are one family. Keep families at
**equal weight** unless you genuinely prefer one — an unequal weight is you deciding in advance
which career you want, in a config file, months before you have the information to decide.

**Company tier from public signals, not a hand-typed list.** A list can only answer "did someone
type this company?", so every company nobody typed collapses to unknown and disappears. Compute a
band from the **best of three independent signals**:

- **Audience size** (e.g. LinkedIn followers) — proxy for "would anyone recognise this"
- **Headcount** — catches large but unglamorous employers
- **Capital raised** — catches young, serious, not-yet-famous companies

Best-of-three, never an average. A well-funded 40-person startup has no audience and no headcount;
averaging buries it. Taking the best signal surfaces it.

> **Cap what each signal can prove.** We initially let capital raised reach the top band, and a
> vertical-SaaS company landed alongside the largest tech firms on lifetime funding. Money proves
> a company is *real*, not that it is a marquee name. Funding now tops out one band below.

**Keep a manual override list anyway** — for prestige no metric can see. Elite consulting firms
and intelligence agencies have no meaningful follower count. Let the computed band be the floor
for everyone else.

**Set the threshold with arithmetic, not vibes.** Pick your minimum acceptable company band, then
choose weights so `family weight + that band's points` exactly equals your alert threshold.
Everything at or above the floor alerts; everything below is silent. Now the threshold means
something you can state in a sentence.

---

## 6. The three emails, and why each exists

**Pre-network (opens in ~14 days).** The only one that creates advantage rather than reacting to
it. Sourced from a calendar of expected open dates, refreshed nightly by a model with web access
because "when does this program open?" lives in prose across career pages and last year's
postings. A stale date here fails in the worst direction: you network toward a window that already
closed. **It repeats daily until you mark it done** — a heads-up shown once, on a morning you were
busy, is a heads-up that never happened.

**The apply queue.** Everything currently open that you have not yet applied to. This is a
**queue you work to zero, not a feed you skim.**

> Original design: a rolling 14-day window. It showed every role every morning for 14 days whether
> or not you had applied, then dropped it whether or not you had. Both complaints — "I see the
> same thing repeatedly" and "things disappear before I get to them" — were the same missing
> piece: **no per-role state.**

Fix: each link routes through a redirect that records the tap before forwarding to the posting.
Tapped rows never return. Untapped rows **never expire** — they persist with a day counter, so
pressure comes from a visible number rather than silent deletion. Group by posting date (Today,
This week, Last week, This month) so the freshest reqs, where early application actually matters,
sit at the top.

**Burning alerts.** Anything above threshold, within one poll cycle. Check the posting is still
live first: an alert for a closed req teaches you to ignore alerts.

---

## 7. Reliability: defer, do not degrade

If the quality-improving step cannot run, **do not send a worse version on time.** Wait, retry,
and send the good one late. A 10/10 email at 9am beats a 7/10 at 7:20, because the whole product
is trust that the email is worth opening.

Two conditions make this safe:
- **A hard backstop.** At some hour, send the degraded version anyway. No email is worse than a
  late one.
- **Distinguish deferred from broken.** Record *why* you deferred, or your health monitor pages
  you with a false alarm every deferred morning and you stop trusting the monitor.

---

## 8. The failure catalogue — the most transferable part of this repo

Every one of these shipped, looked fine, and was silently wrong. They are all the same shape:
**a failure that returns a plausible answer instead of an error.**

| What happened | Why it was invisible | The general lesson |
|---|---|---|
| A site redirected an unknown company slug to a *different* company on a foreign domain, and a substring name check accepted it | Returned real numbers for the wrong company | **A 404 is safe; a wrong 200 is dangerous.** Validate identity, not just status |
| Two real companies shared a name; the correct-looking page was the wrong company | Correct slug, correct name, wrong entity | Structural gates cannot catch semantic collisions. Cross-check an independent signal |
| A "recent funding" file was a 14-day rolling window, used as if it were history | Empty for old companies, which reads as "never raised" | **Know whether your state is a window or a log.** Rolling data cannot answer historical questions |
| `except Exception: return []` around an API call | A rejected query looked identical to "no results" | Never let a failure and an empty result share a representation |
| A workflow triggered by an external event sat on a feature branch | The event fired; nothing received it; no error anywhere | Event-triggered CI usually only runs from the default branch |
| Two checkouts of the same repo; only one was deployed | Merging reported success while changing nothing | Know which copy actually runs. Print the version at startup |
| A dry-run flag with a name one character off from the real one | It sent real email while reporting a dry run | Make destructive-vs-safe modes fail loudly when misconfigured |

**The meta-lesson, and the one to tell your agent:** *run it, then check the result against
something you independently know to be true.* Every failure above passed code review and unit
tests. Each was caught by comparing output to reality — a company whose size we knew, a count that
should not have gone down, a file that should have changed and did not.

---

## 9. Adapting this to something else entirely

The architecture is not about internships. To retarget it:

1. **Rewrite the role families** in `config/profile.yaml`. Group by job-to-be-done, not keywords.
2. **Rewrite the eligibility gates.** Ours excludes senior titles and engineering roles. Yours
   might exclude junior ones, or require a location, or a clearance.
3. **Repoint the sources.** The ATS probing method works for any employer set. VC boards work for
   any startup search. Watch pages work for anything with no API.
4. **Re-tune the tier thresholds** against ~30 organisations you already have an opinion about,
   *before* going live. If a company you consider marginal lands top-band, your thresholds are
   wrong. This calibration run takes twenty minutes and is the highest-value step in setup.
5. **Keep the joints.** Re-rank, resolution, discovery, and adjudication are domain-independent.

What does *not* transfer: our specific patterns, thresholds, and company lists. Those are one
person's judgment about one job market at one moment. Rebuild them from your own.
