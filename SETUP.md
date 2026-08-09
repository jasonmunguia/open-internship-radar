# SETUP — bring your own keys, ~15 minutes

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
Push to GitHub. `.github/workflows/poll.yml` runs every 2h on Actions with no secrets beyond
the default `GITHUB_TOKEN`.

## 5. Local digest
Copy `com.internship-digest.plist` to `~/Library/LaunchAgents/`, edit the paths and
label, then `launchctl load` it. It must run locally — the re-rank needs your Claude session.

## 6. Click relay (optional but recommended)
Without it the emails still work; you just lose tap-to-clear, so rows never leave the queue.

1. Fine-grained GitHub token, **Contents: Read and write**, scoped to this repo only
2. `vercel --prod` from the repo root
3. Set `GH_TOKEN` and `GH_REPO` in Vercel env vars, redeploy
4. Put the deployment URL in `person.yaml` as `delivery.relay_base`

`apply-log.yml` must be on your **default branch** or `repository_dispatch` has nowhere to
deliver and clicks log nothing, silently.

## 7. Verify before trusting it
```
IR_DRY=1 python3 -m radar.digest          # renders to /tmp, sends nothing
```
The flag is `IR_DRY`. `DRY=1` does nothing and will send real mail.
