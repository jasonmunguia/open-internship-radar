"""A tap must clear the ROLE, not the URL it was tapped from.

2026-09-02 (the operator): Databricks/Appian/Amex kept resurfacing after 'I applied' because
job_id() hashes the URL, so the same requisition arriving from jobright, Simplify, speedrun
and the company's own page carried four ids and only the tapped one left the list. On the
live queue that day 41 rows were same-company-same-title twins of an applied row.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import queue_state as qs  # noqa: E402


def _ledger(monkeypatch, td, rows):
    p = os.path.join(td, "applied.jsonl")
    with open(p, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    monkeypatch.setattr(qs, "APPLIED", p)
    return p


# ---- requisition ids: the strongest twin signal, host-independent ----

def test_req_id_greenhouse_variants_collapse():
    a = qs.req_id("https://job-boards.greenhouse.io/databricks/jobs/6883068002")
    b = qs.req_id("https://databricks.com/company/careers/open-positions/job?gh_jid=6883068002")
    c = qs.req_id("https://job-boards.greenhouse.io/embed/job_app?for=databricks&gh_src=Simplify&token=6883068002")
    d = qs.req_id("https://job-boards.greenhouse.io/appian/jobs/8041243?gh_src=Simplify")
    assert a == b == c and a
    assert d and d != a

def test_req_id_oracle_and_career_mirror_collapse():
    a = qs.req_id("https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011916?utm=x")
    b = qs.req_id("https://careers.americanexpress.com/en/sites/CX_1/job/26011916/")
    assert a == b and a

def test_req_id_workday_ashby_smartrecruiters():
    assert qs.req_id("https://workiva.wd503.myworkdayjobs.com/careers/job/USA---Remote/Spring-2027-Intern---Customer-Success_R12206") == "wd:r12206"
    assert qs.req_id("https://jobs.ashbyhq.com/ramp/1f75a275-2bcf-4cb2-a121-eef0a453475f/application") == "uuid:1f75a275-2bcf-4cb2-a121-eef0a453475f"
    assert qs.req_id("https://jobs.smartrecruiters.com/AbbVie/3743990014896329") == "sr:3743990014896329"

def test_req_id_none_for_aggregator_listing():
    # jobright ids are per-LISTING, not per-req: two jobright rows for one role differ.
    assert qs.req_id("https://jobright.ai/jobs/info/6a5908d763a8f619507bfd68?utm_campaign=1047") is None
    assert qs.req_id("#") is None
    assert qs.req_id("") is None


# ---- role key: company + title with the term/season split out ----

def test_role_key_strips_punctuation_emoji_and_terms():
    co, core, terms = qs.role_key({"company": "American Express", "title": "Product Management Intern 🛂"})
    assert (co, core, terms) == ("american express", "product management intern", frozenset())
    co, core, terms = qs.role_key({"company": "Appian", "title": "Product Manager Intern (Summer 2027)"})
    assert (co, core) == ("appian", "product manager intern")
    assert terms == frozenset({"summer", "2027"})


# ---- the filter itself ----

def test_twin_from_other_board_is_done(monkeypatch):
    tapped = {"company": "Databricks", "title": "Product Management Intern (Summer 2027)",
              "url": "https://job-boards.greenhouse.io/databricks/jobs/6883068002"}
    jobright = {"company": "Databricks", "title": "Product Management Intern (Summer 2027)",
                "url": "https://jobright.ai/jobs/info/6a5908d763a8f619507bfd68?utm_campaign=1047"}
    site = {"company": "Databricks", "title": "Product Management Intern",
            "url": "https://www.databricks.com/company/careers/product/product-management-intern-summer-2027"}
    other = {"company": "Databricks", "title": "Solutions Architect Intern",
             "url": "https://job-boards.greenhouse.io/databricks/jobs/7000000000"}
    with tempfile.TemporaryDirectory() as td:
        _ledger(monkeypatch, td, [{"job_id": qs.job_id(tapped), "action": "applied", "ts": 1, "url": tapped["url"]}])
        done = qs.done_state([tapped, jobright, site, other])
        assert qs.is_done(tapped, done)
        assert qs.is_done(jobright, done)      # same title, different board
        assert qs.is_done(site, done)          # title lost its season suffix on the site
        assert not qs.is_done(other, done)     # different role at the same company

def test_season_guard_keeps_a_different_term(monkeypatch):
    summer = {"company": "Appian", "title": "Product Manager Intern (Summer 2027)",
              "url": "https://careers.appian.com/jobs/8041243-product-manager-intern-"}
    bare = {"company": "Appian", "title": "Product Manager Intern ",
            "url": "https://speedrun-talent-network.com/jobs/product-manager-intern-appian-0b3da9f7"}
    fall = {"company": "Appian", "title": "Product Manager Intern (Fall 2026)",
            "url": "https://job-boards.greenhouse.io/appian/jobs/9999999"}
    with tempfile.TemporaryDirectory() as td:
        _ledger(monkeypatch, td, [{"job_id": qs.job_id(summer), "action": "applied", "ts": 1, "url": summer["url"]}])
        done = qs.done_state([summer, bare, fall])
        assert qs.is_done(bare, done)
        assert not qs.is_done(fall, done)      # a different term is a different application

def test_req_id_matches_when_tapped_row_left_the_queue(monkeypatch):
    # The applied row itself is gone from queue.jsonl; only the ledger's URL survives.
    mirror = {"company": "American Express", "title": "Campus Undergraduate Summer Internship Program - 2027",
              "url": "https://careers.americanexpress.com/en/sites/CX_1/job/26011916/"}
    with tempfile.TemporaryDirectory() as td:
        _ledger(monkeypatch, td, [{"job_id": "deadbeef0000", "action": "applied", "ts": 1,
                                   "url": "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011916"}])
        done = qs.done_state([mirror])
        assert qs.is_done(mirror, done)

def test_undo_reopens_the_whole_family(monkeypatch):
    a = {"company": "Gemini", "title": "Product Management Intern", "url": "https://job-boards.greenhouse.io/gemini/jobs/1"}
    b = {"company": "Gemini", "title": "Product Management Intern", "url": "https://jobright.ai/jobs/info/abc"}
    with tempfile.TemporaryDirectory() as td:
        _ledger(monkeypatch, td, [{"job_id": qs.job_id(a), "action": "applied", "ts": 1, "url": a["url"]},
                                  {"job_id": qs.job_id(a), "action": "undo", "ts": 2, "url": a["url"]}])
        done = qs.done_state([a, b])
        assert not qs.is_done(a, done) and not qs.is_done(b, done)

def test_same_title_other_company_untouched(monkeypatch):
    a = {"company": "Stripe", "title": "Product Manager Intern", "url": "https://stripe.com/jobs/1"}
    b = {"company": "Plaid", "title": "Product Manager Intern", "url": "https://plaid.com/jobs/1"}
    with tempfile.TemporaryDirectory() as td:
        _ledger(monkeypatch, td, [{"job_id": qs.job_id(a), "action": "applied", "ts": 1, "url": a["url"]}])
        assert not qs.is_done(b, qs.done_state([a, b]))

def test_blank_title_never_collapses(monkeypatch):
    a = {"company": "", "title": "", "url": "https://x.com/1"}
    b = {"company": "", "title": "", "url": "https://y.com/2"}
    with tempfile.TemporaryDirectory() as td:
        _ledger(monkeypatch, td, [{"job_id": qs.job_id(a), "action": "applied", "ts": 1, "url": a["url"]}])
        assert not qs.is_done(b, qs.done_state([a, b]))


# ---- the click Action must never drop a tap ----

def test_apply_log_has_no_concurrency_group():
    """GitHub keeps ONE pending run per concurrency group and cancels the older pending run
    when another dispatch arrives: 16 of 41 taps on 2026-08-31 were cancelled before a job
    ever started. data/*.jsonl merge=union makes serialisation unnecessary."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wf = open(os.path.join(root, ".github", "workflows", "apply-log.yml")).read()
    assert "concurrency:" not in wf
    assert "merge=union" in open(os.path.join(root, ".gitattributes")).read()


def test_role_key_strips_trailing_location():
    a = qs.role_key({"company": "American Express",
                     "title": "Campus Undergraduate Summer Internship Program - 2027 Product Management, Global Commercial Services - New York, NY"})
    b = qs.role_key({"company": "American Express",
                     "title": "Campus Undergraduate Summer Internship Program - 2027 Product Management, Global Commercial Services"})
    assert a == b
    # a different team at the same company is still a different role
    c = qs.role_key({"company": "American Express",
                     "title": "Campus Undergraduate Summer Internship Program - 2027 Product Management, Global Merchant & Network Services - Phoenix, AZ"})
    assert c[1] != a[1]
    assert qs.role_key({"company": "X", "title": "PM Intern (Remote)"})[1] == "pm intern"
    assert qs.role_key({"company": "X", "title": "PM Intern - Richmond, VA"})[1] == "pm intern"
    # not a location: a plain hyphenated qualifier survives
    assert qs.role_key({"company": "X", "title": "PM Intern - Payments"})[1] == "pm intern payments"


def test_liveness_error_keeps_what_the_cli_said(monkeypatch):
    from radar import joints, liveness
    class R:  # a CompletedProcess whose stdout is prose, not JSON
        stdout = "You've hit your usage limit.\nTry again later."
        stderr = ""
    monkeypatch.setattr(joints, "run_joint", lambda *a, **k: R())   # _judge_batch imports it lazily
    verdicts, err = liveness._judge_batch([("u1", {"company": "X", "title": "Y", "url": "u1"}, "text")])
    assert verdicts == {}
    assert "cli: You've hit your usage limit." in err

