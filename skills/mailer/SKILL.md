---
name: mailer
description: "CAPABILITY: sends email as a SPECIFIC named Gmail account (personal / school / work), headlessly — SMTP with an app password stored in the macOS Keychain, so it works from launchd, cron, and CI where no MCP or browser session exists. Displaces MCP-only email paths that die in unattended jobs, and the unspecified-default send that silently originates mail from the wrong mailbox. Use whenever sending mail on the operator's behalf, when an unattended script must send mail, or whenever the from-address matters (job-search mail must NEVER leave from an employer's domain)."
---

# Sending email as the operator

Two routes. **Always name the account explicitly** — an unspecified default may be an
employer's mailbox, and job-search mail in an employer's Sent folder is readable by its
Workspace admins.

| Alias | Address | Use for |
|---|---|---|
| `personal` | you@gmail.com | job search, this radar, anything private |
| `school` | you@example.edu | university, scholarships, campus |
| `work` | you@yourcompany.com | employer business ONLY — never the job search |

## Route 1 — headless SMTP (`tools/mailer.py`) — the radar's primary path

```bash
python3 tools/mailer.py add personal you@gmail.com   # one-time; paste a Gmail app password
                                                     # (myaccount.google.com/apppasswords)
```
```python
import mailer
mailer.send("personal", "you@example.edu", "Subject", "<p>html</p>")
```
Credentials live in the macOS Keychain (never a file, never git). `install.sh` puts the
module at `~/.claude/tools/mailer.py`, which is where `radar/digest.py` imports it from.
Send FROM personal TO where you read mail — never the same address for both (a self-send
files under Sent and is never seen).

## Route 2 — MCP / Composio (in-chat fallback)

If a Gmail MCP or the Composio CLI is connected, the digest falls back to it when SMTP
fails. Route by explicit account; the connected default may not be able to send as every
alias — check before promising it.
