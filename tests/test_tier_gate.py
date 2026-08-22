"""Regression tests for the digest tier gate (added 2026-08-22 per the operator).

The bug this guards against: queue.jsonl keeps each row's ingest-time score forever,
so rows scored under retired rules (unknown tier once earned +10) resurfaced at 58 —
a score unreachable under current arithmetic — and unknown-company jobright rows
(Fifth Wheel Freight, Sweety High Media, HUB Sports Boston) shipped in the apply
email for weeks. The rule now: every apply recommendation is T1-T3 (or freshly
funded); unknown/T4 rows are quarantined for a live resolution pass and NEVER ship
unverified, no matter what score the queue file claims.

Run locally:  python3 -m pytest tests/test_tier_gate.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml

from radar.digest import DISPLAY_FLOOR, PASSING_TIERS, rescore_and_partition
from radar.tiers import _key

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _profile():
    for name in ("profile.yaml", "profile.example.yaml"):
        p = os.path.join(_ROOT, "config", name)
        if os.path.exists(p):
            return yaml.safe_load(open(p))
    raise RuntimeError("no profile config found")


def _row(company, title="Product Management Intern", score=None):
    r = {"company": company, "title": title, "location": "New York, NY",
         "url": f"https://example.com/{company}", "source": "github:jobright-ai/test",
         "department": ""}
    if score is not None:
        r["score"] = score   # stale ingest-time score — the gate must ignore it
    return r


def test_stale_score_cannot_ship_unknown_company():
    """A queue row claiming 99 at an unknown company must land in unverified, re-scored."""
    profile = _profile()
    rows = [_row("Zephyr Widget Chums LLC", score=99)]
    passing, unverified = rescore_and_partition(rows, profile, funded={}, tier_cache={})
    assert passing == []
    assert len(unverified) == 1
    assert unverified[0]["score"] < 99          # stale score was replaced, not trusted
    assert unverified[0]["tier"] not in PASSING_TIERS


def test_cached_t2_company_passes():
    cache = {_key("AcmeCorp"): {"company": "AcmeCorp", "band": 2, "needs_resolution": False}}
    passing, unverified = rescore_and_partition([_row("AcmeCorp")], _profile(), {}, cache)
    assert len(passing) == 1 and unverified == []
    assert passing[0]["tier"] == "T2"
    assert passing[0]["score"] >= DISPLAY_FLOOR


def test_measured_t4_company_is_quarantined():
    """Measured T4 is still below the bar — quarantined with the unknowns, never shipped."""
    cache = {_key("Tiny Shop"): {"company": "Tiny Shop", "band": 4, "needs_resolution": False}}
    passing, unverified = rescore_and_partition([_row("Tiny Shop")], _profile(), {}, cache)
    assert passing == []
    assert len(unverified) == 1


def test_unknown_at_family_weight_is_kept_for_resolution():
    """40 (family) + best-case T1 (40) clears the floor, so the row must reach the
    resolver instead of being dropped on its current 40."""
    passing, unverified = rescore_and_partition([_row("Mystery Robotics")], _profile(), {}, {})
    assert passing == []
    assert len(unverified) == 1


def test_gated_out_title_is_dropped_entirely():
    """A row failing the family gate (no cluster match) is dropped, not quarantined."""
    rows = [_row("AcmeCorp", title="Senior Staff Accountant")]
    cache = {_key("AcmeCorp"): {"company": "AcmeCorp", "band": 1, "needs_resolution": False}}
    passing, unverified = rescore_and_partition(rows, _profile(), {}, cache)
    assert passing == [] and unverified == []
