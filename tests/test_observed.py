"""Regression tests for observed_opens (spec item 8b: observed ground truth).

The matcher's first live probe (2026-08-09) produced 14 phantom matches because 'cia',
'dia', 'nsa' and 'meta' are substrings of unrelated company names. Those phantoms are
pinned here as MUST-NOT-MATCH cases: a future loosening of the matcher fails loudly
instead of silently polluting the calendar's ground-truth evidence.

Run locally:  python3 -m pytest tests/test_observed.py -q
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar.observed import _company_matches, _key, capture, evidence_block  # noqa: E402


def test_company_matcher_exact_and_prefix():
    assert _company_matches(_key("SpaceX"), _key("SpaceX"))
    assert _company_matches(_key("Amazon"), _key("Amazon Web Services (AWS)"))
    assert _company_matches(_key("Tesla"), _key("Tesla Motors"))
    assert _company_matches(_key("Scale AI"), _key("Scale AI"))


def test_company_matcher_rejects_the_phantom_class():
    # the exact false positives from the first live probe — short keys inside other names
    assert not _company_matches(_key("CIA"), _key("Acacia Trading"))
    assert not _company_matches(_key("DIA"), _key("Media Labs"))
    assert not _company_matches(_key("NSA"), _key("Naukr AI"))
    assert not _company_matches(_key("Meta"), _key("Metagenomi"))
    assert not _company_matches(_key("BCG"), _key("ABC Global"))
    # short keys still match exactly
    assert _company_matches(_key("CIA"), _key("CIA"))


def test_capture_matches_dedupes_and_filters_titles():
    with tempfile.TemporaryDirectory() as td:
        q = os.path.join(td, "queue.jsonl")
        c = os.path.join(td, "cal.yaml")
        o = os.path.join(td, "observed.jsonl")
        with open(q, "w") as fh:
            fh.write(json.dumps({"company": "SpaceX", "title": "Spring 2027 Business Operations Internship/Co-op",
                                 "url": "https://x/1", "posted_at": "2026-08-03"}) + "\n")
            fh.write(json.dumps({"company": "SpaceX", "title": "Senior Director, Launch Ops",
                                 "url": "https://x/2", "posted_at": "2026-08-01"}) + "\n")
            fh.write(json.dumps({"company": "Acacia Trading", "title": "Quantitative Intern",
                                 "url": "https://x/3", "posted_at": "2026-08-02"}) + "\n")
            # boards emit junk dates ("September ") — must demote to first_seen, never
            # enter the evidence as a sortable date
            fh.write(json.dumps({"company": "SpaceX", "title": "Fall 2027 Ops Internship",
                                 "url": "https://x/4", "posted_at": "September ",
                                 "ts": 1786300000}) + "\n")
        with open(c, "w") as fh:
            fh.write('- {program: "SpaceX internships", company: SpaceX}\n'
                     '- {program: "CIA Undergraduate Internship Program", company: CIA}\n')
        r1 = capture(queue_path=q, cal_path=c, out_path=o)
        # row 1 matches; row 2 ("Senior Director, Launch Ops") matches the title regex via
        # "launch" but that is fine — company gate is what keeps phantoms out; row 3 must
        # NOT match CIA despite containing "cia" and "Intern"
        rows = [json.loads(l) for l in open(o)]
        assert all(x["program"] == "SpaceX internships" for x in rows), rows
        assert any(x["url"] == "https://x/1" and x["date"] == "2026-08-03"
                   and x["date_kind"] == "posted_at" for x in rows)
        junk = [x for x in rows if x["url"] == "https://x/4"]
        assert junk and junk[0]["date_kind"] == "first_seen" and junk[0]["date"].startswith("2026-"), junk
        assert r1["new"] == len(rows) > 0
        # idempotent: a second pass records nothing new
        r2 = capture(queue_path=q, cal_path=c, out_path=o)
        assert r2["new"] == 0, r2
        # and the evidence block cites the observed date
        block = evidence_block(path=o)
        assert "2026-08-03" in block and "SpaceX internships" in block


if __name__ == "__main__":
    test_company_matcher_exact_and_prefix()
    test_company_matcher_rejects_the_phantom_class()
    test_capture_matches_dedupes_and_filters_titles()
    print("observed_opens OK")
