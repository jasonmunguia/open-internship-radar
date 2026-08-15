"""Verdict-tap plumbing + pay extraction, per the 2026-08-15 additions.

Covers the deterministic halves only. The feedback_patterns JOINT (model call) cannot
be smoke-tested here — nested claude -p is intercepted in sessions (see CLAUDE.md);
its gates and parsing are tested, the live run verifies through the nightly.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar.fetchers import extract_pay  # noqa: E402
from radar import feedback_analysis, queue_state  # noqa: E402


# ---- pay extraction ----

def test_pay_hourly_range():
    assert extract_pay("compensation is $45 - $55 per hour for this role") == "$45-$55/hr"

def test_pay_hourly_slash():
    assert extract_pay("Pay: $52.50/hr") == "$52.50/hr"

def test_pay_annual_range():
    assert extract_pay("base salary $120,000 - $150,000 plus equity") == "$120,000-$150,000/yr"

def test_pay_k_form():
    assert extract_pay("Comp: $110k-$130k DOE") == "$110k-$130k/yr"

def test_pay_ignores_funding_amounts():
    # POSITIVE CONTROL inverse: a funding blurb must NOT read as pay.
    assert extract_pay("the company raised $60M and is hiring") == ""

def test_pay_empty_on_no_signal():
    assert extract_pay("a great internship with competitive compensation") == ""


# ---- verdict last-wins ----

def test_verdicts_last_tap_wins(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        fb = os.path.join(td, "feedback.jsonl")
        with open(fb, "w") as fh:
            fh.write(json.dumps({"job_id": "abc", "action": "yes", "ts": 1}) + "\n")
            fh.write(json.dumps({"job_id": "abc", "action": "no", "ts": 2}) + "\n")
            fh.write(json.dumps({"job_id": "def", "action": "yes", "ts": 3}) + "\n")
            fh.write(json.dumps({"job_id": "ghi", "action": "applied", "ts": 4}) + "\n")  # not a verdict
        monkeypatch.setattr(queue_state, "FEEDBACK", fb)
        v = queue_state.verdicts()
        assert v == {"abc": "no", "def": "yes"}


# ---- analysis gates: every skip states why, and no model call is reached ----

def _write_feedback(path, n, span_days):
    base = 1_700_000_000
    with open(path, "w") as fh:
        for i in range(n):
            ts = base + (i * span_days * 86400) // max(n - 1, 1)
            fh.write(json.dumps({"job_id": f"id{i}", "action": "no" if i % 2 else "yes",
                                 "ts": ts}) + "\n")

def test_gate_too_few_verdicts(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        fb = os.path.join(td, "feedback.jsonl")
        _write_feedback(fb, 4, 10)
        monkeypatch.setattr(feedback_analysis, "FEEDBACK", fb)
        monkeypatch.setattr(feedback_analysis, "QUEUE", os.path.join(td, "queue.jsonl"))
        monkeypatch.setattr(feedback_analysis, "OUT", os.path.join(td, "out.json"))
        assert feedback_analysis.run().startswith("skip: 4 verdicts")

def test_gate_span_too_short(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        fb = os.path.join(td, "feedback.jsonl")
        _write_feedback(fb, 12, 3)   # plenty of verdicts, only 3 days of them
        monkeypatch.setattr(feedback_analysis, "FEEDBACK", fb)
        monkeypatch.setattr(feedback_analysis, "QUEUE", os.path.join(td, "queue.jsonl"))
        monkeypatch.setattr(feedback_analysis, "OUT", os.path.join(td, "out.json"))
        assert feedback_analysis.run().startswith("skip: span")

def test_gate_no_new_verdicts(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        fb = os.path.join(td, "feedback.jsonl")
        _write_feedback(fb, 12, 10)
        out = os.path.join(td, "out.json")
        json.dump({"ts": 1, "verdict_count": 12, "proposals": []}, open(out, "w"))
        monkeypatch.setattr(feedback_analysis, "FEEDBACK", fb)
        monkeypatch.setattr(feedback_analysis, "QUEUE", os.path.join(td, "queue.jsonl"))
        monkeypatch.setattr(feedback_analysis, "OUT", out)
        monkeypatch.setattr(feedback_analysis, "REPLIES", os.path.join(td, "replies.jsonl"))
        assert feedback_analysis.run() == "skip: no new verdicts or check-in replies since last analysis"


if __name__ == "__main__":
    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)
    mp = _MP()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(mp) if fn.__code__.co_argcount else fn()
    print("feedback tests OK")
