"""Every apply-list row carries a 'find people' link to FULL-TIME holders of the role.

2026-09-30 (the operator): the pre-network email only covers programs on the release calendar,
so most postings never got a referral path. The apply list now links each row to a
LinkedIn search for people doing that job full-time at that company — not other interns.
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import queue_state as qs  # noqa: E402


def _kw(url):
    u = urlparse(url)
    assert u.netloc == "www.linkedin.com" and u.path == "/search/results/people/"
    return parse_qs(u.query)["keywords"][0]


def test_family_titles_are_full_time():
    kw = _kw(qs.ft_people_search_url("Anduril", "product", "Product Manager Intern (Summer 2027)"))
    assert kw.startswith("Anduril (")
    assert '"Product Manager"' in kw
    assert "intern" not in kw.lower()


def test_every_family_has_titles_and_none_are_intern_titles():
    for fam, titles in qs.FT_TITLES.items():
        assert titles, fam
        for t in titles:
            assert "intern" not in t.lower(), (fam, t)


def test_unknown_family_falls_back_to_stripped_title():
    kw = _kw(qs.ft_people_search_url("SpaceX", "dream-company-general",
                                     "Summer 2027 Intern - Starlink Business Operations"))
    assert kw == 'SpaceX ("Starlink Business Operations")'


def test_posting_title_leads_then_family_widens_without_duplicates():
    kw = _kw(qs.ft_people_search_url("ByteDance", "ops_supply",
                                     "AI Creator Operations Intern (CapCut)"))
    assert kw.startswith('ByteDance ("AI Creator Operations" OR "Program Manager"')
    kw = _kw(qs.ft_people_search_url("Anduril", "product", "Product Manager Intern"))
    assert kw.count('"Product Manager"') == 1


def test_program_names_are_not_treated_as_job_titles():
    assert qs.title_core("Engineering Technical Fellow Solid Rocket Motors Program") == ""
    assert qs.title_core("Deployment Strategist, Internship - US Government") == "Deployment Strategist"
    assert qs.title_core("Special Projects Intern [Fall 2026]") == "Special Projects"


def test_title_that_is_all_noise_searches_company_only():
    assert _kw(qs.ft_people_search_url("Palantir", "", "Intern (Summer 2027)")) == "Palantir"


def test_url_is_safe_inside_a_single_quoted_href():
    url = qs.ft_people_search_url("Moody's & Co", "consulting", "")
    assert "'" not in url and " " not in url and "&" not in url.split("?", 1)[1]


def test_badge_glyphs_and_parentheticals_are_stripped_from_company():
    assert _kw(qs.ft_people_search_url("Bosch ✓", "", "")) == "Bosch"
    assert _kw(qs.ft_people_search_url("LLNL 🆁", "", "")) == "LLNL"
    assert _kw(qs.ft_people_search_url("Regional Finance (Regional Management Corp.)", "", "")) \
        == "Regional Finance"
