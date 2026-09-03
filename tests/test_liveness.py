"""Regression tests for the liveness gate (added 2026-08-22 per the operator).

The bug this guards against: the queue never expires by age (rows leave only when
tapped), so a posting could close at the source and keep being recommended every
morning — a tapped-through digest surfaced multiple expired roles. The rule now:
a row ships only with a fresh verifiable LIVE verdict; dead is permanent; anything
unverifiable is held, never shipped and never deleted.

Run locally:  python3 -m pytest tests/test_liveness.py -q
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import liveness
from radar.liveness import LIVE_TTL_H, classify, probe, sweep
from radar.queue_state import job_id


def test_classify_definitive_gone_is_dead():
    assert classify(404, "") == "dead"
    assert classify(410, "") == "dead"


def test_classify_closed_marker_is_dead():
    body = "<html>" + "x" * 2000 + "This job is no longer available.</html>"
    assert classify(200, body) == "dead"


def test_classify_readable_page_is_live():
    body = "<html>Product Intern role. Responsibilities... " + "detail " * 400 + "Apply now</html>"
    assert classify(200, body) == "live"


def test_classify_blocked_or_shell_is_unsure():
    assert classify(403, "") == "unsure"           # anti-bot wall proves nothing
    assert classify(None, "") == "unsure"          # network trouble proves nothing
    assert classify(200, "<div id=app></div>") == "unsure"          # JS shell
    assert classify(200, "y" * 3000, url="https://x.myworkdayjobs.com/r/1") == "unsure"


def test_probe_no_url_is_unsure_never_live():
    assert probe("") == "unsure"


def test_workday_url_maps_to_cxs_endpoint():
    m = liveness._WORKDAY.match(
        "https://interdigital.wd5.myworkdayjobs.com/InterDigital_Intern/job/Conshohocken-PA/GenAI-Intern_REQ26-1093")
    assert m and m.groups() == ("interdigital", "wd5", "InterDigital_Intern",
                                "Conshohocken-PA/GenAI-Intern_REQ26-1093")
    # locale segment variants (en-US/) must also parse
    m2 = liveness._WORKDAY.match(
        "https://uline.wd1.myworkdayjobs.com/en-US/Careers/job/Pleasant-Prairie/Intern_R1")
    assert m2 and m2.group(3) == "Careers"


def test_redirect_away_from_job_path_is_dead():
    """Verified live 2026-08-22: KnowBe4's greenhouse posting 302'd to the board root
    with ?error=true — the pulled-req pattern the raw status code can't see."""
    ra = liveness.redirected_away
    assert ra("https://job-boards.greenhouse.io/knowbe4/jobs/8660687002",
              "https://job-boards.greenhouse.io/knowbe4?error=true")
    assert ra("https://boards.greenhouse.io/x/jobs/123456",
              "https://boards.greenhouse.io/x")          # job segment vanished
    assert not ra("https://a.com/jobs/123", "https://a.com/jobs/123")       # no redirect
    assert not ra("https://a.com/en/jobs/123", "https://a.com/en-us/jobs/123")  # locale hop keeps the job
    assert not ra("https://a.com/careers", "https://a.com/careers/home")    # no job path to lose


def test_jobright_valid_through_parses():
    body = '... "validThrough":"2026-09-20T19:29:17" ...'
    vt = liveness._VALID_THROUGH.search(body)
    assert vt and vt.group(1) == "2026-09-20"
    assert liveness._VALID_THROUGH.search('{"noField": 1}') is None


def _row(company="AcmeCorp", url="https://example.com/job/1"):
    return {"company": company, "title": "PM Intern", "url": url}


def test_sweep_cached_dead_drops_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(liveness, "CACHE", str(tmp_path / "liveness.json"))
    r = _row()
    import json
    json.dump({job_id(r): {"status": "dead", "ts": int(time.time())}}, open(liveness.CACHE, "w"))
    live, dead, unsure, q = sweep([r], allow_network=False)
    assert live == [] and dead == [r] and unsure == []


def test_sweep_fresh_live_verdict_ships(tmp_path, monkeypatch):
    monkeypatch.setattr(liveness, "CACHE", str(tmp_path / "liveness.json"))
    r = _row()
    import json
    json.dump({job_id(r): {"status": "live", "ts": int(time.time())}}, open(liveness.CACHE, "w"))
    live, dead, unsure, q = sweep([r], allow_network=False)
    assert live == [r] and q["from_cache"] == 1


def test_sweep_stale_live_verdict_must_reverify(tmp_path, monkeypatch):
    """Yesterday's live verdict is not proof for today's email."""
    monkeypatch.setattr(liveness, "CACHE", str(tmp_path / "liveness.json"))
    r = _row()
    stale = int(time.time()) - (LIVE_TTL_H + 1) * 3600
    import json
    json.dump({job_id(r): {"status": "live", "ts": stale}}, open(liveness.CACHE, "w"))
    live, dead, unsure, q = sweep([r], allow_network=False)
    assert live == [] and unsure == [r]     # no network allowed -> held, not shipped


def test_sweep_unknown_row_is_held_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(liveness, "CACHE", str(tmp_path / "liveness.json"))
    live, dead, unsure, q = sweep([_row()], allow_network=False)
    assert live == [] and unsure and q["checked"] == 0


def test_sweep_unlinked_row_is_dead_not_held(tmp_path, monkeypatch):
    """A '#' or blank URL (board parse artifact) can never be verified or applied to —
    it must die once, not retry forever (Medtronic '#' held daily until 2026-08-22)."""
    monkeypatch.setattr(liveness, "CACHE", str(tmp_path / "liveness.json"))
    rows = [_row("Medtronic", url="#"), _row("Palantir Launch", url="")]
    live, dead, unsure, _q = sweep(rows, allow_network=False)
    assert live == [] and unsure == [] and len(dead) == 2


# ---- bot challenge is a gate, not a verdict (2026-09-02) ----

def test_challenge_redirect_is_not_away():
    orig = "https://jobright.ai/jobs/info/6a9608d3c8763a3a87ffe06d?utm_campaign=1063"
    final = "https://jobright.ai/_jr/security/challenge?return=%2Fjobs%2Finfo%2F6a9608d3c8763a3a87ffe06d"
    assert liveness.redirected_away(orig, final) is False
    assert liveness.redirected_away(orig, "https://jobright.ai/login?next=%2Fjobs%2Finfo%2Fabc") is False
    # the real pulled-req signature still counts
    assert liveness.redirected_away("https://x.greenhouse.io/co/jobs/8660687002",
                                    "https://x.greenhouse.io/co?error=true") is True


def test_probe_challenge_redirect_is_unsure(monkeypatch):
    class R:
        status = 200
        def read(self, n=None): return b"x" * 3000
        def geturl(self): return "https://jobright.ai/_jr/security/challenge?return=%2Fjobs%2Finfo%2Fabc"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(liveness.urllib.request, "urlopen", lambda *a, **k: R())
    assert probe("https://jobright.ai/jobs/info/abc") == "unsure"


def test_paced_hosts_leave_the_thread_pool():
    rows = [("a", {"url": "https://jobright.ai/jobs/info/1"}),
            ("b", {"url": "https://boards.greenhouse.io/x/jobs/2"}),
            ("c", {"url": "https://jobright.ai/jobs/info/3"})]
    paced, pooled = liveness._partition(rows)
    assert [j for j, _ in paced] == ["a", "c"] and [j for j, _ in pooled] == ["b"]
    assert "jobright.ai" in liveness.PACED_HOSTS and liveness.PACE_SECONDS >= 1


def test_digest_commits_the_caches_after_the_sweep():
    """Uncommitted cache files are destroyed by the mirror reset at the next run; the
    sweep's verdicts must be committed before any defer return (2026-09-02)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "radar", "digest.py")).read()
    assert "add data/liveness.json data/company_tiers.json" in src
    call = src.index("        _persist_caches()")
    assert call > src.index("_live_sweep(roles")
    assert call < src.index('if _lv_q.get("error") and _lv_unsure and not DRY:')

