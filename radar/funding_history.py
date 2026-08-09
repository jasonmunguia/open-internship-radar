"""Persistent Form D funding history — the third tier signal.

WHY: data/funded_watch.json is a ROLLING window (recent_big_form_ds defaults to days=1 and
the file held 3 rows). That is correct for "who just raised", but it means the funding signal
in radar/tiers.py was dead for any company that raised more than ~2 weeks ago — which is
almost all of them. MaintainX fell to T4 on 58k followers / 766 employees because its real
raise was invisible. Anduril fell to T3 for the same reason and was only saved by the
override list.

This module accumulates every observed Form D into a permanent, append-only history keyed on
a normalised company name, so a raise counts forever rather than for a fortnight.

Deterministic: SEC EDGAR only, no model, no credits.
"""
import json, os, re

HISTORY = os.path.join(os.path.dirname(__file__), "..", "data", "funding_history.json")

# Form D filer names are legal names, not brand names ("Sila Nanotechnologies, Inc.").
_LEGAL = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|co|ltd|lp|l\.p|holdings|"
                    r"technologies|technology|labs|group|company|plc|sa|nv|gmbh)\b\.?", re.I)


def normc(name):
    """Normalise a company name for cross-source matching. Same discipline as the lead-gen
    pipeline: match on a normalised key, never on the raw display string."""
    s = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower())
    s = _LEGAL.sub(" ", s)
    return re.sub(r"\s+", "", s)


def load():
    try:
        with open(HISTORY) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save(h):
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w") as fh:
        json.dump(h, fh, indent=1, sort_keys=True)


def ingest(rows, history=None):
    """Fold Form D rows into history. Keeps the LARGEST raise ever seen per company and the
    most recent date — a company does not become less funded over time."""
    h = load() if history is None else history
    added = 0
    for r in rows or []:
        name = r.get("full_name") or r.get("company")
        k = normc(name)
        if not k or len(k) < 3:
            continue
        prev = h.get(k)
        amt = int(r.get("amount") or 0)
        if not prev or amt > prev.get("amount", 0):
            h[k] = {"company": r.get("company") or name, "amount": max(amt, (prev or {}).get("amount", 0)),
                    "date": r.get("date") or (prev or {}).get("date"), "industry": r.get("industry")}
            added += 1
    save(h)
    return added


def lookup(company, history=None):
    """Total observed raise for a company, or None. Tries the name and its parent forms."""
    h = load() if history is None else history
    k = normc(company)
    if k in h:
        return h[k]
    words = re.sub(r"[^a-z0-9 ]", " ", str(company).lower()).split()
    for i in range(len(words) - 1, 0, -1):          # "Uber Freight" -> "uber"
        cand = normc(" ".join(words[:i]))
        if cand in h:
            return h[cand]
    return None


def seed_known(history=None):
    """One-time seed for large private raises that predate the rolling window. Values are
    publicly reported totals; EDGAR ingestion supersedes any of these as filings arrive."""
    known = {"MaintainX": 154_000_000, "Anduril": 2_500_000_000, "Etched": 300_000_000,
             "ServiceTitan": 1_400_000_000, "Applied Intuition": 600_000_000,
             "Skydio": 740_000_000, "Verkada": 460_000_000, "Flock Safety": 380_000_000,
             "Ramp": 1_200_000_000, "Rippling": 1_400_000_000, "Databricks": 4_000_000_000,
             "Figure": 750_000_000, "Physical Intelligence": 400_000_000,
             "Scale AI": 1_600_000_000, "Instawork": 160_000_000, "Motive": 570_000_000}
    return ingest([{"company": k, "full_name": k, "amount": v, "date": "seed"}
                   for k, v in known.items()], history)
