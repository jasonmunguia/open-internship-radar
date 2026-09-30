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
    """n verdicts over span_days, each with a queue row beside it (queue.jsonl in the
    same dir) — a verdict no record can name is not evidence and is left out."""
    base = 1_700_000_000
    queue = os.path.join(os.path.dirname(path), "queue.jsonl")
    with open(path, "w") as fh, open(queue, "w") as qh:
        for i in range(n):
            row = {"company": f"Co{i}", "title": f"Analyst Intern {i}",
                   "url": f"https://jobs.example.com/{i}"}
            qh.write(json.dumps(row) + "\n")
            ts = base + (i * span_days * 86400) // max(n - 1, 1)
            fh.write(json.dumps({"job_id": queue_state.job_id(row),
                                 "action": "no" if i % 2 else "yes", "ts": ts}) + "\n")

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


# ---- the verdict join: every tap reaches the joint with facts, or is counted out ----

def _join_env(monkeypatch, td):
    from radar import verdict_jd
    for mod, name, fn in [(feedback_analysis, "FEEDBACK", "feedback.jsonl"),
                          (feedback_analysis, "QUEUE", "queue.jsonl"),
                          (verdict_jd, "OUT", "verdict_jd.jsonl")]:
        monkeypatch.setattr(mod, name, os.path.join(td, fn))
    monkeypatch.setattr(feedback_analysis, "_rules_now", lambda: (lambda row: "excluded"))
    return verdict_jd


def test_join_falls_back_to_capture_when_row_left_queue(monkeypatch):
    """A row a later rule removed from the queue still has its tap-time identity in
    verdict_jd.jsonl. Before 2026-09-30 such verdicts reached the joint blank."""
    with tempfile.TemporaryDirectory() as td:
        vj = _join_env(monkeypatch, td)
        open(feedback_analysis.QUEUE, "w").close()             # the row is gone
        with open(feedback_analysis.FEEDBACK, "w") as fh:
            fh.write(json.dumps({"job_id": "gone1", "action": "no", "ts": 5}) + "\n")
        with open(vj.OUT, "w") as fh:
            fh.write(json.dumps({"job_id": "gone1", "company": "AbbVie",
                                 "title": "Pharmaceutical Sales Intern", "jd": ""}) + "\n")
        joined, _first, _last, unresolved = feedback_analysis._evidence()
        assert unresolved == 0 and len(joined) == 1
        assert joined[0]["company"] == "AbbVie"
        assert joined[0]["title"] == "Pharmaceutical Sales Intern"
        assert joined[0]["rules_now"] == "excluded"


def test_unresolvable_taps_left_out_and_counted(monkeypatch):
    """Test taps ("test-verify", "t") name no row anywhere: not evidence, but counted —
    a silent drop would look exactly like a lost verdict."""
    with tempfile.TemporaryDirectory() as td:
        _join_env(monkeypatch, td)
        open(feedback_analysis.QUEUE, "w").close()
        with open(feedback_analysis.FEEDBACK, "w") as fh:
            for jid in ("test-verify", "t"):
                fh.write(json.dumps({"job_id": jid, "action": "yes", "ts": 1}) + "\n")
        joined, _first, _last, unresolved = feedback_analysis._evidence()
        assert joined == [] and unresolved == 2
        monkeypatch.setattr(feedback_analysis, "OUT", os.path.join(td, "out.json"))
        assert feedback_analysis.run() == "skip: 0 verdicts < 10 (2 unresolvable taps left out)"


if __name__ == "__main__":
    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)
    mp = _MP()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(mp) if fn.__code__.co_argcount else fn()
    print("feedback tests OK")
