"""LOCAL-only fetchers using Scrapling (stealth browser) for bot-walled but PUBLIC
(no-login) career pages the cloud poller's plain HTTP can't reach. Runs on the operator's Mac.
Confirmed working: Apple, Google, Meta (Google + Meta rebuilt on structured data
2026-10-28). (Tesla stays 403 even via stealth.)
Never used to defeat login/auth walls — public listings only.

Each site's parsing is a pure function (raw page/JSON in -> rows out) so a site change is
caught by tests/test_scrapling_parsers.py against saved fixtures, not by a silent zero.
Fetchers RAISE on fetch errors and on zero rows; fetch_all_scrapling records the reason
per site, so one broken site never stops the others."""
import http.client
import json
import re
import time

from radar.score import is_us_location

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

def _stealth(url, **kw):
    from scrapling.fetchers import StealthyFetcher
    return StealthyFetcher.fetch(url, headless=True, network_idle=True, **kw)

def _http_get(url, timeout=20):
    """Plain GET with certifi's CA bundle passed explicitly, so it works whether or not the
    caller exported SSL_CERT_FILE (the missing-cert failure is a known trap here)."""
    import ssl
    import urllib.request
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")

def fetch_apple():
    p = _stealth("https://jobs.apple.com/en-us/search?search=intern&sort=relevance")
    if p.status != 200:
        return []
    out, seen = [], set()
    for a in p.css('a[href*="/details/"]'):
        title = (a.text or "").strip()
        href = a.attrib.get("href", "")
        if not title or title.lower().startswith("see full role") or href in seen:
            continue
        seen.add(href)
        out.append({"company": "Apple", "title": title,
                    "location": "", "url": "https://jobs.apple.com" + href,
                    "department": "", "posted_at": "", "source": "scrapling:apple"})
    return out

# ---- Google ---------------------------------------------------------------------------
# (2026-10-28) The anchor-tag selectors died silently. Google server-renders every result
# page's data as JSON inside AF_initDataCallback(...) — present in plain HTTP and stealth
# renders alike. We locate that blob by SHAPE (a list whose items start with a numeric job
# id), not by its 'ds:N' key, because key numbering is an implementation detail.
# location=United States is applied server-side (1 page instead of 5); the parser still
# filters on each location's country code so a dropped param can't leak foreign roles.
# q=intern stays: without it the intern level also returns CapitalG "Open ... Career
# Opportunities" catch-alls that aren't internships.
GOOGLE_SEARCH = ("https://www.google.com/about/careers/applications/jobs/results/"
                 "?q=intern&target_level=INTERN_AND_APPRENTICE&location=United%20States&page={}")
GOOGLE_JOB = "https://www.google.com/about/careers/applications/jobs/results/{}"
_AF = re.compile(r"AF_initDataCallback\(\{\s*key:\s*'[^']*',\s*hash:\s*'[^']*',\s*data:")

def _google_blob(html):
    """-> (raw job arrays, total hits). Raises ValueError when no results blob exists:
    that means Google changed its embed, which must not read as 'no internships today'."""
    dec = json.JSONDecoder()
    for m in _AF.finditer(html):
        try:
            data, _ = dec.raw_decode(html, m.end())
        except ValueError:
            continue
        if not (isinstance(data, list) and len(data) >= 3 and isinstance(data[2], int)):
            continue
        jobs = data[0] or []
        if jobs and not (isinstance(jobs[0], list) and str(jobs[0][0]).isdigit()):
            continue
        return jobs, data[2]
    raise ValueError("job-results blob not found in page (Google changed its embed?)")

def parse_google(html):
    """Results page HTML -> (rows, total_hits). Keeps only US-located postings and lists only
    their US locations: downstream is_us_location drops a row naming ANY foreign country."""
    jobs, total = _google_blob(html)
    out = []
    for j in jobs:
        locs = j[9] if len(j) > 9 and isinstance(j[9], list) else []
        names = []
        for loc in locs:
            name = loc[0] if loc else ""
            country = loc[5] if len(loc) > 5 else None
            if (country == "US") if country else is_us_location(name):
                names.append(name)
        if locs and not names:
            continue
        brand = j[7] if len(j) > 7 and isinstance(j[7], str) else ""
        # [12] is the earliest of three [seconds, nanos] stamps (12/13/14): read as publish
        # time. Google never displays a date, so this is inferred, not confirmed (2026-10-28).
        ts = j[12][0] if len(j) > 12 and isinstance(j[12], list) and j[12] else None
        out.append({"company": "Google", "title": str(j[1]).strip(),
                    "location": "; ".join(names),
                    "url": GOOGLE_JOB.format(j[0]),   # id-only: survives title edits, resolves 200
                    "department": brand if brand and brand != "Google" else "",
                    "posted_at": time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "",
                    "source": "scrapling:google"})
    return out, total

def fetch_google(max_pages=10, budget_s=45):
    """Plain HTTP first (~1s/page; Google serves the full blob to it), stealth only if that
    errors. Paginates until the reported total is covered or the time budget runs out."""
    t0, rows, seen_raw, page = time.monotonic(), [], 0, 1
    while page <= max_pages:
        url = GOOGLE_SEARCH.format(page)
        try:
            html = _http_get(url)
        except (OSError, http.client.HTTPException) as ex:   # URLError/timeout/SSL are OSError
            print(f"[warn] google: plain fetch failed ({type(ex).__name__}: {ex}); retrying via stealth")
            html = _stealth(url).html_content
        jobs, total = _google_blob(html)
        page_rows, _ = parse_google(html)
        rows += page_rows
        seen_raw += len(jobs)
        if not jobs or seen_raw >= total:
            break
        if time.monotonic() - t0 > budget_s:
            print(f"[warn] google: time budget hit after page {page}; {seen_raw}/{total} results read")
            break
        page += 1
    rows = list({r["url"]: r for r in rows}.values())
    if not rows:
        raise RuntimeError(f"0 US intern rows ({seen_raw} raw results of {total} reported)")
    return rows

# ---- Meta -----------------------------------------------------------------------------
# (2026-10-28) /jobs?q= now 301s to /jobsearch/ and job links moved to
# /profile/job_details/<id>; the old a[href*="/jobs/"] selector matched nothing. The page
# loads its results from a public, no-login GraphQL query (CareersJobSearchResultsV2DataQuery)
# that returns EVERY match in one response — so we capture that response in the stealth
# render instead of scraping DOM cards (which only render 10 at a time). Replaying the POST
# ourselves would need the rotating doc_id + lsd token; capturing what the page itself
# fetches survives both. roles[0]=Internship is Meta's own classification: on 2026-10-28 it
# returned exactly the 125 intern-titled jobs of the q=intern search (incl. both Reality
# Labs TPM interns, which Meta files under "University Grad", not "Internship").
META_SEARCH = "https://www.metacareers.com/jobsearch/?roles[0]=Internship"
META_JOB = "https://www.metacareers.com/profile/job_details/{}/"
_INTERN = re.compile(r"\bintern(ship)?s?\b", re.IGNORECASE)   # \b: never "Internal", "International"
_LEVEL_TEAM = ("Internship", "University Grad")       # career-level buckets, not departments

def parse_meta(payload):
    """GraphQL response (str or parsed dict) -> rows. Re-checks intern-ness and US location
    itself so that if Meta ever ignores the roles filter we still ship only US internships.
    Raises ValueError when the payload has no all_jobs list (query renamed / shape changed)."""
    docs = [payload] if isinstance(payload, dict) else \
        [json.loads(line) for line in str(payload).splitlines() if line.strip().startswith("{")]
    found, jobs = False, []
    for d in docs:
        for v in ((d or {}).get("data") or {}).values():
            if isinstance(v, dict) and isinstance(v.get("all_jobs"), list):
                found = True
                jobs += v["all_jobs"] + (v.get("featured_jobs") or [])
    if not found:
        raise ValueError("no all_jobs list in GraphQL payload (Meta changed the query?)")
    out, seen = [], set()
    for j in jobs:
        jid, title = str(j.get("id") or ""), (j.get("title") or "").strip()
        teams = j.get("teams") or []
        if not jid or jid in seen or not title:
            continue
        if not (_INTERN.search(title) or any(t.startswith("Internship") for t in teams)):
            continue
        locs = j.get("locations") or []
        us = [l for l in locs if is_us_location(l)]
        if locs and not us:
            continue
        seen.add(jid)
        dept = [t for t in teams if not t.startswith(_LEVEL_TEAM)] or (j.get("sub_teams") or [])
        out.append({"company": "Meta", "title": title, "location": "; ".join(us),
                    "url": META_JOB.format(jid), "department": ", ".join(dept),
                    "posted_at": "",   # not in the search payload; per-job fetch not worth 125 renders
                    "source": "scrapling:meta"})
    return out

def fetch_meta():
    p = _stealth(META_SEARCH, capture_xhr=r"/graphql")
    if p.status != 200:
        raise RuntimeError(f"search page HTTP {p.status}")
    xhrs = getattr(p, "captured_xhr", None) or []
    for x in xhrs:
        body = x.body.decode("utf-8", "replace") if isinstance(x.body, (bytes, bytearray)) else str(x.body)
        if '"all_jobs"' in body:
            rows = parse_meta(body)
            if not rows:
                raise RuntimeError("search payload parsed but 0 US intern rows")
            return rows
    raise RuntimeError(f"results payload not among {len(xhrs)} captured /graphql responses")

def fetch_all_scrapling():
    """Per-site isolation: a site that raises becomes one errors[] line, never a dead run."""
    out, errors = [], []
    for name, fn in [("apple", fetch_apple), ("google", fetch_google), ("meta", fetch_meta)]:
        try:
            out.extend(fn())
        except Exception as ex:
            errors.append(f"{name}: {type(ex).__name__}: {ex}")
    return out, errors
