"""Weekly learning check-in -> operator reply loop (2026-08-15 per the operator).

The digest already RENDERS what the feedback joint thinks it has learned. This module
makes that a conversation: once a week it emails the patterns — the "no" patterns
first, because rejections carry the correction signal — and asks for a reply. The
nightly then watches the sending mailbox over IMAP and follows up DAILY until a reply
arrives. The reply is appended verbatim to data/feedback_replies.jsonl, which
feedback_analysis feeds into every future pattern run as operator guidance, weighted
above anything inferred from taps alone.

Deterministic spine, no new joint: composing, sending, reply polling, and follow-up
cadence are pure Python. Model judgment stays where it already lives — the
feedback_patterns joint that writes data/feedback_patterns.json.

State (data/learning_loop.json, git-tracked like the digest heartbeat — sync_repo
snaps checkouts to origin, so untracked state would be silently rewound):
  last_weekly_ts   when the last weekly check-in went out
  awaiting         {token, sent_ts, followups, last_contact_ts} while a reply is owed

Failure posture: an IMAP outage must not nag. If the inbox cannot be read we CANNOT
know whether he replied, so the follow-up is withheld and the status string reports
the outage — a follow-up sent blind after his reply arrives is worse than a quiet day.
"""
import html
import json
import os
import re
import time
from datetime import datetime

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE = os.path.join(ROOT, "data", "learning_loop.json")
PATTERNS = os.path.join(ROOT, "data", "feedback_patterns.json")
REPLIES = os.path.join(ROOT, "data", "feedback_replies.jsonl")

WEEKLY_EVERY = 7 * 86400 - 2 * 3600     # slack for launchd schedule drift
FOLLOWUP_EVERY = 22 * 3600              # nightly cadence, minus the same drift

_POLARITY_ORDER = {"no": 0, "mixed": 1, "yes": 2}


def _state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save_state(d):
    json.dump(d, open(STATE, "w"), indent=1)


def _send_email(subject, body_html):
    """Indirection point (tests monkeypatch this). Real path reuses the digest's
    sender: named-account SMTP with the Composio/relay fallbacks and IR_DRY."""
    from radar.digest import send_email
    return send_email(subject, body_html)


def _search_inbox(token, since_ts):
    """Indirection point (tests monkeypatch this). Reads the SEND_AS mailbox —
    replies come back to the From address, not to the digest's To."""
    import sys
    sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
    import mailer
    from radar.settings import SEND_AS
    return mailer.search_inbox(SEND_AS, token, since_ts=since_ts)


def strip_quoted(text):
    """His words only: drop quoted lines and the 'On ... wrote:' attribution line."""
    keep = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(">"):
            continue
        if re.match(r"On .{4,80} wrote:$", s):
            continue
        keep.append(line)
    return "\n".join(keep).strip()


def _load_patterns():
    try:
        d = json.load(open(PATTERNS))
        return d.get("proposals") or [], d.get("verdict_count", 0)
    except Exception:
        return [], 0


def compose(now=None):
    """(subject, html) for a check-in. Rejection patterns lead — a 'no' is the
    correction signal; a 'yes' only confirms what already ships."""
    now = now or int(time.time())
    token = f"LRN-{datetime.fromtimestamp(now):%Y%m%d}"
    subject = f"Radar learning check-in [{token}]"   # token plain ASCII: IMAP SUBJECT search finds the reply
    props, n_verdicts = _load_patterns()
    props = sorted(props, key=lambda p: _POLARITY_ORDER.get(p.get("polarity"), 1))
    h = ["<h2>🧠 What your taps are teaching the radar</h2>"]
    if not props:
        h.append(
            f"<p>Cold start: {n_verdicts} verdicts on file — not enough signal to name a "
            "pattern yet. Tap 👍/👎 on digest rows and this email gets substantive. "
            "Meanwhile: <b>reply to this email</b> with anything you already know you "
            "don't want (companies, industries, role shapes) and it goes straight into "
            "the analysis as your own words.</p>")
    else:
        h.append(f"<p>{len(props)} patterns from {n_verdicts} verdicts — rejections first, "
                 "because the 👎s are what correct the system:</p><ol>")
        for p in props:
            pol = {"no": "👎", "yes": "👍"}.get(p.get("polarity"), "↔️")
            h.append(f"<li>{pol} <b>{html.escape(p.get('pattern', ''))}</b><br>"
                     f"<small>evidence: {html.escape(p.get('evidence', ''))}<br>"
                     f"would change: {html.escape(p.get('proposal', ''))}</small></li>")
        h.append("</ol>")
    h.append("<p><b>Reply to this email</b> — confirm, correct, or add in plain English. "
             "Your reply is fed into every future pattern run, weighted above inferred "
             "patterns. Until you reply, a daily nudge re-sends this. Nothing is applied "
             "to scoring config without you saying so.</p>")
    return token, subject, "".join(h)


def check_reply(awaiting):
    """His reply, or None. Raises on transport failure — run() turns that into a
    reported outage instead of a blind follow-up."""
    from radar.settings import SEND_AS
    import sys
    sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
    import mailer
    own = mailer.resolve(SEND_AS).lower()
    for m in _search_inbox(awaiting["token"], awaiting["sent_ts"]):
        if own in (m.get("from") or "").lower():
            continue                            # our own check-in/follow-up, not a reply
        text = strip_quoted(m.get("text", ""))
        if text:
            return {"ts": m.get("ts", 0), "from": m.get("from", ""),
                    "token": awaiting["token"], "text": text}
    return None


def run(now=None):
    """Nightly entry. Returns a status string — every path says what happened,
    because a silent no-op is indistinguishable from a dead feature."""
    now = int(now or time.time())
    st = _state()
    aw = st.get("awaiting")
    if aw:
        try:
            reply = check_reply(aw)
        except Exception as ex:
            return f"imap outage ({type(ex).__name__}: {ex}) — follow-up withheld"
        if reply:
            with open(REPLIES, "a") as fh:
                fh.write(json.dumps(reply) + "\n")
            st.pop("awaiting", None)
            st["last_reply_ts"] = reply["ts"] or now
            _save_state(st)
            return f"reply received for {reply['token']} ({len(reply['text'])} chars) — ingested"
        if now - aw.get("last_contact_ts", 0) >= FOLLOWUP_EVERY:
            token, subject, body = compose(now)
            days = max(1, (now - aw["sent_ts"]) // 86400)
            body = (f"<p><i>Day {days} without a reply — same question, standing nudge. "
                    "One reply stops these.</i></p>" + body)
            # Same token as the original so his eventual reply matches regardless of
            # which email in the chain he answers.
            _send_email(f"Re: Radar learning check-in [{aw['token']}]", body)
            aw["followups"] = aw.get("followups", 0) + 1
            aw["last_contact_ts"] = now
            _save_state(st)
            return f"follow-up #{aw['followups']} sent for {aw['token']}"
        return f"awaiting reply to {aw['token']} (followups so far: {aw.get('followups', 0)})"

    if now - st.get("last_weekly_ts", 0) >= WEEKLY_EVERY:
        token, subject, body = compose(now)
        _send_email(subject, body)
        st["last_weekly_ts"] = now
        st["awaiting"] = {"token": token, "sent_ts": now, "followups": 0,
                          "last_contact_ts": now}
        _save_state(st)
        return f"weekly check-in sent ({token})"

    return f"skip: last check-in {(now - st.get('last_weekly_ts', 0)) // 86400}d ago < 7d"


if __name__ == "__main__":
    print(run())
