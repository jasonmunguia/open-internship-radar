"""Regression tests for tier-override name matching.

2026-08-15: 'First Wisconsin Financial Inc' (2-person mortgage shop) alerted as T1/score-80
because 'cia' in the dream list substring-matched Finan-CIA-l. 60 of 704 queued companies
had the same false match ('cia' in Association/Social, 'meta' in Metals, 'stripe' in
PlainStripes). name_match() requires word boundaries.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radar.tiers import name_match, override_band

PROFILE = {"tiers": {"dream": ["cia", "meta", "stripe", "scale ai", "in-q-tel", "8vc"],
                     "target": ["mckinsey"]}}


def test_no_midword_false_positives():
    for company in ("First Wisconsin Financial Inc", "American Heart Association",
                    "The Social Fleur", "AA Metals, Inc", "Metallus Inc.",
                    "PlainStripes", "Faurecia", "Acadium"):
        assert override_band(company, PROFILE) is None, company


def test_real_names_still_match():
    assert override_band("CIA", PROFILE) == 1
    assert override_band("Central Intelligence Agency (CIA)", PROFILE) == 1
    assert override_band("Meta Platforms", PROFILE) == 1
    assert override_band("Stripe, Inc.", PROFILE) == 1
    assert override_band("Scale AI", PROFILE) == 1
    assert override_band("In-Q-Tel", PROFILE) == 1
    assert override_band("8VC", PROFILE) == 1
    assert override_band("McKinsey & Company", PROFILE) == 2


def test_boundary_semantics():
    assert name_match("cia", "cia headquarters")
    assert not name_match("cia", "financial")
    assert not name_match("8vc", "18vc capital")
    assert name_match("meta", "meta-platforms")
