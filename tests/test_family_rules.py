"""Per-family content exclusions (2026-09-30, from learning check-in LRN-20260823).

A cluster may carve content OUT of itself with `exclude`, with `exempt_industries` /
`exempt_patterns` as the escape hatch: supply-chain roles at a grocery chain and at a
rocket company share a title and are different seats. The mechanism is tested on a
synthetic profile (runs anywhere); the operator's real rules are tested against his
real tap evidence when config/profile.yaml exists (skipped in a fresh clone).

Run locally:  python3 -m pytest tests/test_family_rules.py -q
"""
import os
import sys

import pytest
import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from radar.score import score_posting  # noqa: E402

SYNTH = {
    "clusters": {
        "consulting": {"weight": 40, "angle": "consulting", "patterns": ["consult"],
                       "exclude": ["\\btax\\b"]},
        "product": {"weight": 40, "angle": "product", "patterns": ["product manage"]},
        "ops": {"weight": 40, "angle": "ops", "patterns": ["supply chain"],
                "exclude": ["supply chain"], "exempt_industries": ["space"],
                "exempt_patterns": ["robot"]},
    },
    "industries": {"space": ["rocketco"]},
    "tiers": {}, "bonus_keywords": [], "offcycle_patterns": [],
    "scoring": {"gate_patterns": ["\\bintern\\b"], "exclude_patterns": []},
}


def family(title, company="Acme", description="", profile=SYNTH):
    s, brief = score_posting({"company": company, "title": title, "location": "",
                              "source": "", "description": description},
                             profile, tier_cache={})
    return brief["cluster"] if brief else None


def test_exclude_blocks_the_family():
    assert family("Consulting Intern") == "consulting"
    assert family("Tax Consulting Intern") is None


def test_exclude_also_blocks_the_description_fallback():
    """The half-weight description match must not readmit a title the family refused."""
    assert family("Tax Intern", description="join our consulting practice") is None


def test_other_family_still_claims_the_title():
    assert family("Tax Product Manager Intern") == "product"


def test_exemptions():
    assert family("Supply Chain Intern", company="GroceryCo") is None
    assert family("Supply Chain Intern", company="RocketCo") == "ops"          # industry
    assert family("Supply Chain Intern, Robotics", company="BigBox") == "ops"  # pattern


# ---- the operator's real rules vs his real verdicts ----

_REAL = os.path.join(_ROOT, "config", "profile.yaml")
real = pytest.mark.skipif(not os.path.exists(_REAL), reason="radar not configured")

SHIPS = [  # yes-taps, applied taps, and protected PwC titles
    ("Boeing", "Boeing Summer 2027 Internship Program (Paid) - Supply Chain"),
    ("Varda Space", "Supply Chain Internship - Spring 2027"),
    ("Rocket Lab", "Supply Chain Intern Fall 2026"),
    ("Divergent", "Summer 2027 Supply Chain Intern"),
    ("Amazon", "Supply Chain Manager Intern/Co-op, ROBOTICS - 2027"),
    ("Hermeus", "Supply Chain Intern - Spring/Summer 2027"),
    ("Skydio", "Hardware Product Management Intern"),
    ("PwC", "Strategy& Strategy Consulting Intern - Summer 2027"),
    ("PwC", "Business Process Consulting Intern - Summer 2027"),
    ("PwC", "Management Consulting - Operations & Supply Chain Solutions Intern - Summer 2027"),
    ("PwC", "Tax Innovation Delivery Experience (TIDE) - Product Management - Intern - Summer 2027"),
    ("Capital One", "Business Analyst Intern - Summer 2027"),
    ("Databricks", "Product Management Intern"),
]
DROPS = [  # no-taps the check-in patterns were built from
    ("Kroger", "Supply Chain Intern - Summer 2027"),
    ("Uline", "Logistics Operations Internship - Summer"),
    ("Sysco", "Warehouse Operations Intern"),
    ("Walmart", "2027 Inventory Operations Intern"),
    ("Microsoft", "Construction Project Management INTERN (Internship Opportunities for US - West region)"),
    ("PwC", "Risk Consulting Intern - Summer 2027"),
    ("PwC", "Legal, Regulatory & Compliance Consulting Intern - Summer 2027"),
    ("Plante Moran", "2027 Business Valuation Consultant Intern"),
    ("Withum", "Tax Valuation Consulting Spring Internship 2027"),
    ("RSM US LLP", "Enterprise Data Integration and Migration Consulting Intern - Summer 2027"),
    ("Figure AI", "Hardware Reliability Intern [Fall 2026]"),
    ("Base Power", "Hardware Technical Program Management Intern"),
    ("Qorvo", "Product Management Engineering Intern"),
    ("Etched", "Electrical Platform Intern"),
    ("Google", "Data Scientist, Product Intern, MS, Summer 2027"),
    ("AbbVie", "2027 Business Technology Solutions Intern - Cybersecurity (Undergraduate)"),
    ("Amazon", "Industrial Development Engineer Intern/Co-op, ROBOTICS - 2027"),
    ("Morningstar", "Morningstar Internship Program – Sales Intern 2027 (Campus)"),
    ("Celonis", "Intern Business Development (French-Speaking)"),
]


@real
@pytest.mark.parametrize("company,title", SHIPS)
def test_real_rules_keep(company, title):
    assert family(title, company, profile=yaml.safe_load(open(_REAL))) is not None


@real
@pytest.mark.parametrize("company,title", DROPS)
def test_real_rules_drop(company, title):
    assert family(title, company, profile=yaml.safe_load(open(_REAL))) is None
