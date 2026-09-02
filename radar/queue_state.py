"""Apply-queue state — the difference between a feed and a list you work to zero.

Before this, the digest was a rolling 14-day window with no memory: a role appeared every
morning for 14 days whether or not the operator had applied, then vanished whether or not he had.
Both failure modes he named — "some get shown multiple times, some get lost" — came from
the same missing piece: no per-role state.

States: new -> shown(day N) -> applied. A row leaves the list ONLY when tapped. Nothing
ages out on its own; the day counter is the pressure instead.
"""
import hashlib
import json
import os
import re
from datetime import date, datetime

APPLIED = os.path.join(os.path.dirname(__file__), "..", "data", "applied.jsonl")
SHOWN = os.path.join(os.path.dirname(__file__), "..", "data", "shown.json")
FEEDBACK = os.path.join(os.path.dirname(__file__), "..", "data", "feedback.jsonl")


def job_id(row):
    """Stable across sources: the same req arriving from six boards must collapse to one id,
    so the URL is preferred and company+title is the fallback."""
    basis = (row.get("url") or "").strip().lower() or \
            f"{row.get('company','').lower()}|{row.get('title','').lower()}"
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def _read_jsonl(path):
    try:
        with open(path) as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except Exception:
        return []


def acted_ids(action=None):
    """Ids the operator has tapped. `undo` re-opens a row, so replay in order and let the last
    action win — a mis-tap must be recoverable."""
    state = {}
    for r in _read_jsonl(APPLIED):
        state[r.get("job_id")] = r.get("action")
    return {k for k, v in state.items() if v not in (None, "undo") and (action is None or v == action)}


def verdicts():
    """job_id -> "yes"/"no" from the 👍/👎 taps. Replayed in file order, last verdict
    wins — the flip link on the relay's confirmation page is the mis-tap recovery, so
    a later tap must supersede an earlier one. A "no" hides the row from the digest;
    a "yes" only marks it. Both feed the weekly pattern analysis."""
    state = {}
    for r in _read_jsonl(FEEDBACK):
        if r.get("action") in ("yes", "no") and r.get("job_id"):
            state[r["job_id"]] = r["action"]
    return state


def load_shown():
    try:
        with open(SHOWN) as fh:
            return json.load(fh)
    except Exception:
        return {}


def mark_shown(rows, shown=None):
    """First-seen date per row, which is what the 'day N' counter counts from."""
    shown = load_shown() if shown is None else shown
    today = date.today().isoformat()
    for r in rows:
        jid = job_id(r)
        if jid not in shown:
            # First sighting -> archive it. Rows outlive their postings by design (nothing
            # expires on age), so without a snapshot a pulled req becomes an unreadable 404.
            try:
                from radar.archive import snapshot
                snapshot(r.get("url", ""))
            except Exception:
                pass
        shown.setdefault(jid, today)
    os.makedirs(os.path.dirname(SHOWN), exist_ok=True)
    with open(SHOWN, "w") as fh:
        json.dump(shown, fh, indent=1, sort_keys=True)
    return shown


def days_shown(row, shown):
    try:
        return (date.today() - date.fromisoformat(shown[job_id(row)])).days
    except Exception:
        return 0


def bucket(row):
    """Chronological grouping by when the role was POSTED, not when we noticed it."""
    raw = row.get("posted_at") or ""
    try:
        d = datetime.fromisoformat(str(raw)[:10]).date()
    except Exception:
        ts = row.get("ts")
        d = datetime.fromtimestamp(ts).date() if ts else date.today()
    age = (date.today() - d).days
    if age <= 0:
        return "Today"
    if age <= 7:
        return "This week"
    if age <= 14:
        return "Last week"
    return "This month"


BUCKET_ORDER = ["Today", "This week", "Last week", "This month"]


def relay(url, row, base, action="applied", override_id=None):
    """Wrap a destination in the click relay so a tap is recorded. Falls back to the raw URL
    if the relay isn't configured yet — a missing env var must not produce dead links."""
    from urllib.parse import quote
    if not base:
        return url
    jid = override_id or job_id(row)
    return f"{base.rstrip('/')}/api/a?j={jid}&k={action}&u={quote(url or '', safe='')}"


def program_id(program):
    """Stable id for a release-calendar program, so 'networked' state keys the same way
    postings do and both live in one file."""
    return "prog-" + hashlib.sha1(str(program).lower().encode()).hexdigest()[:10]


def people_search_url(company):
    """LinkedIn people search pre-filtered to the roles the operator is targeting. Deliberately a
    PLAIN link, never relayed: he taps this repeatedly while networking and it must not clear
    the row. Only the explicit 'done' link does that."""
    from urllib.parse import quote
    q = (f'{company} ("Product Manager Intern" OR "APM Intern" OR "Product Management Intern" '
         f'OR "Business Analyst Intern" OR "Strategy Intern" OR "Chief of Staff")')
    return f"https://www.linkedin.com/search/results/people/?keywords={quote(q)}"


# ---- role families (2026-09-02): a tap clears the ROLE, not the URL it was tapped from ----
#
# job_id() is per-URL by construction (the ledger and shown.json are keyed on it, so it
# cannot change). But the same requisition reaches the queue from jobright, Simplify,
# speedrun, GitHub lists AND the company's own page, each with its own URL — so only the
# tapped copy ever left the list. Three shapes a twin can wear, checked in order of strength:
#   1. the exact id (unchanged behaviour)
#   2. the ATS requisition id parsed out of the URL — host-independent, survives mirrors
#   3. normalised company + title, with the term/season split out so "PM Intern (Summer
#      2027)" hides "PM Intern" and "PM Intern 2027" but NOT "PM Intern (Fall 2026)"

_REQ = (
    ("gh",   re.compile(r"[?&](?:gh_jid|token)=(\d+)")),
    ("gh",   re.compile(r"greenhouse\.io/[^/?#]+/jobs/(\d+)")),
    ("uuid", re.compile(r"(?:ashbyhq\.com|lever\.co)/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")),
    ("wd",   re.compile(r"myworkdayjobs\.com/.*_((?:jr|r)?\d{4,})(?=[/?#]|$)")),
    ("sr",   re.compile(r"smartrecruiters\.com/[^/]+/(\d{10,})")),
    ("job",  re.compile(r"/job/(\d{6,})(?=[/?#]|$)")),          # Oracle CX + careers.* mirrors
)

def req_id(url):
    """Requisition id from an ATS URL, prefixed by ATS family so numeric spaces can't
    collide. None for aggregators whose ids are per-listing (jobright) and for no-URL rows."""
    u = (url or "").strip().lower()
    if not u.startswith("http"):
        return None
    for kind, rx in _REQ:
        m = rx.search(u)
        if m:
            return f"{kind}:{m.group(1)}"
    return None


_TERM = re.compile(r"\b(summer|fall|autumn|winter|spring|20[2-3]\d)\b")

def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()

def role_key(row):
    """(company, title-without-terms, terms). Emoji, punctuation and case are noise;
    the term tokens are kept aside because they ARE the difference between two reqs."""
    co = _norm(row.get("company"))
    t = _norm(row.get("title"))
    terms = frozenset(_TERM.findall(t))
    core = re.sub(r"\s+", " ", _TERM.sub(" ", t)).strip()
    return co, core, terms


def done_state(rows, ids=None):
    """Everything a tap has cleared, in all three shapes. `rows` is the full queue (a
    tapped id resolves to its company/title only through the row that carries it);
    the ledger's own URL covers taps whose row has since left the queue."""
    ids = set(acted_ids()) if ids is None else set(ids)
    reqs, keys = set(), {}
    urls = {}
    for r in _read_jsonl(APPLIED):
        urls[r.get("job_id")] = r.get("url", "")
    for jid in ids:
        rid = req_id(urls.get(jid, ""))
        if rid:
            reqs.add(rid)
    for r in rows:
        if job_id(r) not in ids:
            continue
        rid = req_id(r.get("url", ""))
        if rid:
            reqs.add(rid)
        co, core, terms = role_key(r)
        if co and core:
            keys.setdefault((co, core), []).append(terms)
    return {"ids": ids, "reqs": reqs, "keys": keys}


def is_done(row, done):
    if job_id(row) in done["ids"]:
        return True
    rid = req_id(row.get("url", ""))
    if rid and rid in done["reqs"]:
        return True
    co, core, terms = role_key(row)
    if not (co and core):
        return False
    for t in done["keys"].get((co, core), ()):
        if t <= terms or terms <= t:    # one term set contains the other (or is empty)
            return True
    return False
