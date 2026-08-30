# TOOLS — what this system uses, and why

The radar is a **deterministic spine with LLM judgment at the joints.** Fetching, parsing,
scoring, and delivery are plain Python that run unattended in GitHub Actions with no model
involved. A model is reached only where regex genuinely cannot decide. That split is the
architecture, not an implementation detail — if you replace the model, the spine still runs.

Everything below is what a fresh clone actually depends on. Nothing here is optional
background: each entry is load-bearing somewhere in the pipeline.

## Where each source type is reached, and by what

| Source type | Count | Reached by | Detection lag |
|---|---|---|---|
| Direct ATS APIs | 120 | plain HTTPS JSON — Greenhouse, Ashby, Lever, Workday, Getro, Consider, SmartRecruiters, Eightfold | <= 2h (poll interval) |
| Job-list GitHub repos | 25 | GitHub raw markdown fetch | repo update lag + <= 2h |
| Newsletters | 7 | Substack JSON | days |
| Watch pages | 12 | HTML fetch, Scrapling when blocked | <= 2h |
| SEC Form D | — | EDGAR full index (free, no key) | daily |

Walled employers (Google, Microsoft, LinkedIn, Apple, Amazon, Goldman) publish no pollable
board. They are reachable ONLY through the job-list repos — which is why `zshah101`
(~4,285 endpoints across 12 ATS platforms) matters more than any single direct feed.

## Tools, and the specific job each does

**Python 3.11 + PyYAML** — the whole spine. No framework.

**Scrapling** (`radar/scrapling_fetch.py`, `radar/tiers.py`) — anti-bot page fetching.
The capability that matters is not "scraping a website"; it is **reaching any publicly
readable page past an anti-bot layer**. That is why it can read logged-out LinkedIn company
pages for follower and employee counts at zero cost — the fact that unlocks company tiering
without a paid enrichment API. If you find yourself reaching for a credits-based data vendor,
check first whether the data is on a public page.

**GitHub Actions** — the 2-hourly poll (`.github/workflows/poll.yml`), the click logger
(`apply-log.yml`), and the dead-man's-switch (`heartbeat.yml`). Cloud-side, no laptop needed.

**launchd** (`~/Library/LaunchAgents/com.internship-digest.plist`) — the daily digest,
retried hourly 6:00–18:20. It must run locally because the eligibility filter needs the local
Claude session. launchd does NOT inherit an interactive shell's environment, which is why
config lives in `config/person.yaml` rather than env vars.

**Claude Code CLI** — the eligibility filter, invoked as a subprocess. **No API key.** This is
the BYOK story: the operator's own Claude subscription does the judgment work. Any coding-agent
CLI can be substituted; see "LLM joints" below for exactly what it must do.

**Composio MCP** (`GMAIL_SEND_EMAIL`) — email fallback. Routes by account alias; it silently
defaults to the wrong mailbox unless `account:` is passed explicitly.

**mailer skill** (`~/.claude/tools/mailer.py`) — primary SMTP send, credentials in Keychain.
Preferred over Composio because it produces a clean subject with no `[owner/repo]` prefix.

**gh CLI** — repo operations and the issue relay used as a last-resort delivery channel.

**Vercel** (`api/a.js`) — the click relay. A tap is recorded, then 302s to the posting.
Writes go through `repository_dispatch` so concurrent taps serialise inside Actions rather
than racing a file SHA.

**SEC EDGAR** via the `free-apis` skill — Form D filings, the funding tier signal.

## LLM joints — the six places a model is used, and the registry that enforces it

**`radar/joints.py` is the registry and the only door to the CLI** — every joint's model,
timeout and contract lives there, and `tests/test_joints.py` fails if a model call appears
anywhere else. (This section used to say "four"; building the registry on 2026-08-09
surfaced a fifth the prose had missed — which is why the registry exists.)

1. **eligibility** (`radar/eligibility.py`, was `rerank`) — every new drop scoring >= 40
   gets a second opinion before anything is hidden. May only remove the IMPOSSIBLE;
   defaults to eligible; never expresses preference.
2. **slug_resolve** (`radar/tiers.py`) — after slug guesses and a search-engine lookup
   both fail, a model is asked which LinkedIn page is really this company. Every answer is
   re-verified through the same gates as a guess; omission is correct, guessing is not.
   (Name collisions — funding says serious, followers say tiny — feed this queue too.)
3. **discovery** (`radar/discover.py`) — "what postings exist?" with real web search.
   Only postings actually seen; never constructed URLs; empty array is a valid answer.
4. **calendar** (`radar/calendar_research.py`) — refreshes release-date estimates; may
   revise dates only with a cited evidence URL (and `radar/observed.py` feeds it the real
   post dates the system has itself witnessed); malformed output is a no-op.
5. **source_heal** (`radar/self_heal.py`) — a source dark 3+ polls after automated repair
   failed: may edit only that source's entry in sources.yaml, must verify jobs return,
   never commits.
6. **feedback_patterns** (`radar/feedback_analysis.py`) — weekly analysis of the ✓/✗
   verdict taps joined to row facts (gated: ≥10 verdicts, ≥7-day span, new data only).
   Returns pattern PROPOSALS rendered in the digest; never edits any file — applying a
   proposal is the operator's call, made in conversation.

Title-variant mining from `data/dropped_unmatched.jsonl` is MANUAL today: ask an agent to
mine the local drop log; it PROPOSES patterns to a human and never auto-adds them. (No
automated nightly miner exists; the log only accumulates on the local machine.)

## Failure modes and what they look like

- **Wrong-company 200s.** LinkedIn 301s an unknown slug to a nearest match on a foreign host.
  `/company/uber` resolved to a UK creative agency and passed a substring name check, tiering
  Uber at T3 on 5,984 followers. Gated now on the final URL's slug plus exact-prefix name
  matching. **A 404 is safe; a wrong 200 is the dangerous one.**
- **Rolling vs persistent state.** `funded_watch.json` is a ~14-day window, not a history.
  Treating it as history left the funding signal dead for every company that raised earlier.
  `radar/funding_history.py` accumulates permanently.
- **repository_dispatch only fires workflows on the DEFAULT branch.** A workflow on a feature
  branch receives nothing, silently.
- **Two checkouts.** `REPO_DIR` is hardcoded to `~/.internship-radar`; the dev clone is
  separate. Merging to main deploys nothing until that checkout pulls.
- **Dedup on normalised keys, never display strings.** The same req arrives from six boards
  with six spellings of the company name.

## Deliberately not used

**Member networks and credentialed portals** (Bookface, Handshake and kin) — excluded by design: a radar must never operate someone's account, and job-search activity inside a members-only network is attributable to the member. If you want that coverage, browse it yourself.

**Paid enrichment (Apollo / Clay / FullEnrich)** — the data these were wanted for (follower
counts, headcount) sits on public pages that Scrapling reads for free. Check the public page
before spending a credit.

## Conventions that are not obvious

- Config is the interface: `person.yaml` (who), `profile.yaml` (what they want),
  `sources.yaml` (where to look). Forking for someone else means editing those three.
- Scoring is blind to the operator's resume. It grades **role family** and **company caliber**
  only. See `config/profile.yaml` on why `angles` is paused.
- Nothing expires on age. The apply list is a queue worked to zero; rows leave only when tapped.
- Delivery never originates from a work domain. `person.yaml` hard-blocks them.
