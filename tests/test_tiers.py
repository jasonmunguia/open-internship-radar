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


# ---- subsidiaries named in the company string inherit the parent's caliber (2026-09-30) ----

from radar import tiers


def test_explicit_parent_forms():
    assert tiers.explicit_parent("Solar Turbines (Caterpillar)") == "Caterpillar"
    assert tiers.explicit_parent("Allergan Aesthetics, an AbbVie Company") == "AbbVie"
    assert tiers.explicit_parent("Progress Rail, A Caterpillar Company") == "Caterpillar"
    assert tiers.explicit_parent("Acme Robotics, a subsidiary of Globex") == "Globex"
    # a parenthetical that is the name's own acronym, a location, or a rename is not a parent
    for company in ("Boston Consulting Group (BCG)", "Central Intelligence Agency (CIA)",
                    "Acme (Remote)", "Acme (US)", "Initech (formerly Initrode)",
                    "Mercedes-Benz in the UK", "The Walt Disney Company", "Caterpillar Inc."):
        assert tiers.explicit_parent(company) is None, company


def _cache(**entries):
    return {k: {"company": k, "band": b, "needs_resolution": b is None}
            for k, b in entries.items()}


def test_subsidiary_takes_better_parent_band():
    cache = _cache(allerganaesthetics=3, abbvie=2)
    b, _pts, src = tiers.band_for("Allergan Aesthetics, an AbbVie Company", {}, cache=cache)
    assert (b, src) == (2, "parent:cache")


def test_subsidiary_keeps_own_band_when_better():
    """Best of the two, never worse: a parent measured lower never drags a child down."""
    cache = _cache(globexlabs=1, initech=3)
    b, _pts, _src = tiers.band_for("Globex Labs (Initech)", {}, cache=cache)
    assert b == 1


def test_bare_name_finds_legal_form_entry():
    """'Caterpillar' sat unresolved while 'Caterpillar Inc.' was measured T2 — same company,
    two cache keys. The bare name now falls through to the legal-form key."""
    cache = _cache(caterpillar=None, caterpillarinc=2)
    assert tiers.band_for("Caterpillar", {}, cache=cache)[0] == 2
    assert tiers.band_for("Solar Turbines (Caterpillar)", {}, cache=cache)[0] == 2


def test_unknown_parent_changes_nothing():
    b, _pts, src = tiers.band_for("Nobody Co (Nothing Corp)", {}, cache={})
    assert (b, src) == (4, "pending")


def test_priority_jumps_the_slug_queue(monkeypatch, tmp_path):
    cache_path = tmp_path / "company_tiers.json"
    import json as _json
    entries = {f"tail{i}": {"company": f"Tail {i}", "band": 4, "needs_resolution": True}
               for i in range(30)}
    entries["caterpillar"] = {"company": "Caterpillar", "band": 4, "needs_resolution": True}
    cache_path.write_text(_json.dumps(entries))
    monkeypatch.setattr(tiers, "CACHE", str(cache_path))
    seen = {}

    class _Out:
        stdout = "{}"

    def fake_joint(name, prompt, timeout=None):
        seen["prompt"] = prompt
        return _Out()
    import radar.joints
    monkeypatch.setattr(radar.joints, "run_joint", fake_joint)
    tiers.resolve_unresolved_with_claude(limit=5, priority=["Caterpillar", "Tail 29"])
    names = seen["prompt"].split("COMPANIES:\n", 1)[1].splitlines()
    assert names[:2] == ["Caterpillar", "Tail 29"]     # prioritized, in priority order
    assert names[2:] == ["Tail 0", "Tail 1", "Tail 2"]  # the rest keep cache order
