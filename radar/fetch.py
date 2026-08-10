"""One shared validated fetch — "a 404 is safe; a wrong 200 is dangerous", encoded.

This rule used to live as a comment repeated in three files while the validation logic
drifted apart. The incident it encodes: an unknown company slug 301-redirected to a
different company on a foreign host (linkedin.com/company/uber ->
uk.linkedin.com/company/ubercreativedigitalagency), passed a substring name check, and
tiered a major company on 5,984 followers. Every fetch that must not silently return the
wrong page goes through validated_fetch; callers get the REASON so rejections are loggable.
"""
import re

# Corporate suffixes a page name may legitimately carry beyond the requested name.
# Shared with tiers._key_candidates (division -> parent cache keys) — one list, one truth.
SUFFIXES = ("freight", "ventures", "labs", "studios", "health", "cloud", "ai", "robotics",
            "technologies", "technology", "financial", "capital", "industries")


def _host(url):
    m = re.match(r"https?://([^/]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def _domain(host):
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def linkedin_slug(url):
    m = re.search(r"linkedin\.com/company/([^/?#]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def name_matches(page_title, company):
    """Substring matching is too weak in both directions ('uber' matches
    'ubercreativedigitalagency'), so compare normalised names: the page name must equal
    the requested name, or exceed it only by known corporate suffixes."""
    if not page_title:
        return False
    page_name = page_title.split("|")[0]
    norm = lambda t: [w for w in re.sub(r"[^a-z0-9 ]", " ", t.lower()).split() if w]
    want, got = norm(company), norm(page_name)
    if not want or not got:
        return False
    if got[:len(want)] != want:                       # must START with the requested name
        return False
    extra = set(got[len(want):]) - set(SUFFIXES) - {"the", "group", "co", "company", "and"}
    return not extra                                  # no unexplained extra words


def validated_fetch(url, expect=None, allow_redirect_host=False, timeout=40000):
    """Fetch url via Scrapling and validate what actually came back. -> (page, ok, reason)

    - non-200 fails (a 404 is SAFE — it cannot lie about identity)
    - a redirect to a different registered DOMAIN fails unless allow_redirect_host=True
      (search-engine endpoints bounce between their own hosts; identity pages must not).
      Same-domain host moves (www.linkedin.com -> uk.linkedin.com) are tolerated — the
      slug gate below still guards identity.
    - a redirect that changes a linkedin company slug fails: if the slug moved, the
      company we asked for is not the company we got
    - with expect=<company name>, the page must NAME that company (prefix match, known
      corporate suffixes tolerated)

    Callers should log `reason` on ok=False wherever a rejection is surprising — a
    wrong-200 rejection that is indistinguishable from a miss hides systematic failure.
    """
    from scrapling.fetchers import StealthyFetcher
    try:
        p = StealthyFetcher.fetch(url, headless=True, network_idle=False, timeout=timeout)
    except Exception as ex:
        return None, False, f"fetch failed: {type(ex).__name__}"
    if p.status != 200:
        return p, False, f"status {p.status}"
    final = getattr(p, "url", "") or ""
    if final:
        if not allow_redirect_host and _domain(_host(final)) != _domain(_host(url)):
            return p, False, f"cross-host redirect: {_host(url)} -> {_host(final)}"
        req = linkedin_slug(url)
        if req and linkedin_slug(final) not in ("", req):
            return p, False, f"slug redirect: {req} -> {linkedin_slug(final)}"
    if expect is not None and not name_matches(p.get_all_text()[:120], expect):
        return p, False, f"page does not name {expect!r}"
    return p, True, "ok"
