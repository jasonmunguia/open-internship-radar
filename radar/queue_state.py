"""Apply-queue state — the difference between a feed and a list you work to zero.

Before this, the digest was a rolling 14-day window with no memory: a role appeared every
morning for 14 days whether or not the operator had applied, then vanished whether or not he had.
Both failure modes he named — "some get shown multiple times, some get lost" — came from
the same missing piece: no per-role state.

States: new -> shown(day N) -> applied. A row leaves the list ONLY when tapped. Nothing
ages out on its own; the day counter is the pressure instead.
"""
import hashlib, json, os
from datetime import date, datetime

APPLIED = os.path.join(os.path.dirname(__file__), "..", "data", "applied.jsonl")
SHOWN = os.path.join(os.path.dirname(__file__), "..", "data", "shown.json")


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
