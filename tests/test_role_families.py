"""A role is one row in the digest and leaves only when tapped or confirmed closed
(2026-10-28 per the operator). Guards the three ways it was slipping:
  - copies of one role from different boards showed as separate rows ("NVIDIA ✓" vs
    "Nvidia", "The Walt Disney Company" vs "Disney")
  - a role was judged closed by one copy's link (IQVIA's dead jobright link hid a role
    whose other copies were never checked)
  - an alerted role was hidden by the freshness window (Apple EPM: alerted 10-25,
    posted in May) or by a re-score under the floor

Run locally:  python3 -m pytest tests/test_role_families.py -q
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import digest, fetchers, liveness, queue_state as qs  # noqa: E402
from radar.poll import alert_keys  # noqa: E402

NOW = int(time.time())


def row(company, title, url, ts=NOW, posted_at=None, source="t"):
    return {"company": company, "title": title, "url": url, "ts": ts,
            "posted_at": posted_at, "source": source}


def test_badge_and_emoji_variants_are_one_role():
    a = row("NVIDIA ✓", "Go-to-Market Strategy Intern, NPN AI Consulting - Summer 2027 🆕",
            "https://github.example/list#1")
    b = row("Nvidia", "Go-to-Market Strategy Intern, NPN AI Consulting - Summer 2027",
            "https://speedrun-talent-network.com/jobs/gtm-nvidia")
    assert len(qs.families([a, b])) == 1


def test_company_name_variants_are_one_role():
    a = row("The Walt Disney Company", "Social Media Marketing Strategy Intern, Spring 2027", "https://a.example/1")
    b = row("Disney", "Social Media Marketing Strategy Intern, Spring 2027", "https://b.example/2")
    assert len(qs.families([a, b])) == 1


def test_shared_req_id_joins_different_titles():
    """Visa's req REF089881W arrived as 'Product Management Intern' (APM List) and under
    its full title (Workday): one role, two rows in the 10-28 email."""
    a = row("Visa", "Product Management Intern, Data and AI Team - Summer 2027",
            "https://visa.wd5.myworkdayjobs.com/Visa/job/US---Foster-City-CA/PM-Intern_REF089881W")
    b = row("Visa", "Product Management Intern",
            "https://visa.wd5.myworkdayjobs.com/Visa_Early_Careers/job/US---Foster-City-CA/PM_REF089881W")
    assert len(qs.families([a, b])) == 1


def test_different_reqs_same_title_stay_apart():
    a = row("Microsoft", "Product Manager Intern", "https://ms.wd1.myworkdayjobs.com/x/job/Redmond/PM_JR111111")
    b = row("Microsoft", "Product Manager Intern", "https://ms.wd1.myworkdayjobs.com/x/job/Cambridge/PM_JR222222")
    assert len(qs.families([a, b])) == 2


def test_unrelated_companies_and_other_seasons_stay_apart():
    assert len(qs.families([row("Meta", "Product Intern", "https://a/1"),
                            row("Metabase", "Product Intern", "https://b/2")])) == 2
    assert len(qs.families([row("Acme", "PM Intern (Fall 2026)", "https://a/1"),
                            row("Acme", "PM Intern (Summer 2027)", "https://b/2")])) == 2


def test_alerted_role_survives_the_freshness_window():
    old = NOW - 150 * 86400
    apple = row("Apple", "Engineering Program Management Undergrad Internships",
                "https://jobs.apple.com/en-us/details/200600000", ts=old, posted_at="2026-05-21")
    stale = row("Acme", "Strategy Intern", "https://a/9", ts=old, posted_at="2026-05-21")
    seen = {alert_keys(apple)[0]: NOW - 3 * 86400}
    roles, _ = digest.standing_roles([apple, stale], seen, 28, since=NOW - 86400)
    assert roles == [apple] and apple["_alerted"]


def test_fresh_copy_represents_the_role():
    old = row("Acme", "Strategy Intern", "https://a/1", ts=NOW - 60 * 86400, posted_at="2026-08-01")
    new = row("Acme", "Strategy Intern", "https://b/2", ts=NOW - 3600)
    roles, copies = digest.standing_roles([old, new], {}, 28, since=NOW - 86400)
    assert roles == [new] and copies[id(new)] == [old]


def test_alerted_role_kept_when_rescore_drops_under_floor(monkeypatch):
    monkeypatch.setattr(digest, "score_posting", lambda r, *a, **k: (40, {"tier": "T1"}))
    a, b = row("A", "PM Intern", "https://a/1"), row("B", "PM Intern", "https://b/1")
    a["_alerted"] = True
    passing, _ = digest.rescore_and_partition([a, b], {}, {}, {})
    assert passing == [a]


def _fake_sweep(verdicts):
    """sweep stand-in: verdict per URL ('live' | 'dead' | 'unsure')."""
    def sweep(rows, allow_network=True):
        out = {"live": [], "dead": [], "unsure": []}
        for r in rows:
            out[verdicts.get(r["url"], "unsure")].append(r)
        return out["live"], out["dead"], out["unsure"], {"checked": len(rows), "error": None, "suspect": 0}
    return sweep


def _q():
    return {"checked": 0, "error": None, "suspect": 0}


def test_dead_link_with_an_open_copy_ships_the_open_copy(monkeypatch):
    rep = row("IQVIA", "Associate Co-op, Healthcare Strategy Consulting", "https://jobright.ai/jobs/info/dead")
    alt = row("IQVIA", "Associate Co-op, Healthcare Strategy Consulting", "https://speedrun.example/jobs/iqvia")
    monkeypatch.setattr(liveness, "sweep", _fake_sweep({alt["url"]: "live"}))
    live, dead, unsure = digest.family_liveness([], [rep], [], _q(), {id(rep): [alt]})
    assert dead == [] and unsure == [] and live[0]["url"] == alt["url"]
    assert live[0]["title"] == rep["title"]


def test_role_drops_only_when_every_copy_is_closed(monkeypatch):
    rep = row("X", "PM Intern", "https://x/1")
    alts = [row("X", "PM Intern", "https://x/2"), row("X", "PM Intern", "https://x/3")]
    monkeypatch.setattr(liveness, "sweep", _fake_sweep({"https://x/2": "dead", "https://x/3": "dead"}))
    live, dead, unsure = digest.family_liveness([], [rep], [], _q(), {id(rep): alts})
    assert dead == [rep] and live == [] and unsure == []


def test_closed_rep_with_an_unverifiable_copy_is_held_not_dropped(monkeypatch):
    rep = row("X", "PM Intern", "https://x/1")
    alt = row("X", "PM Intern", "https://x/2")
    monkeypatch.setattr(liveness, "sweep", _fake_sweep({"https://x/2": "unsure"}))
    live, dead, unsure = digest.family_liveness([], [rep], [], _q(), {id(rep): [alt]})
    assert unsure == [rep] and dead == []


def test_direct_company_link_is_tried_before_aggregators(monkeypatch):
    rep = row("Salesforce", "Summer 2027 Intern - Product GTM Strategy", "https://jobright.ai/jobs/info/a")
    agg = row("Salesforce", "Summer 2027 Intern - Product GTM Strategy", "https://jobright.ai/jobs/info/b")
    ats = row("Salesforce", "Summer 2027 Intern - Product GTM Strategy",
              "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/SF/GTM_JR362217")
    tried = []
    def sweep(rows, allow_network=True):
        tried.extend(r["url"] for r in rows)
        return rows, [], [], {"checked": len(rows), "error": None, "suspect": 0}
    monkeypatch.setattr(liveness, "sweep", sweep)
    live, _, _ = digest.family_liveness([], [rep], [], _q(), {id(rep): [agg, ats]})
    assert tried == [ats["url"]] and live[0]["url"] == ats["url"]


def test_workday_source_can_set_its_own_search_and_filter(monkeypatch):
    """Accenture: US-country facet + 'summer', paged in full even with no 'intern' titles."""
    sent = []
    def post(url, body, hdr):
        sent.append(dict(body))
        jobs = [{"title": f"Summer Analyst {body['offset'] + i}", "externalPath": f"/job/x_R{body['offset'] + i}"}
                for i in range(20 if body["offset"] == 0 else 3)]
        return json.dumps({"total": 23, "jobPostings": jobs})
    monkeypatch.setattr(fetchers, "_post_hdr", post)
    rows = fetchers.fetch_workday("Accenture", "accenture@wd103/AccentureCareers",
                                  search="summer", facets={"locationCountry": ["us-id"]})
    assert len(rows) == 23 and len(sent) == 2
    assert sent[0]["searchText"] == "summer" and sent[0]["appliedFacets"] == {"locationCountry": ["us-id"]}


def test_old_alerted_role_gets_its_own_bucket():
    assert qs.bucket({"posted_at": "2026-05-21"}) == "Older (alerted)"
    assert "Older (alerted)" in qs.BUCKET_ORDER


def test_workday_req_id_shapes():
    rid = qs.req_id
    assert rid("https://visa.wd5.myworkdayjobs.com/Visa/job/X/PM_REF089881W-1") == "wd:ref089881w"
    assert rid("https://zapply.jobs/l/d/workday-visa-visa-REF089881W?s=gh") == "wd:ref089881w"
    assert (rid("https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/SF/GTM_JR362217-1")
            == rid("https://salesforce.wd12.myworkdayjobs.com/Futureforce_Internships/job/SF/GTM_JR362217"))
