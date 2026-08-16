"""Regression tests for the eligibility gate patterns in config/profile.yaml.

The bug this guards against (found 2026-08-14): a bare "intern" gate pattern is a
substring regex, so it matched inside "internAtional" and "internAl" — any posting
whose title or description mentioned "international" sailed through the intern gate
and landed in the operator's inbox. The gate must match intern/interns/internship(s) as
whole words and NOTHING longer.

Cluster patterns ending in "... intern" had the same class of bug ("solutions intern"
matched "solutions international"), so those are checked too.

Run locally:  python3 -m tests.test_gate_patterns
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml
from radar.score import _any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Loads config/profile.yaml if the radar is configured, else the shipped example — so
# this guard runs in a fresh clone too, where only the example exists.
_PROFILE = os.path.join(_ROOT, "config", "profile.yaml")
if not os.path.exists(_PROFILE):
    _PROFILE = os.path.join(_ROOT, "config", "profile.example.yaml")

# titles/text the gate MUST still pass (real early-career postings)
MUST_PASS = [
    "Product Manager Intern",
    "Business Operations Internship - Summer 2027",
    "Strategy & Operations Intern (Summer 2027)",
    "2027 Summer Internships — Business Analyst",
    "Interns, Corporate Strategy",
    "intern",                      # bare lowercase, start/end of string
    "Co-op, Supply Chain",
    "Undergraduate Fellow",
]

# titles/text the gate MUST reject (the "international" false-positive class)
MUST_REJECT = [
    "International Sales Manager",
    "Director, International Expansion",
    "Internal Audit Associate",
    "Senior Internal Communications Lead",
    "Business Development Manager - International Markets",
    "Account Executive (internationally distributed team)",
    "Internationalization Engineer",
]

# cluster patterns ending in "intern" must not fire on "... international ..."
CLUSTER_MUST_REJECT = [
    "We deliver solutions internationally to enterprise clients",
    "Drive sales international growth across EMEA",
    "Own product international rollout strategy",
    "Operations International Program Lead",
]
CLUSTER_MUST_PASS = [
    "Solutions Intern",
    "Product Internship",
    "Operations Interns - Summer",
    "Sales Intern",
]


def main():
    profile = yaml.safe_load(open(_PROFILE))
    gates = profile["scoring"]["gate_patterns"]
    cluster_pats = [p for c in profile["clusters"].values() for p in c["patterns"]
                    if "intern" in p]

    failures = []
    for t in MUST_PASS:
        if not _any(gates, t):
            failures.append(f"gate WRONGLY REJECTED a real early-career title: {t!r}")
    for t in MUST_REJECT:
        if _any(gates, t):
            failures.append(f"gate WRONGLY PASSED a non-intern title: {t!r}")
    for t in CLUSTER_MUST_REJECT:
        hits = _any(cluster_pats, t)
        if hits:
            failures.append(f"cluster pattern {hits!r} WRONGLY matched: {t!r}")
    for t in CLUSTER_MUST_PASS:
        if not _any(cluster_pats, t):
            failures.append(f"cluster patterns missed a real intern title: {t!r}")

    total = len(MUST_PASS) + len(MUST_REJECT) + len(CLUSTER_MUST_REJECT) + len(CLUSTER_MUST_PASS)
    if failures:
        print(f"❌ gate patterns FAILED — {len(failures)}/{total} cases wrong:")
        for f in failures:
            print("   ", f)
        sys.exit(1)
    print(f"✅ gate patterns OK — {total}/{total} cases correct")


def test_all():
    """Pytest-visible wrapper — CI runs main() as a module step; without this,
    pytest collects ZERO tests from this file and 'pytest tests/' reports a
    passing suite that never ran these cases."""
    main()


if __name__ == "__main__":

    main()
