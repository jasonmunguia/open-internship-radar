# DEPENDENCIES — every external thing this system stands on

An agent must be able to resolve every dependency from this file alone. Each entry: what it
fundamentally CAN DO (capability), what it is load-bearing for HERE, where to get it, and
what breaks without it. `install.sh` automates the installable subset and verifies the rest.
None of it needs a paid API key.

## Runtime

**Python 3.11+** — the whole spine.
Load-bearing for: everything. The launchd plists hardcode
`/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`; if your python lives
elsewhere, edit the plists.
Get: python.org installer (`python3 --version` to check yours).
Without it: nothing runs.
Note: **`SSL_CERT_FILE` must point at certifi's bundle or every HTTPS call fails.** The
plists set it. An interactive shell does NOT — export it before hand-testing anything:
`export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")`.
A probe returning 0 results is usually this, not an absence of data.

**PyYAML + pytest** (`requirements.txt`) — config parsing; the test suites install.sh
and CI run. Without PyYAML: import error at startup (loud, safe). Without pytest:
install.sh's verify step reports [MISS].

## Tools

**Scrapling** (shipped skill: `skills/scrapling/`) —
CAPABILITY: reads ANY publicly-viewable page past anti-bot layers (Cloudflare, JS
rendering, fingerprinting) with no API key, no credits, no login. Replaces paid enrichment
vendors whenever the data sits on a public page.
Load-bearing for: company tiering (logged-out LinkedIn follower/employee counts in
`radar/tiers.py` via `radar/fetch.py`), the local corporate scrape (`radar/local_scrape.py`),
the scraped-discovery fallback (`radar/discover.py`).
Get: `pip3 install scrapling && scrapling install` (the second command fetches browser
binaries; without it StealthyFetcher raises at first fetch).
Without it: tier backfill and local scrape die; poll/score/digest still run, but every
unmeasured company stays `pending` (T4, silent) forever.

**Claude Code CLI** (`claude`) —
CAPABILITY: a coding agent with web search, invocable headlessly as a subprocess — the
system's judgment layer, paid for by a subscription you already have. No API key.
Load-bearing for: all six LLM joints (`radar/joints.py` is the registry and the ONLY door
to the CLI; contracts live there).
Get: https://claude.com/claude-code — then confirm `claude -p "Reply with exactly: OK"`
prints OK. Expected at `~/.local/bin/claude` (joints.py falls back to `$PATH`).
Without it: joints degrade per their contracts — the digest DEFERS rather than sending
degraded email (by design); slug resolution/discovery/calendar/source-heal quietly skip.
Any coding-agent CLI can substitute if it honors the contracts in `radar/joints.py`.
TRAP: a nested `claude -p` inside a Claude Code session is intercepted and returns prose,
not JSON. Joints can only be smoke-tested through launchd (see CLAUDE.md).

**mailer** (shipped: `tools/mailer.py` + skill `skills/mailer/`) —
CAPABILITY: headless SMTP send as a SPECIFIC named Gmail account, app-password in the
macOS Keychain — works from launchd/cron where no MCP exists.
Load-bearing for: primary delivery of all three emails, and the deadline-page alerts in
`local_scrape.py`. `radar/digest.py` imports it from `~/.claude/tools/mailer.py`
(install.sh copies it there).
Setup: `python3 tools/mailer.py add personal you@gmail.com` then paste a Gmail app
password (myaccount.google.com/apppasswords).
Without it: digest falls back to Composio, then to the GitHub-issue relay — mail still
arrives, uglier (botty `[owner/repo]` subject prefix).

**Composio CLI** (optional fallback) —
CAPABILITY: authenticated Gmail actions from the shell (`composio execute GMAIL_*`).
Load-bearing for: email fallback #1 in `send_email()`. Route by explicit account — the
unspecified default is a WORK mailbox, which the work-domain guard will refuse.
Get: https://composio.dev CLI + `composio login`. Without it: the fallback chain skips to
the GitHub relay.

**gh CLI** —
CAPABILITY: GitHub operations from the shell with stored auth.
Load-bearing for: closing healed `[health]` issues (`radar/self_heal.py`); ops convenience
(workflow dispatch, run logs). Expected at `~/.local/bin/gh`.
Get: https://cli.github.com. Without it: self-heal cannot close issues (cosmetic); the
issue RELAY still works (it uses `GITHUB_TOKEN` inside Actions, not gh).

## Services (all free tier)

**GitHub Actions** — the cloud engine: 2-hourly poll (`poll.yml`), click logger
(`apply-log.yml`), notifier (`notify.yml`), dead-man's-switch (`heartbeat.yml`), CI lint
(`lint.yml`). Repo secrets used by poll alerts: `GMAIL_APP_PASSWORD`, `GMAIL_SENDER`,
`ALERT_TO`. Without Actions: no real-time alerts, no click relay backend — the local
digest alone still works.

**launchd** (macOS) — the local engine. Four jobs, ALL FOUR templates in `docs/`
(digest 6:00 + hourly :20 retries to 18:20, scrape 7:05, nightly 2:10, selfheal every 30
min). `SETUP.md` covers installing them — launchd expands neither ~ nor $HOME. Without them: no morning emails, no nightly enrichment.

**Vercel** (`api/a.js`, optional) — the click relay: a tap logs to `data/applied.jsonl`
via `repository_dispatch`, then 302s to the posting. Without it: emails carry raw links
and rows never auto-clear from the queue.

**SEC EDGAR** — Form D filings, the funding tier signal. Free, no key, just a User-Agent
header (set from `person.yaml` contact_email). Without it: funding signal empty; tiering
falls back to followers/employees.

## MCP

`mcp.json` documents the optional Gmail MCP path. The system's primary email is SMTP
(mailer.py); MCP is a fallback. Nothing here REQUIRES an MCP server.
