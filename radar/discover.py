"""Open-web discovery — finds postings that are on no board we poll.

WHY THIS IS A CLAUDE JOINT AND NOT A SCRAPER (revised 2026-08-09)
The first version issued `site:boards.greenhouse.io` queries to scraped search-engine HTML.
It ran clean and returned ZERO, twice, for two different reasons: three of four public SearXNG
instances were dead (403/429/DNS), and the surviving engines do not surface ATS job pages for
a site: query through their HTML endpoints -- DuckDuckGo returned the bare domain with no path,
Bing an encoded parameter. Scraping search results is a fragile way to ask "what exists?".

A coding agent with real web search answers the same question directly and can also read the
posting to confirm it is real before returning it. The deterministic scraper is kept below as
a fallback for anyone without model access, but it is no longer the primary path. This is the
rule from METHODOLOGY.md applied honestly: use code where output is identical, use a model
where it is genuinely better -- and be willing to move the line after you measure.

Legacy scraper notes — finds postings that are on no board we poll.

Every other source answers "what did this board publish?". This answers "what exists?".
Deterministic query templates against rotating SearXNG instances, same pattern as the
lead-gen pipeline. No model: the LLM only ever judges borderline rows downstream.

Rotation matters because a single public SearXNG instance rate-limits or disappears without
warning; treating one as reliable is how a discovery pass silently returns zero forever.
"""
import re, time, urllib.parse

# Backends in reliability order. Observed 2026-08-09 on the first live run: priv.au 403 then
# 429, searxng.site 403, search.bus-hit.me DNS failure — 3 of 4 dead in one night, and the pass
# returned 0 results while reporting success. Public SearXNG instances are volunteer-run and
# churn constantly, so the HTML endpoints of the big engines are the reliable floor and the
# SearXNG instances are the bonus. DuckDuckGo HTML is proven — it is what resolves LinkedIn
# slugs elsewhere in this codebase.
BACKENDS = [
    ("ddg",     "https://html.duckduckgo.com/html/?q={q}"),
    ("bing",    "https://www.bing.com/search?q={q}"),
    ("searxbe", "https://searx.be/search?q={q}"),
]
INSTANCES = [u for _, u in BACKENDS]

# One template per family. Site filters target the ATS hosts a posting actually lives on, so
# results are postings rather than blog posts about postings.
SITES = ["boards.greenhouse.io", "jobs.ashbyhq.com", "jobs.lever.co", "myworkdayjobs.com"]
FAMILY_QUERIES = {
    "product":     ['"product manager intern" 2027', '"associate product manager intern" 2027'],
    "cos_bizops":  ['"chief of staff intern" 2027', '"business operations intern" 2027'],
    "gtm_bd":      ['"business development intern" 2027', '"go-to-market intern" 2027'],
    "deployment":  ['"deployment strategist" intern 2027', '"solutions intern" 2027'],
    "consulting":  ['"business analyst intern" 2027'],
    "vc":          ['"investment intern" venture 2027'],
    "ops_supply":  ['"operations intern" 2027'],
}


def _fetch(url_tpl, q):
    from scrapling.fetchers import StealthyFetcher
    url = url_tpl.format(q=urllib.parse.quote(q))
    try:
        p = StealthyFetcher.fetch(url, headless=True, network_idle=False, timeout=30000)
        if p.status != 200:
            return ""
        # str(p.body) too: result URLs live in href attributes, not visible text
        return p.get_all_text() + " " + str(p.body)
    except Exception:
        return ""


def discover_scraped(families=None, per_query=1):
    """Returns [{url, family, query}] for postings found on ATS hosts. Dedup and scoring
    happen downstream in the normal pipeline — this only widens the funnel."""
    out, seen = [], set()
    fams = families or list(FAMILY_QUERIES)
    for i, fam in enumerate(fams):
        for base in FAMILY_QUERIES.get(fam, []):
            for site in SITES[:per_query] if per_query else SITES:
                q = f"{base} site:{site}"
                # Try backends in order until one returns something. Rotating blindly meant a
                # dead instance silently consumed a query and the run reported success with
                # zero results — a discovery pass that finds nothing must look different from
                # one that is broken.
                text = ""
                for _, tpl in BACKENDS:
                    text = _fetch(tpl, q)
                    if text:
                        break
                    time.sleep(0.8)
                # Engines render results three ways and only one is a plain URL:
                #   1. a real https:// link
                #   2. a redirect wrapper with the target percent-encoded inside
                #   3. display text with no scheme ("boards.greenhouse.io > jobs > 123")
                # Matching only shape 1 returned nothing while the page plainly contained
                # hits — a discovery pass that finds zero must not look like one that works.
                hay = text + ' ' + urllib.parse.unquote(text)
                pat = re.compile(r'(?:https?://)?' + re.escape(site) + r'[^\s"\'<>&]*')
                for raw in pat.findall(hay):
                    u = raw.strip()
                    if not u.startswith('http'):
                        u = 'https://' + u
                    if u.rstrip('/') == 'https://' + site or u in seen:
                        continue                      # bare domain, no posting path
                    seen.add(u)
                    out.append({'url': u, 'family': fam, 'query': q})
                time.sleep(1.2)
    return out


def discover(families=None, timeout=900, per_query=None):
    """Ask a coding-agent CLI with web search to find postings no polled board carries.

    Returns [{url, family, company, title}]. Everything found re-enters the normal pipeline
    and is scored, gated and deduped like any other row -- discovery widens the funnel, it
    never bypasses the filters."""
    import json as _json, subprocess
    fams = families or list(FAMILY_QUERIES)
    wanted = "\n".join(f"- {f}: " + "; ".join(FAMILY_QUERIES[f]) for f in fams if f in FAMILY_QUERIES)
    prompt = (
        "Find CURRENTLY OPEN US internship/co-op postings matching the role families below. "
        "Use web search. Prefer postings on applicant-tracking hosts (boards.greenhouse.io, "
        "jobs.ashbyhq.com, jobs.lever.co, myworkdayjobs.com) and official company career pages.\n\n"
        f"{wanted}\n\n"
        "Rules:\n"
        "1. Only postings you have actually seen. Do not construct plausible URLs.\n"
        "2. Only roles open to undergraduates. Exclude MBA-only, new-grad and senior roles.\n"
        "3. Prefer things unlikely to appear on aggregator lists.\n"
        "4. Return ONLY a JSON array, no prose: "
        "[{\"url\":\"...\",\"company\":\"...\",\"title\":\"...\",\"family\":\"...\"}]\n"
        "5. An empty array is a correct answer. A fabricated URL is not.")
    try:
        r = subprocess.run(["claude", "-p", prompt, "--permission-mode", "bypassPermissions"],
                           capture_output=True, text=True, timeout=timeout)
        body = r.stdout
        body = body.split("```")[1].lstrip("json").strip() if "```" in body else body.strip()
        rows = _json.loads(body[body.find("["):body.rfind("]") + 1])
    except Exception as ex:
        print(f"[discover] model pass failed ({type(ex).__name__}); falling back to scraper")
        return discover_scraped(families=families, per_query=per_query or 1)
    out = []
    for x in rows if isinstance(rows, list) else []:
        if isinstance(x, dict) and str(x.get("url", "")).startswith("http"):
            out.append({"url": x["url"], "company": x.get("company", ""),
                        "title": x.get("title", ""), "family": x.get("family", ""),
                        "source": "discovery"})
    return out
