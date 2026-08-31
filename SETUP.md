# SETUP — bring your own keys, 30-60 minutes (most of it is deciding what you want)

This runs on your own Claude subscription and free tiers. No API keys are required for the
core loop. Costs nothing beyond what you already pay for.

## 1. Clone and install
```
git clone https://github.com/<you>/internship-radar ~/.internship-radar
cd ~/.internship-radar && pip3 install -r requirements.txt
```
`~/.internship-radar` is not arbitrary — `REPO_DIR` in `radar/digest.py` points there. Use a
different path and you must change that constant, or the digest will read another checkout's
config and you will debug a ghost.

## 2. Tell it who you are
Edit **`config/person.yaml`**: name, GitHub handle, repo, `delivery.to`, `delivery.send_as`,
and `work_domains` (mailboxes it must never send FROM — your employer's, typically).

Edit **`config/profile.yaml`**: role families and their patterns, company tier overrides,
eligibility gates, `high_fit_threshold`. The shipped values assume an undergraduate seeking
internships; change `gate_patterns` and `exclude_patterns` if that is not you.

Edit **`config/sources.yaml`**: boards to poll. The shipped list is a strong default.

## 3. Email delivery
Either the mailer skill (SMTP, password in Keychain) or Composio MCP with `GMAIL_SEND_EMAIL`.
Send FROM a personal account TO wherever you read mail — **do not send from an address to
itself**, Gmail files self-sends under Sent with no INBOX label and you will never see them.

## 4. Cloud polling
Push to a PRIVATE GitHub repo (your click/application history lives in it).
`.github/workflows/poll.yml` runs every 2h on Actions. The default `GITHUB_TOKEN` is
enough for polling + issue-relay alerts; for CLEAN-SUBJECT alert emails add three repo
secrets: `GMAIL_APP_PASSWORD`, `GMAIL_SENDER`, `ALERT_TO`.

## 5. Local jobs (four launchd templates in docs/)
Copy each `docs/launchd-*.plist.example` to `~/Library/LaunchAgents/com.internship-<name>.plist`,
replace every `/Users/YOURNAME` with your real home directory (launchd expands neither `~`
nor `$HOME`), check the python3 path, then `launchctl load` each. Schedules: scrape 7:05,
digest 6:00 with hourly :20 retries to 18:20 (the StartCalendarInterval array IS the retry
mechanism), nightly 2:10, selfheal every 30 min. The digest must run locally — the
eligibility joint needs your local coding-agent CLI. Also copy
`config/release_calendar.example.yaml` to `release_calendar.yaml` and seed it with
programs YOU care about, or the pre-network email stays empty.
## 6. Click relay (optional but recommended)
Without it the emails still work; you just lose tap-to-clear, so rows never leave the queue.

1. Fine-grained GitHub token, **Contents: Read and write**, scoped to this repo only —
   create it at https://github.com/settings/personal-access-tokens/new
2. `vercel --prod` from the repo root (no account yet? https://vercel.com/signup — the
   hobby tier is enough; CLI via `npm i -g vercel`)
3. Set `GH_TOKEN` and `GH_REPO` in Vercel env vars (project → Settings → Environment
   Variables on vercel.com), redeploy
4. Put the deployment URL in `person.yaml` as `delivery.relay_base`

`apply-log.yml` must be on your **default branch** or `repository_dispatch` has nowhere to
deliver and clicks log nothing, silently.

## 7. Verify before trusting it
```
IR_DRY=1 python3 -m radar.digest          # renders to /tmp; sends nothing, WRITES nothing
```
The flag is `IR_DRY`. `DRY=1` does nothing and will send real mail. A dry run is fully
read-only — it does not sync the production clone, advance state, or start day counters.
