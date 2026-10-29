"""Offline tests for the Google/Meta career-page parsers and the no-silent-zero contract.

Fixtures are trimmed copies of the live payloads captured 2026-10-28 (long HTML fields
cut to null). Records marked SYNTHETIC were added to cover a branch no live posting hit
that day. If a site changes shape, refresh the fixture from a real capture — never edit
the parser until it passes a hand-made fixture.

Run:  python3 -m pytest tests/test_scrapling_parsers.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import scrapling_fetch as sf

KEYS = {"company", "title", "location", "url", "department", "posted_at", "source"}

# ---- Google: AF_initDataCallback blobs as served in the results page -------------------
_G_JOBS = [
    # live: US-only, multi-location
    ["91436104816698054", "Software Engineering Intern, PhD, Summer 2027", None, None, None,
     "projects/p/tenants/t/companies/c", None, "Google", "en-US",
     [["Mountain View, CA, USA", ["100 Bay Vw Dr, Mountain View, CA 94043, USA"], "Mountain View", "94043", "CA", "US"],
      ["Atlanta, GA, USA", ["Atlanta, GA, USA"], "Atlanta", None, "GA", "US"]],
     None, [4], [1787559294, 670000000], [1788210493, 376000000], [1788210493, 685000000]],
    # live: foreign-only -> dropped
    ["123907061523063494", "Associate Product Marketing Manager BS/MS Intern, 2027", None, None, None,
     "projects/p/tenants/t/companies/c", None, "Google", "en-US",
     [["Dublin, Ireland", ["Dublin, Ireland"], "Dublin", None, None, "IE"],
      ["Paris, France", ["Paris, France"], "Paris", None, None, "FR"]],
     None, [2, 3], [1790946569, 0]],
    # SYNTHETIC: US + Canada under a non-Google brand -> US location only, brand as department
    ["100000000000000001", "User Experience Design Intern, Summer 2027, YouTube UX", None, None, None,
     "projects/p/tenants/t/companies/y", None, "YouTube", "en-US",
     [["San Bruno, CA, USA", ["San Bruno, CA, USA"], "San Bruno", None, "CA", "US"],
      ["Toronto, ON, Canada", ["Toronto, ON, Canada"], "Toronto", None, "ON", "CA"]],
     None, [2, 3], [1793171396, 0]],
]
GOOGLE_HTML = (
    '<html><head><script class="ds:0" nonce="x">AF_initDataCallback({key: \'ds:0\', hash: \'1\', '
    'data:[[["projects/p/tenants/t/companies/d","DeepMind","deepmind"]]], sideChannel: {}});</script>'
    '<script class="ds:1" nonce="x">AF_initDataCallback({key: \'ds:1\', hash: \'2\', data:'
    + json.dumps([_G_JOBS, None, 85, 20])
    + ', sideChannel: {}});</script></head><body></body></html>')
GOOGLE_EMPTY = ("<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:[null,null,0,20], "
                "sideChannel: {}});</script>")

def test_google_rows_shape_and_us_filter():
    rows, total = sf.parse_google(GOOGLE_HTML)
    assert total == 85
    assert [r["title"] for r in rows] == ["Software Engineering Intern, PhD, Summer 2027",
                                          "User Experience Design Intern, Summer 2027, YouTube UX"]
    assert all(set(r) == KEYS and r["source"] == "scrapling:google" for r in rows)
    swe, yt = rows
    assert swe["url"] == "https://www.google.com/about/careers/applications/jobs/results/91436104816698054"
    assert swe["location"] == "Mountain View, CA, USA; Atlanta, GA, USA"
    assert swe["posted_at"] == "2026-08-24" and swe["department"] == ""
    assert yt["location"] == "San Bruno, CA, USA"            # Toronto dropped, or score.py rejects the row
    assert yt["department"] == "YouTube"

def test_google_empty_results_parse_to_zero_not_error():
    assert sf.parse_google(GOOGLE_EMPTY) == ([], 0)

def test_google_missing_blob_raises():
    with pytest.raises(ValueError, match="blob not found"):
        sf.parse_google("<html><body>Sorry, something went wrong</body></html>")

def test_fetch_google_raises_on_zero_rows(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, timeout=20: GOOGLE_EMPTY)
    with pytest.raises(RuntimeError, match="0 US intern rows"):
        sf.fetch_google()

def test_fetch_google_paginates_until_total(monkeypatch):
    calls = []
    def fake(url, timeout=20):
        calls.append(url)
        page = int(url.rsplit("page=", 1)[1])
        job = list(_G_JOBS[0]); job[0] = str(900 + page)
        return ("<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:"
                + json.dumps([[job], None, 3, 1]) + ", sideChannel: {}});</script>")
    monkeypatch.setattr(sf, "_http_get", fake)
    rows = sf.fetch_google()
    assert len(calls) == 3 and len(rows) == 3

# ---- Meta: CareersJobSearchResultsV2DataQuery GraphQL response --------------------------
META_PAYLOAD = json.dumps({"data": {"job_search_with_featured_jobs_v2": {
    "all_jobs": [
        {"id": "1649069223327170", "title": "Technical Program Manager Intern, Reality Labs — 2027",
         "locations": ["Sunnyvale, CA", "Seattle, WA"],
         "teams": ["University Grad - Engineering, Tech & Design"], "sub_teams": ["Program Management"]},
        {"id": "1763344164969127", "title": "Structural Design Engineer - FEA (Intern)",
         "locations": ["Sunnyvale, CA", "Redmond, WA", "Seattle, WA"],
         "teams": ["AR/VR", "Facebook Reality Labs", "Internship - Engineering, Tech & Design"],
         "sub_teams": ["Engineering", "Hardware"]},
        {"id": "1823027662342331", "title": "ASIC Engineer Intern, Physical Design",
         "locations": ["Bangalore, India"], "teams": ["Data Center", "Infrastructure"], "sub_teams": ["Hardware"]},
        # live title from the q=intern search: must NOT match \bintern\b
        {"id": "1000000000000002", "title": "Internal Audit Manager - Product, Integrity and Operations",
         "locations": ["Menlo Park, CA"], "teams": ["Finance"], "sub_teams": []},
        # SYNTHETIC: mixed US + foreign -> US locations only
        {"id": "1000000000000003", "title": " Research Scientist Intern, FAIR (PhD)",
         "locations": ["London, UK", "New York, NY"], "teams": ["AI Research"], "sub_teams": ["Research"]},
        {"id": "1649069223327170", "title": "Technical Program Manager Intern, Reality Labs — 2027",
         "locations": ["Sunnyvale, CA"], "teams": [], "sub_teams": []},   # duplicate id
    ],
    # live: the featured slot held a full-time role even under roles[0]=Internship
    "featured_jobs": [{"id": "1690022942358388", "title": "Critical Facility Engineer",
                       "locations": ["Henrico, VA"], "teams": ["Data Center"], "sub_teams": []}],
    "featured_jobs_title": "Featured Jobs", "all_jobs_title": "All Jobs"}},
    "extensions": {"is_final": True}})

def test_meta_rows_shape_and_filters():
    rows = sf.parse_meta(META_PAYLOAD)
    by_id = {r["url"].rstrip("/").rsplit("/", 1)[1]: r for r in rows}
    assert set(by_id) == {"1649069223327170", "1763344164969127", "1000000000000003"}
    assert all(set(r) == KEYS and r["source"] == "scrapling:meta" and r["company"] == "Meta" for r in rows)
    tpm = by_id["1649069223327170"]
    assert tpm["url"] == "https://www.metacareers.com/profile/job_details/1649069223327170/"
    assert tpm["location"] == "Sunnyvale, CA; Seattle, WA"
    assert tpm["department"] == "Program Management"         # level-bucket team skipped -> sub_team
    assert by_id["1763344164969127"]["department"] == "AR/VR, Facebook Reality Labs"
    mixed = by_id["1000000000000003"]
    assert mixed["location"] == "New York, NY" and mixed["title"] == "Research Scientist Intern, FAIR (PhD)"

def test_meta_accepts_parsed_dict():
    assert len(sf.parse_meta(json.loads(META_PAYLOAD))) == 3

def test_meta_wrong_payload_raises():
    with pytest.raises(ValueError, match="no all_jobs"):
        sf.parse_meta('{"data":{"job_search_filters":{"roles":["Internship"]}}}')

class _Xhr:
    def __init__(self, body): self.body = body.encode()

class _Page:
    def __init__(self, status, xhrs): self.status, self.captured_xhr = status, xhrs

def test_fetch_meta_uses_captured_graphql(monkeypatch):
    monkeypatch.setattr(sf, "_stealth", lambda url, **kw: _Page(200, [
        _Xhr('{"data":{"job_search_with_featured_jobs_v2":{"job_count":125}}}'), _Xhr(META_PAYLOAD)]))
    assert len(sf.fetch_meta()) == 3

def test_fetch_meta_raises_when_payload_missing(monkeypatch):
    monkeypatch.setattr(sf, "_stealth", lambda url, **kw: _Page(200, []))
    with pytest.raises(RuntimeError, match="not among 0 captured"):
        sf.fetch_meta()

def test_fetch_meta_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(sf, "_stealth", lambda url, **kw: _Page(400, []))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        sf.fetch_meta()

# ---- contract: one broken site never stops the others ----------------------------------
def test_fetch_all_isolates_failures(monkeypatch):
    ok = {"company": "Apple", "title": "Intern", "location": "", "url": "u", "department": "",
          "posted_at": "", "source": "scrapling:apple"}
    def boom():
        raise RuntimeError("results payload not among 0 captured /graphql responses")
    monkeypatch.setattr(sf, "fetch_apple", lambda: [ok])
    monkeypatch.setattr(sf, "fetch_google", lambda: [dict(ok, company="Google")])
    monkeypatch.setattr(sf, "fetch_meta", boom)
    rows, errors = sf.fetch_all_scrapling()
    assert [r["company"] for r in rows] == ["Apple", "Google"]
    assert errors == ["meta: RuntimeError: results payload not among 0 captured /graphql responses"]
