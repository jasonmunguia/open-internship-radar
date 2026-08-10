"""Observed ground truth for the release calendar — NEXT.md item 8b (spec item 21).

The calendar's expected_open dates are ESTIMATES refreshed nightly by re-researching the
web. But the system also observes reality it used to throw away: when a req from a
calendared program actually lands in the queue, that IS the open date for this cycle.
This module records those observations and feeds them to the calendar joint as evidence
that outweighs prose — "last cycle this posted August 14" beats a model's "mid-August".

Deterministic spine: no model here. The calendar JOINT consumes the evidence.
"""
import json, os, re, time
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBSERVED = os.path.join(ROOT, "data", "observed_opens.jsonl")

# Queue rows are already family+tier gated, so a matching COMPANY plus an intern-shaped
# TITLE is program evidence. The title filter exists to exclude full-time postings from
# calendared companies (Anduril "International Deployment Manager" is not a program open).
_TITLE = re.compile(r"intern|co-?op|fellow|\bapm\b|launch", re.I)


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _company_matches(cal_key, row_key):
    """Exact match, or longer-starts-with-shorter for keys of >=5 chars. Substring
    matching is NOT enough: 'cia' sits inside other company names and 'dia'/'nsa'/'meta'
    likewise, which produced 14 phantom program matches (CIA "Quantitative Trading",
    DIA "Advertising Sales") on this matcher's very first probe, 2026-08-09. Short
    agency keys (CIA, DIA, NSA, NGA, BCG) therefore match exactly or not at all."""
    if not cal_key or not row_key:
        return False
    if cal_key == row_key:
        return True
    short, long_ = sorted((cal_key, row_key), key=len)
    return len(short) >= 5 and long_.startswith(short)


def capture(queue_path=None, cal_path=None, out_path=None):
    """Scan the queue for postings that ARE a calendared program opening; append the new
    ones to data/observed_opens.jsonl (dedup: program+url). Returns {matched, new} and
    the nightly logs it — a matcher stuck at 0 against a queue that plainly holds SpaceX
    and Amazon intern reqs must look broken, not quiet."""
    import yaml
    queue_path = queue_path or os.path.join(ROOT, "data", "queue.jsonl")
    cal_path = cal_path or os.path.join(ROOT, "config", "release_calendar.yaml")
    out_path = out_path or OBSERVED
    cal = yaml.safe_load(open(cal_path)) or []
    programs = [(e["program"], _key(e.get("company", ""))) for e in cal if e.get("company")]
    seen = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                d = json.loads(line)
                seen.add((d.get("program"), d.get("url")))
            except Exception:
                continue
    matched = new = 0
    if not os.path.exists(queue_path):
        return {"matched": 0, "new": 0}
    with open(out_path, "a") as out:
        for line in open(queue_path):
            try:
                r = json.loads(line)
            except Exception:
                continue
            rk = _key(r.get("company", ""))
            title = r.get("title", "")
            if not _TITLE.search(title):
                continue
            for prog, ck in programs:
                if _company_matches(ck, rk):
                    matched += 1
                    if (prog, r.get("url")) in seen:
                        continue
                    # posted_at must be a real ISO date — boards also emit junk like a
                    # bare "September", which would pollute the evidence AND win the
                    # reverse-date sort ("S" > "2"). Non-ISO falls back to first_seen.
                    posted = str(r.get("posted_at") or "")[:10]
                    try:
                        date.fromisoformat(posted)
                    except ValueError:
                        posted = ""
                    obs = {"program": prog, "company": r.get("company", ""),
                           "title": title, "url": r.get("url", ""),
                           "date": posted or datetime.fromtimestamp(
                               r.get("ts", time.time())).date().isoformat(),
                           # posted_at is the board's own date (strong); first_seen is
                           # when the poller found it (an upper bound on the open date)
                           "date_kind": "posted_at" if posted else "first_seen",
                           "recorded": date.today().isoformat()}
                    out.write(json.dumps(obs) + "\n")
                    seen.add((prog, r.get("url")))
                    new += 1
    return {"matched": matched, "new": new}


def evidence_block(path=None, per_program=3):
    """The ground-truth section for the calendar joint's prompt. Empty string when
    nothing has been observed yet — the prompt then carries no section at all
    (absent-means-off, same rule as angles)."""
    path = path or OBSERVED
    if not os.path.exists(path):
        return ""
    by_prog = {}
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        by_prog.setdefault(d["program"], []).append(d)
    if not by_prog:
        return ""
    lines = ["OBSERVED GROUND TRUTH — real postings this system has already seen from the",
             "calendared programs. A date here is what ACTUALLY happened and outweighs any",
             "web estimate: if a program below posted this cycle, set expected_open from it",
             "(and say observed in deadline_behavior); for annual programs, project the",
             "next cycle from the observed date.", ""]
    for prog in sorted(by_prog):
        rows = sorted(by_prog[prog], key=lambda d: d.get("date", ""), reverse=True)[:per_program]
        lines.append(f"- {prog}:")
        for d in rows:
            lines.append(f"    {d['date']} ({d['date_kind']}): {d['title'][:70]} — {d['url']}")
    return "\n".join(lines)
