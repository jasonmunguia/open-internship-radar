"""Source fetchers: ATS boards (Greenhouse/Lever/Ashby) + GitHub job-list repos."""
import re, json, time, urllib.request

from radar.settings import USER_AGENT

UA = {"User-Agent": USER_AGENT}

# ---- pay extraction (2026-08-15: show salary/hourly pay in the digest) ----
# Deterministic only — no model call, no extra HTTP. Reads pay from what the ATS list
# response already carries: Lever's salaryRange/descriptionPlain, Ashby's
# compensationTierSummary, speedrun's comp_min/max. Greenhouse/Workday list endpoints
# carry no pay, so those rows have none — blank means "board didn't publish it",
# never "extraction silently died" (test_feedback.py holds a positive control).
_PAY_HOURLY = re.compile(
    r"(\$\d{1,3}(?:\.\d{2})?(?:\s*(?:[-–—~]|to)\s*\$?\d{1,3}(?:\.\d{2})?)?)\s*(?:/\s*|\bper\s+)(?:hr|hour)",
    re.IGNORECASE)
_PAY_ANNUAL = re.compile(
    r"(\$\d{2,3},\d{3}(?:\s*(?:[-–—~]|to)\s*\$?\d{2,3},\d{3})?)")
_PAY_K = re.compile(
    r"(\$\d{2,3}\s?[kK](?:\s*(?:[-–—~]|to)\s*\$?\d{2,3}\s?[kK])?)")

def extract_pay(text):
    """Best-effort pay string from posting text: '$45–$55/hr' or '$120,000–$140,000/yr'.
    Hourly checked first — intern comp is usually hourly and an hourly figure next to an
    annualized range is the one an intern actually gets paid."""
    if not text:
        return ""
    m = _PAY_HOURLY.search(text)
    if m:
        return re.sub(r"\s+", "", m.group(1)) + "/hr"
    m = _PAY_ANNUAL.search(text) or _PAY_K.search(text)
    if m:
        return re.sub(r"\s+", "", m.group(1)) + "/yr"
    return ""


def _get(url, timeout=20, retries=3):
    """GET with backoff. Job boards rate-limit and time out routinely; without retries a single
    blip starts a false 'source went dark' streak (this is exactly what happened to Anduril on
    2026-07-30 — its board was serving 2,142 jobs minutes after the alert fired)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # 4xx other than 429 is a real answer ("this board is gone") — don't waste retries.
            if e.code != 429 and 400 <= e.code < 500:
                raise
            last = e
        except Exception as e:
            last = e
        if attempt < retries - 1:
            time.sleep(1.5 * (2 ** attempt))          # 1.5s, 3s
    raise last

def _post(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def fetch_greenhouse(company, token):
    jobs = json.loads(_get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"))["jobs"]
    return [{"company": company, "title": j["title"], "location": (j.get("location") or {}).get("name", ""),
             "url": j["absolute_url"], "department": " ".join(d.get("name","") for d in j.get("departments",[]) if d),
             "posted_at": (j.get("first_published") or j.get("updated_at") or "")[:10],
             "source": f"greenhouse:{token}"} for j in jobs]

def fetch_lever(company, org):
    jobs = json.loads(_get(f"https://api.lever.co/v0/postings/{org}?mode=json"))
    out = []
    for j in jobs:
        ts = j.get("createdAt")
        posted = ""
        if ts:
            import datetime as _dt
            posted = _dt.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        # Structured salaryRange first (pay-transparency postings carry it); regex over
        # the plain description otherwise.
        sr = j.get("salaryRange") or {}
        if sr.get("min") and sr.get("max"):
            unit = "/hr" if "hour" in str(sr.get("interval", "")).lower() else "/yr"
            pay = f"${int(sr['min']):,}–${int(sr['max']):,}{unit}"
        else:
            pay = extract_pay(f"{j.get('descriptionPlain','')} {j.get('additionalPlain','')}")
        out.append({"company": company, "title": j["text"], "location": (j.get("categories") or {}).get("location", ""),
                    "url": j["hostedUrl"], "department": (j.get("categories") or {}).get("team", ""),
                    "posted_at": posted, "pay": pay, "source": f"lever:{org}"})
    return out

def fetch_workday(company, token):
    """token = 'tenant/site'. Workday cxs JSON API."""
    tenant, _, site = token.partition("/")
    # infer wd host number from a known map or default wd1; caller can pass 'tenant@wd5/site'
    host = "wd1"
    if "@" in tenant:
        tenant, host = tenant.split("@")
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    base = f"https://{tenant}.{host}.myworkdayjobs.com/en-US/{site}"
    out = []
    for offset in range(0, 100, 20):
        data = json.loads(_post_hdr(url, {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "intern"},
                                    {"User-Agent": UA["User-Agent"], "Content-Type": "application/json",
                                     "Accept": "application/json"}))
        jp = data.get("jobPostings", [])
        if not jp:
            break
        for j in jp:
            out.append({"company": company, "title": j.get("title", ""),
                        "location": j.get("locationsText", ""),
                        "url": base + j.get("externalPath", ""),
                        "department": "", "posted_at": "", "source": f"workday:{tenant}"})
        if len(jp) < 20:
            break
    return out

def fetch_smartrecruiters(company, org):
    out = []
    for offset in (0, 100, 200):
        data = json.loads(_get(f"https://api.smartrecruiters.com/v1/companies/{org}/postings?limit=100&offset={offset}"))
        content = data.get("content", [])
        if not content:
            break
        for j in content:
            loc = j.get("location", {}) or {}
            out.append({"company": company, "title": j.get("name", ""),
                        "location": ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                        "url": f"https://jobs.smartrecruiters.com/{org}/{j.get('id','')}",
                        "department": (j.get("department") or {}).get("label", ""),
                        "posted_at": str(j.get("releasedDate") or "")[:10], "source": f"smartrecruiters:{org}"})
        if len(content) < 100:
            break
    return out

def fetch_eightfold(company, token):
    """token = 'host|domain', e.g. 'explore.jobs.netflix.net|netflix.com'."""
    host, _, domain = token.partition("|")
    out = []
    for start in (0, 10, 20, 30):
        data = json.loads(_get(f"https://{host}/api/apply/v2/jobs?domain={domain}&query=intern&start={start}&num=10"))
        positions = data.get("positions", []) or data.get("jobs", [])
        if not positions:
            break
        for j in positions:
            out.append({"company": company, "title": j.get("name", "") or j.get("title", ""),
                        "location": j.get("location", "") or ", ".join(j.get("locations", []) or []),
                        "url": j.get("canonicalPositionUrl") or j.get("apply_url") or j.get("url", ""),
                        "department": "", "posted_at": "", "source": f"eightfold:{domain}"})
        if len(positions) < 10:
            break
    return out

def fetch_oraclecloud(company, token):
    """token = 'tenant|siteNumber', e.g. 'jpmc|CX_1001'. Oracle Cloud Recruiting's public
    CE API — keyless JSON, used by the finance/CPG giants the aggregator boards never
    carry (verified 2026-08-22: jpmc returned '2027 Markets Summer Analyst Program')."""
    tenant, _, site = token.partition("|")
    # `expand` is REQUIRED: without it the API returns 200 with an empty requisitionList
    # — a classic wrong-200 (verified 2026-08-22: same query, 0 rows bare vs 99 expanded).
    data = json.loads(_get(
        f"https://{tenant}.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        f"?onlyData=true&expand=requisitionList.secondaryLocations"
        f"&finder=findReqs;siteNumber={site},keyword=intern,limit=100"))
    out = []
    for j in (data.get("items") or [{}])[0].get("requisitionList", []):
        rid = j.get("Id", "")
        out.append({"company": company, "title": j.get("Title", ""),
                    "location": j.get("PrimaryLocation", ""),
                    "url": f"https://{tenant}.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
                    "department": "", "posted_at": str(j.get("PostedDate", "")),
                    "source": f"oraclecloud:{tenant}"})
    return out

def fetch_ashby(company, org):
    data = json.loads(_get(f"https://api.ashbyhq.com/posting-api/job-board/{org}"), strict=False)
    return [{"company": company, "title": j["title"], "location": j.get("location", ""),
             "url": j.get("jobUrl") or j.get("applyUrl", ""), "department": j.get("department", "") or j.get("team", ""),
             "posted_at": str(j.get("publishedAt") or j.get("publishedDate") or "")[:10],
             # Ashby publishes a ready-made comp string when the employer opts in.
             "pay": j.get("compensationTierSummary") or "",
             "source": f"ashby:{org}"} for j in data.get("jobs", [])]

def fetch_substack(name, sub):
    """New posts from a Substack RSS feed -> newsletter items."""
    xml = _get(f"https://{sub}.substack.com/feed")
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    out = []
    for it in items[:10]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        l = re.search(r"<link>(.*?)</link>", it, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        if t and l:
            out.append({"company": name, "title": t.group(1).strip(), "location": "",
                        "url": l.group(1).strip(), "department": "",
                        "posted_at": (d.group(1).strip() if d else ""), "type": "newsletter",
                        "source": f"substack:{sub}"})
    return out

def watch_page(name, url):
    """Hash a program page; caller diffs the hash to detect cohort openings."""
    import hashlib
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", _get(url), flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha1(text.encode()).hexdigest()

def _post_hdr(url, body, headers, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _pick(d, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return default

def fetch_getro(company, collection_id):
    # exact Accept header required or Getro 406s; hitsPerPage caps at 20, so paginate
    out = []
    for page in range(6):
        raw = _post_hdr(f"https://api.getro.com/api/v2/collections/{collection_id}/search/jobs",
                        {"hitsPerPage": 20, "page": page, "query": "intern", "filters": {}},
                        {"User-Agent": UA["User-Agent"], "Content-Type": "application/json",
                         "Accept": "application/json"})
        data = json.loads(raw)
        jobs = data.get("results", {}).get("jobs") if isinstance(data.get("results"), dict) else None
        jobs = jobs or data.get("jobs", []) or (data.get("results") if isinstance(data.get("results"), list) else [])
        if not jobs:
            break
        for j in jobs:
            org = j.get("organization") or {}
            out.append({"company": f"{_pick(org, 'name', default=company)}",
                        "title": _pick(j, "title", "name"),
                        "location": ", ".join(j.get("locations", [])) if isinstance(j.get("locations"), list) else str(j.get("locations", "")),
                        "url": _pick(j, "url", "applyUrl", "hostedUrl"),
                        "department": "", "source": f"getro:{collection_id}"})
        if len(jobs) < 20:
            break
    return out

def fetch_consider(company, token):
    """Consider-platform board. token = 'host|board_id' (host omitted -> jobs.{slug}.com)."""
    host, _, board_id = token.partition("|")
    if not board_id:
        board_id = host
    raw = _post_hdr(f"https://{host}/api-boards/search-jobs",
                    {"meta": {"size": 100}, "board": {"id": board_id, "isParent": True},
                     "query": {"promoteFeatured": True, "searchText": "intern"}},
                    {"User-Agent": UA["User-Agent"], "Content-Type": "application/json",
                     "Accept": "application/json"})
    data = json.loads(raw)
    return [{"company": _pick(j, "companyName", "company", default=company),
             "title": _pick(j, "title", "name"),
             "location": str(_pick(j, "locations", "location")),
             "url": _pick(j, "applyUrl", "url", "jobUrl"),
             "posted_at": str(_pick(j, "createdAt", "publishedAt", "timeStamp"))[:10],
             "department": "", "source": f"consider:{board_id}"} for j in data.get("jobs", [])]

def fetch_a16z(company="a16z portfolio", token="jobs.a16z.com|andreessen-horowitz"):
    return fetch_consider(company, token)

def fetch_speedrun(company="a16z speedrun network", pages=12):
    """a16z speedrun talent network — public v1 API (no auth/keys).
    Covers the a16z portfolio (10k+ roles) AND a wider 'market' set, ~4.7k tagged seniority=intern.
    Documented at /developers; spec at /api/v1/openapi.json. Sorted recent-first, so a dozen pages
    comfortably covers everything new since the last 2-hour run. Carries real publish dates and
    comp bands, which most ATS feeds don't."""
    import time as _t
    out = []
    for page in range(1, pages + 1):
        url = ("https://speedrun-talent-network.com/api/v1/jobs"
               f"?sen=intern&sort=recent&page={page}")
        try:
            data = json.loads(_get(url))
        except Exception:
            break
        jobs = data.get("jobs", [])
        if not jobs:
            break
        for j in jobs:
            comp = ""
            if j.get("comp_min"):
                comp = f"${int(j['comp_min'])//1000}k-{int(j.get('comp_max') or 0)//1000}k"
            out.append({"company": _pick(j, "company", "company_slug", default=company),
                        "title": _pick(j, "title"),
                        "location": str(_pick(j, "location")),
                        "url": _pick(j, "url", "company_url"),
                        # comp moved out of department (2026-08-15): it now has a first-class
                        # field; keeping it in department polluted keyword matching.
                        "department": _pick(j, "function"),
                        "pay": (comp + "/yr") if comp else "",
                        "posted_at": str(_pick(j, "published_at"))[:10],
                        "source": "speedrun"})
        if page >= data.get("total_pages", 0):
            break
        _t.sleep(0.2)
    return out

def fetch_amazon(company="Amazon"):
    """US-only, multi-query, paginated.
    country=USA is essential: without it the 100-result window fills with Mexico/Brazil/India
    postings and US roles never surface. 'internship' returns ~1500 US hits vs ~35 for 'intern'."""
    import urllib.parse, time as _t
    out, seen = [], set()
    for query, pages in (("internship", 3), ("intern", 1), ("university", 1)):
        for page in range(pages):
            url = ("https://www.amazon.jobs/en/search.json"
                   f"?base_query={urllib.parse.quote(query)}&country=USA"
                   f"&offset={page * 100}&result_limit=100")
            try:
                jobs = json.loads(_get(url)).get("jobs", [])
            except Exception:
                break
            if not jobs:
                break
            for j in jobs:
                path = _pick(j, "job_path")
                if not path or path in seen:
                    continue
                seen.add(path)
                out.append({"company": company, "title": _pick(j, "title"),
                            "location": _pick(j, "normalized_location", "location"),
                            "url": "https://www.amazon.jobs" + path,
                            "department": _pick(j, "job_category", "business_category"),
                            "posted_at": str(_pick(j, "posted_date"))[:10],
                            "source": "amazon"})
            _t.sleep(0.3)
    return out

def fetch_bcg(company="BCG"):
    body = {"lang": "en_us", "deviceType": "desktop", "country": "us", "pageName": "search-results",
            "ddoKey": "refineSearch", "from": 0, "jobs": True, "counts": True,
            "all_fields": ["category", "country", "state", "city"], "size": 100,
            "jdsource": "facets", "siteType": "external", "keywords": "intern", "global": True,
            "selected_fields": {}}
    raw = _post_hdr("https://careers.bcg.com/widgets", body,
                    {"User-Agent": UA["User-Agent"], "Content-Type": "application/json",
                     "Accept": "application/json"})
    jobs = json.loads(raw).get("refineSearch", {}).get("data", {}).get("jobs", [])
    return [{"company": company, "title": _pick(j, "title"),
             "location": _pick(j, "cityStateCountry", "city", "location"),
             "url": _pick(j, "applyUrl", "jobUrl") or f"https://careers.bcg.com/global/en/job/{_pick(j,'jobId','jobSeqNo')}",
             "department": _pick(j, "category"), "source": "bcg"} for j in jobs]

def fetch_rippling(company="Rippling"):
    data = json.loads(_get("https://api.rippling.com/platform/api/ats/v1/board/rippling/jobs"))
    jobs = data if isinstance(data, list) else data.get("jobs", data.get("results", []))
    return [{"company": company, "title": _pick(j, "name", "title"),
             "location": str(_pick(j, "workLocation", "location")),
             "url": _pick(j, "url", "applyUrl"), "department": str(_pick(j, "department")),
             "source": "rippling"} for j in jobs]

def fetch_manatal(company, org):
    out, url = [], f"https://core.api.manatal.com/open/v3/career-page/{org}/jobs/"
    for _ in range(5):
        data = json.loads(_get(url))
        for j in data.get("results", []):
            out.append({"company": company, "title": _pick(j, "position_name", "name", "title"),
                        "location": _pick(j, "location_display", "location", "city"),
                        "url": f"https://www.careers-page.com/{org}/job/{_pick(j, 'hash', 'slug', 'id')}",
                        "department": "", "source": f"manatal:{org}"})
        url = data.get("next")
        if not url:
            break
    return out

MD_ROW = re.compile(r"^\|(.+)\|\s*$")
LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)|href=\"([^\"]+)\"")

def fetch_github_repo(repo, branches=("main", "dev", "master")):
    """Parse markdown tables in a job-list repo README. Rows -> postings."""
    text = None
    for br in branches:
        try:
            text = _get(f"https://raw.githubusercontent.com/{repo}/{br}/README.md")
            break
        except Exception:
            continue
    if text is None:
        return []
    out, last_company = [], ""
    for line in text.splitlines():
        m = MD_ROW.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 3 or set("".join(cells)) <= set("-: "):
            continue
        company = re.sub(r"\*|\[|\]\([^)]*\)|<[^>]+>", "", cells[0]).strip()
        if company in ("Company", "Name", ""):
            if company == "":
                company = last_company  # continuation row (↳)
            else:
                continue
        if company in ("↳",):
            company = last_company
        last_company = company or last_company
        raw_title = cells[1]
        tl = LINK.search(raw_title)
        link = ""
        if tl:
            title = tl.group(1) or ""
            link = tl.group(2) or ""
        else:
            title = raw_title
        title = re.sub(r"<[^>]+>|\*", "", title).strip()
        if not link:
            for c in cells[2:]:
                lm = LINK.search(c)
                if lm:
                    link = lm.group(2) or lm.group(3) or ""
                    if "http" in link:
                        break
        loc = re.sub(r"<[^>]+>", " ", cells[2]).strip() if len(cells) > 2 else ""
        if not title:
            continue
        out.append({"company": company, "title": title, "location": loc,
                    "url": link, "department": "", "source": f"github:{repo}"})
    return out

def fetch_all(sources):
    postings, errors = [], []
    counts = {}  # per-source fetch count; -1 = errored (for health monitoring)
    simple = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
              "getro": fetch_getro, "manatal": fetch_manatal, "consider": fetch_consider,
              "workday": fetch_workday, "smartrecruiters": fetch_smartrecruiters,
              "eightfold": fetch_eightfold, "oraclecloud": fetch_oraclecloud}
    standalone = {"a16z": fetch_a16z, "amazon": fetch_amazon, "bcg": fetch_bcg,
                  "rippling": fetch_rippling, "speedrun": fetch_speedrun}
    for e in sources.get("ats", []):
        try:
            if e["ats"] in simple:
                got = simple[e["ats"]](e["name"], e["token"])
            elif e["ats"] in standalone:
                got = standalone[e["ats"]]()
            else:
                continue
            postings.extend(got)
            counts[e["name"]] = len(got)
        except Exception as ex:
            errors.append(f"{e['name']}: {ex}")
            counts[e["name"]] = -1
    for repo in sources.get("github_repos", []):
        try:
            got = fetch_github_repo(repo)
            postings.extend(got)
            counts[f"repo:{repo}"] = len(got)
        except Exception as ex:
            errors.append(f"{repo}: {ex}")
            counts[f"repo:{repo}"] = -1
    return postings, errors, counts


def is_posting_live(url, timeout=12):
    """Is this posting still open? Adapted from career-ops' liveness doctrine (santifer/career-ops):
    never surface a dead listing — a closed role wastes the one thing an applicant can't get back.
    Conservative by design: only a definitive 404/410, or an ATS page that self-identifies as closed,
    counts as dead. Network trouble returns True, because a false 'dead' silently hides a real job."""
    if not url:
        return True
    try:
        req = urllib.request.Request(url, headers=UA, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(60000).decode("utf-8", "replace").lower()
    except urllib.error.HTTPError as e:
        return e.code not in (404, 410)
    except Exception:
        return True
    # Marker list lives in radar/liveness.py (the digest's gate) so the two checks
    # cannot drift apart — one vocabulary for "this page says it is closed".
    from radar.liveness import DEAD_MARKERS
    return not any(m in body for m in DEAD_MARKERS)
