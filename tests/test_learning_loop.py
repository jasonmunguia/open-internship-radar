"""Learning-loop check-in cycle, deterministic halves (2026-08-15 additions).

The IMAP read and SMTP send are monkeypatched at the module's indirection points —
the live transports verify through the nightly, same posture as test_feedback.py.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import learning_loop as ll  # noqa: E402

NOW = 1_800_000_000


def _tmp(monkeypatch, patterns=None):
    d = tempfile.mkdtemp()
    monkeypatch.setattr(ll, "STATE", os.path.join(d, "learning_loop.json"))
    monkeypatch.setattr(ll, "PATTERNS", os.path.join(d, "feedback_patterns.json"))
    monkeypatch.setattr(ll, "REPLIES", os.path.join(d, "feedback_replies.jsonl"))
    if patterns is not None:
        json.dump(patterns, open(ll.PATTERNS, "w"))
    return d


def _capture_send(monkeypatch):
    sent = []
    monkeypatch.setattr(ll, "_send_email", lambda subj, body: sent.append((subj, body)) or True)
    return sent


def test_cold_start_compose(monkeypatch):
    _tmp(monkeypatch)
    token, subject, body = ll.compose(NOW)
    assert token.startswith("LRN-") and token in subject
    assert "Cold start" in body and "Reply to this email" in body


def test_nos_render_first(monkeypatch):
    _tmp(monkeypatch, {"verdict_count": 14, "proposals": [
        {"pattern": "likes robotics", "polarity": "yes", "evidence": "5/5", "proposal": "none"},
        {"pattern": "rejects unpaid", "polarity": "no", "evidence": "0/6", "proposal": "gate pay"},
    ]})
    _, _, body = ll.compose(NOW)
    assert body.index("rejects unpaid") < body.index("likes robotics")


def test_weekly_send_then_await(monkeypatch):
    _tmp(monkeypatch)
    sent = _capture_send(monkeypatch)
    assert ll.run(NOW).startswith("weekly check-in sent")
    assert len(sent) == 1
    # same night again: awaiting, not re-sent, no follow-up (cadence not reached)
    monkeypatch.setattr(ll, "check_reply", lambda aw: None)
    assert ll.run(NOW + 60).startswith("awaiting reply")
    assert len(sent) == 1


def test_daily_followup_until_reply(monkeypatch):
    _tmp(monkeypatch)
    sent = _capture_send(monkeypatch)
    monkeypatch.setattr(ll, "check_reply", lambda aw: None)
    ll.run(NOW)
    assert ll.run(NOW + 26 * 3600).startswith("follow-up #1")     # next calendar day
    assert ll.run(NOW + 50 * 3600).startswith("follow-up #2")     # the day after
    assert len(sent) == 3
    assert "Day 1" in sent[1][1] and sent[1][0].startswith("Re: ")


def test_followup_fires_next_morning_not_24h_later(monkeypatch):
    """The cadence bug this guards: a check-in sent at 16:56 with a 22h elapsed-time
    gate would hold at the 02:10 nightly (only 9h later) and not nudge until the
    following night — 33h after the ask, skipping a day he expected to hear on."""
    _tmp(monkeypatch)
    _capture_send(monkeypatch)
    monkeypatch.setattr(ll, "check_reply", lambda aw: None)
    import time as _t
    evening = int(_t.mktime(_t.strptime("2026-08-15 16:56", "%Y-%m-%d %H:%M")))
    next_nightly = int(_t.mktime(_t.strptime("2026-08-16 02:10", "%Y-%m-%d %H:%M")))
    ll.run(evening)
    assert ll.run(next_nightly).startswith("follow-up #1")


def test_reply_ingested_and_loop_stops(monkeypatch):
    _tmp(monkeypatch)
    sent = _capture_send(monkeypatch)
    ll.run(NOW)
    reply = {"ts": NOW + 3600, "from": "the operator <j@example.edu>", "token": "LRN-x",
             "text": "drop all defense below T2"}
    monkeypatch.setattr(ll, "check_reply", lambda aw: reply)
    assert ll.run(NOW + 7200).startswith("reply received")
    saved = [json.loads(l) for l in open(ll.REPLIES)]
    assert saved[0]["text"] == "drop all defense below T2"
    # loop is closed: next night is a plain weekly-gate skip, nothing sent
    assert ll.run(NOW + 2 * 86400).startswith("skip")
    assert len(sent) == 1


def test_imap_outage_withholds_followup(monkeypatch):
    _tmp(monkeypatch)
    sent = _capture_send(monkeypatch)
    ll.run(NOW)

    def boom(aw):
        raise OSError("imap.gmail.com unreachable")
    monkeypatch.setattr(ll, "check_reply", boom)
    assert ll.run(NOW + 30 * 3600).startswith("imap outage")
    assert len(sent) == 1          # no blind nag


def test_strip_quoted():
    text = "keep this\n> quoted junk\nOn Mon, Aug 17, 2026 at 9:00 AM X wrote:\nand this"
    assert ll.strip_quoted(text) == "keep this\nand this"


def test_own_mail_not_a_reply(monkeypatch):
    _tmp(monkeypatch)
    monkeypatch.setattr(ll, "_search_inbox", lambda token, since_ts: [
        {"from": "me@gmail.test", "subject": "Re: [LRN-x]", "ts": NOW, "text": "nudge body"}])
    import types
    fake = types.SimpleNamespace(resolve=lambda a: "me@gmail.test")
    monkeypatch.setitem(sys.modules, "mailer", fake)
    assert ll.check_reply({"token": "LRN-x", "sent_ts": NOW - 60}) is None
