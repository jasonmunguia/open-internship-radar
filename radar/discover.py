"""LLM-free web discovery — finds postings that are on no board we poll.

Every other source answers "what did this board publish?". This answers "what exists?".
Deterministic query templates against rotating SearXNG instances, same pattern as the
lead-gen pipeline. No model: the LLM only ever judges borderline rows downstream.

Rotation matters because a single public SearXNG instance rate-limits or disappears without
warning; treating one as reliable is how a discovery pass silently returns zero forever.
"""
import re, time, urllib.parse

INSTANCES = ["https://searx.be", "https://search.bus-hit.me", "https://priv.au", "https://searxng.site"]

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


def _fetch(instance, q):
    from scrapling.fetchers import StealthyFetcher
    url = f"{instance}/search?q={urllib.parse.quote(q)}&format=json"
    try:
        p = StealthyFetcher.fetch(url, headless=True, network_idle=False, timeout=30000)
        return p.get_all_text() if p.status == 200 else ""
    except Exception:
        return ""


def discover(families=None, per_query=1):
    """Returns [{url, family, query}] for postings found on ATS hosts. Dedup and scoring
    happen downstream in the normal pipeline — this only widens the funnel."""
    out, seen = [], set()
    fams = families or list(FAMILY_QUERIES)
    for i, fam in enumerate(fams):
        for base in FAMILY_QUERIES.get(fam, []):
            for site in SITES[:per_query] if per_query else SITES:
                q = f"{base} site:{site}"
                inst = INSTANCES[(i + len(out)) % len(INSTANCES)]   # rotate, never hammer one
                text = _fetch(inst, q)
                for u in re.findall(r"https?://[^\s\"'<>]+", text):
                    if site in u and u not in seen:
                        seen.add(u)
                        out.append({"url": u, "family": fam, "query": q})
                time.sleep(1.2)
    return out
