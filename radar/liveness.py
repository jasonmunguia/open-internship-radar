"""Liveness gate — a posting ships in the digest only if it is verifiably still open.

WHY THIS EXISTS (2026-08-22, per the operator): the queue never expires by age — rows leave
when tapped — so a role could sit for weeks, die at the source, and still be
recommended every morning. The operator tapped through a digest and found expired postings.
"Still live" is now a claim that must carry proof, checked before EVERY send: a live
verdict expires after LIVE_TTL_H hours, so no email ever leans on yesterday's check.

Three layers, cheapest first (each layer only sees what the previous could not judge):
  1. stdlib GET  — 404/410 or a self-identified closed marker -> dead; a readable page
     without one -> live; blocked (403/429/5xx), network error, or a JS shell -> unsure
  2. Scrapling StealthyFetcher renders the unsure pages (JS apps, anti-bot walls)
  3. the `liveness` Claude joint judges rendered text that still reads ambiguous

Verdicts persist in data/liveness.json: dead is PERMANENT (a closed req does not
reopen under the same URL; if it truly does, the fetchers will re-see it as a new row),
live expires after LIVE_TTL_H. Rows that end unsure are HELD out of the email and
retried tomorrow — never shipped unverified, and never deleted (a false "dead" hides
a real job, so unsure is a hold, not a verdict).
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "liveness.json")
LIVE_TTL_H = 20                     # a live verdict is good for one send cycle, not two
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# A page that says any of these about ITSELF is dead. Shared with
# fetchers.is_posting_live (the burning-alert check) so the two gates cannot drift.
DEAD_MARKERS = ("no longer accepting applications", "this job is no longer available",
                "position has been filled", "posting is closed", "job posting not found",
                "this role is closed", "no longer open", "requisition is closed",
                "job is unavailable", "this job has expired", "job has been closed")

# Hosts whose posting pages are JS shells — the raw GET body proves nothing either way,
# so they skip straight to the render layer. (Workday normally never gets here: its CXS
# JSON endpoint answers first; this is the fallback when the URL shape defeats the regex.)
ALWAYS_RENDER = ("myworkdayjobs.com",)

# Workday's human URL maps to its CXS JSON API, which is authoritative: 200 with
# jobPostingInfo means open, 404 means the req is closed. Verified live 2026-08-22
# against interdigital.wd5 (200 + jobPostingInfo on an open intern req).
_WORKDAY = re.compile(
    r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-zA-Z-]{2,5}(?:_[A-Z]{2})?/)?([^/]+)/job/(.+)$")

# jobright.ai pages embed schema.org JobPosting structured data with a validThrough
# timestamp — jobright's own expiry. Their HTML never carries a closed marker (verified
# 2026-08-22 on month-old postings), so without this field the page is unjudgeable raw.
_VALID_THROUGH = re.compile(r'"validThrough"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def classify(status, body, url=""):
    """(status_code, body_text, url) -> 'live' | 'dead' | 'unsure'. Pure — no I/O.
    Conservative in BOTH directions: dead needs a definitive 404/410 or an explicit
    closed marker; live needs a readable page without one; everything blocked,
    errored, or unreadable is unsure and escalates."""
    if status in (404, 410):
        return "dead"
    if status is None or status >= 400:
        return "unsure"
    low = (body or "").lower()
    if any(m in low for m in DEAD_MARKERS):
        return "dead"
    if any(h in (url or "") for h in ALWAYS_RENDER):
        return "unsure"                      # JS shell: a 200 here proves nothing
    if len(low) < 1500 or "enable javascript" in low or "captcha" in low:
        return "unsure"
    return "live"


def probe(url, timeout=12):
    """Layer 1: one cheap GET, host-aware. No URL means no way to verify — unsure,
    never live. Workday asks the CXS JSON API (authoritative); jobright pages are
    judged by their embedded validThrough expiry; everything else by classify()."""
    if not url:
        return "unsure"
    m = _WORKDAY.match(url)
    if m:
        tenant, wdn, site, rest = m.groups()
        cxs = f"https://{tenant}.{wdn}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{rest}"
        try:
            req = urllib.request.Request(cxs, headers={**_UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(30000).decode("utf-8", "replace")
            return "live" if "jobPostingInfo" in body else "unsure"
        except urllib.error.HTTPError as e:
            return "dead" if e.code in (404, 410) else "unsure"
        except Exception:
            return "unsure"
    try:
        req = urllib.request.Request(url, headers=_UA, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(300000 if "jobright.ai" in url else 60000).decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        return classify(e.code, "", url)
    except Exception:
        return "unsure"
    if "jobright.ai" in url and status == 200:
        vt = _VALID_THROUGH.search(body)
        if vt:
            return "live" if vt.group(1) >= time.strftime("%Y-%m-%d") else "dead"
        return "unsure"       # no expiry field and the HTML never carries closed markers
    return classify(status, body, url)


def render(url):
    """Layer 2: Scrapling renders the page past JS and anti-bot walls.
    Returns (verdict, text_excerpt) — the excerpt feeds layer 3 when still unsure."""
    try:
        from scrapling.fetchers import StealthyFetcher
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        text = " ".join((page.get_all_text() or "").split())
    except Exception:
        return "unsure", ""
    low = text.lower()
    if any(m in low for m in DEAD_MARKERS):
        return "dead", ""
    if "apply" in low and len(low) > 400:
        return "live", ""
    return "unsure", text[:1200]


def _judge_batch(batch):
    """Layer 3: the `liveness` joint judges rendered text the markers could not.
    batch: [(jid, row, excerpt)]. Returns ({jid: 'live'|'dead'}, error_or_None) —
    anything the model does not decisively settle stays out of the mapping (held)."""
    from radar.joints import run_joint
    items = [{"i": i, "company": r.get("company", ""), "title": r.get("title", ""),
              "url": r.get("url", ""), "page_text": (ex or "")[:1200]}
             for i, (_jid, r, ex) in enumerate(batch)]
    prompt = (
        "For each job posting below, judge from page_text ALONE whether the posting is "
        "still open. status is 'dead' ONLY when the text explicitly says the role is "
        "closed, filled, expired, or not found. status is 'live' ONLY when the text "
        "clearly shows this specific role open with a way to apply. Anything else — "
        "empty text, a careers homepage, a login wall, ambiguity — is 'unsure'. Never "
        "infer from posting age or plausibility.\n\n"
        f"POSTINGS:\n{json.dumps(items)}\n\n"
        'Return ONLY a JSON array: [{"i":<idx>,"status":"live|dead|unsure"}]. No prose.')
    try:
        out = run_joint("liveness", prompt).stdout
        js = out[out.find("["):out.rfind("]") + 1]
        verdicts = {}
        for v in json.loads(js):
            if v.get("status") in ("live", "dead"):
                verdicts[batch[int(v["i"])][0]] = v["status"]
        return verdicts, None
    except Exception as ex:
        return {}, f"{type(ex).__name__}: {ex}"[:120]


def _load():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}


def sweep(rows, allow_network=True):
    """Gate rows on liveness. Returns (live, dead, unsure, quality) where quality is
    {checked, from_cache, error} — callers MUST inspect it (a checker that degrades
    without reporting is how the eligibility filter died silently for days).

    allow_network=False (DRY runs) consults the cache only and writes nothing: cached
    dead rows still drop, everything unverifiable is held."""
    from radar.queue_state import job_id
    cache = _load()
    now = time.time()
    live, dead, unsure, to_check = [], [], [], []
    for r in rows:
        jid = job_id(r)
        v = cache.get(jid) or {}
        if v.get("status") == "dead":
            dead.append(r)
        elif v.get("status") == "live" and now - v.get("ts", 0) < LIVE_TTL_H * 3600:
            live.append(r)
        else:
            to_check.append((jid, r))
    q = {"checked": 0, "from_cache": len(rows) - len(to_check), "error": None}
    if not allow_network:
        unsure.extend(r for _, r in to_check)
        return live, dead, unsure, q

    def _settle(jid, r, verdict):
        cache[jid] = {"status": verdict, "ts": int(now), "url": r.get("url", "")}
        (live if verdict == "live" else dead).append(r)

    # Layer 1 — independent and I/O-bound, so threads (parallel iff reordering is a no-op).
    with ThreadPoolExecutor(max_workers=12) as ex:
        l1 = list(ex.map(lambda t: (t[0], t[1], probe(t[1].get("url", ""))), to_check))
    q["checked"] = len(l1)
    needs_render = []
    for jid, r, v in l1:
        if v in ("live", "dead"):
            _settle(jid, r, v)
        else:
            needs_render.append((jid, r))

    # Layer 2 — a real browser per page, so serial and capped; overflow is held to tomorrow.
    cap = int(os.environ.get("IR_LIVECHECK_RENDER_LIMIT", "60"))
    unsure.extend(r for _, r in needs_render[cap:])
    needs_judgment = []
    for jid, r in needs_render[:cap]:
        v, excerpt = render(r.get("url", ""))
        if v in ("live", "dead"):
            _settle(jid, r, v)
        else:
            needs_judgment.append((jid, r, excerpt))

    # Layer 3 — batched model judgment on whatever survived both deterministic layers.
    batch_size = 10
    for s in range(0, len(needs_judgment), batch_size):
        chunk = needs_judgment[s:s + batch_size]
        verdicts, err = _judge_batch(chunk)
        q["error"] = q["error"] or err
        for jid, r, _ex in chunk:
            if jid in verdicts:
                _settle(jid, r, verdicts[jid])
            else:
                unsure.append(r)

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
    return live, dead, unsure, q
