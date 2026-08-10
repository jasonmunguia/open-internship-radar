"""Company tier bands from observable signals — replaces the hand-typed allowlist.

WHY THIS EXISTS
A three-list allowlist can only answer "did someone type this company?", so every company
nobody typed collapsed to `unknown` (+10) and never alerted. That silently hid real
mid-tier employers. Bands are computed instead, from three independent signals:

    followers   LinkedIn brand reach  -> proxy for "would a recruiter recognise this"
    employees   operational size      -> catches big-but-unglamorous (Trimble, Deere)
    funding     capital raised        -> catches young + serious (Etched: 41k followers, $300M)

BAND = BEST OF THE THREE, never an average. Etched is T4 on followers and T2 on funding,
so it is T2. A company only lands T4 if it fails all three.

Thresholds calibrated 2026-08-08 against 32 known companies; see docs/CALIBRATION.md.

DETERMINISTIC SPINE / LLM JOINT
Fetch + parse + band assignment are pure Python and run in GitHub Actions with no model.
Claude is invoked for exactly one thing: resolving a company's LinkedIn slug when the
guesses fail or resolve to the wrong company. That is judgment, and regex cannot do it.
"""
import json, os, re, time

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "company_tiers.json")
CACHE_TTL_DAYS = 180                     # brand/headcount move slowly; refetch twice a year
BAND_POINTS = {1: 40, 2: 30, 3: 20, 4: 0}

#            band:  (followers, employees, raise_usd)
THRESHOLDS = {1: (5_000_000, 100_000, None),
              2: (800_000, 25_000, 250_000_000),
              3: (100_000, 1_000, 25_000_000)}

# Funding CANNOT reach T1 (None above). Capital raised proves a company is real and serious —
# a floor argument — not that it is a marquee logo. ServiceTitan raised $1.4B pre-IPO and was
# briefly banded T1 alongside Google on that alone. T1 comes from reach, headcount, or the
# override list only.

# Legacy hand lists stay authoritative as an OVERRIDE: prestige that signals cannot see
# (Palantir and Anduril are T2 on followers alone; MBB and the IC agencies have no
# meaningful follower/headcount signal at all).
OVERRIDE_BAND = {"dream": 1, "target": 2, "watch": 3, "gov": 1}


def _num(s):
    s = s.replace(",", "").strip()
    mult = {"k": 1e3, "m": 1e6}.get(s[-1:].lower())
    return float(s[:-1]) * mult if mult else float(s)


def band_from_signals(followers=None, employees=None, raise_usd=None):
    """Best (lowest-numbered) band any single signal supports. 4 = below the floor."""
    for band in (1, 2, 3):
        f_min, e_min, r_min = THRESHOLDS[band]
        if (followers or 0) >= f_min or (employees or 0) >= e_min:
            return band
        if r_min is not None and (raise_usd or 0) >= r_min:
            return band
    return 4


def slug_candidates(company):
    """LinkedIn slug guesses, most-likely first. Real misses go to the Claude joint."""
    base = re.sub(r"[^a-z0-9 ]", "", company.lower()).strip()
    squashed = base.replace(" ", "")
    hyphen = base.replace(" ", "-")
    stripped = re.sub(r"\b(inc|llc|corp|corporation|technologies|technology|labs|ai|industries)\b",
                      "", base).strip().replace(" ", "-")
    out = []
    for c in (hyphen, squashed, stripped, f"{hyphen}-technologies", f"{hyphen}-industries", f"{hyphen}-inc"):
        if c and c not in out:
            out.append(c)
    return out


def scrape_linkedin(company, sleep=0.6):
    """(followers, employees, resolved_slug) or (None, None, None). Logged-out public page,
    no auth, no credits. Scrapling handles the anti-bot layer.

    Identity validation (redirect + name gates) lives in radar/fetch.py — the shared
    validated_fetch that encodes "a 404 is safe; a wrong 200 is dangerous"."""
    from radar.fetch import validated_fetch
    for slug in slug_candidates(company):
        p, ok, _why = validated_fetch(f"https://www.linkedin.com/company/{slug}/",
                                      expect=company)
        if ok:
            text = p.get_all_text()
            f = re.findall(r"([\d][\d,.]*[KMkm]?)\s*followers", text)
            e = re.findall(r"([\d][\d,.]*[KMkm]?)\s*employees", text)
            if f:
                return (_num(f[0]), _num(e[0]) if e else None, slug)
        time.sleep(sleep)                       # politeness: hundreds of companies per backfill
    return (None, None, None)


def load_cache():
    try:
        with open(CACHE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)


# One suffix list, shared with the name gate in radar/fetch.py — two copies would drift.
from radar.fetch import SUFFIXES as _SUFFIXES

# Divisions inherit the parent's band: an Uber Freight PM intern is an Uber-caliber seat.
_PARENT = {"alphabet": "google", "metaplatforms": "meta", "square": "block",
           "facebook": "meta", "xdevelopment": "google", "waymo": "google",
           "awsamazonwebservices": "amazon", "amazonwebservices": "amazon"}


def _key(company):
    return re.sub(r"[^a-z0-9]", "", company.lower())


def _key_candidates(company):
    """Cache keys to try, most specific first. Resolves 'Uber Freight' -> 'uber' so a
    division inherits its parent's band instead of falling through to `pending`."""
    k = _key(company)
    out = [k, _PARENT.get(k, "")]
    words = re.sub(r"[^a-z0-9 ]", "", company.lower()).split()
    for i in range(len(words) - 1, 0, -1):          # progressively drop trailing words
        if words[i] in _SUFFIXES or i == len(words) - 1:
            cand = _key(" ".join(words[:i]))
            out.append(cand)
            out.append(_PARENT.get(cand, ""))
    return [c for i, c in enumerate(out) if c and c not in out[:i]]


def override_band(company, profile):
    """Hand lists win over signals — they encode prestige no metric captures."""
    cl = company.lower()
    for tname, names in (profile.get("tiers") or {}).items():
        if tname in OVERRIDE_BAND and any(str(t).lower() in cl for t in names):
            return OVERRIDE_BAND[tname]
    return None


def band_for(company, profile, funded=None, allow_fetch=False, cache=None):
    """Band + points for a company. Cache-first; only fetches when explicitly allowed
    (the poller must never block on the network — the nightly backfill does the fetching).

    Returns (band:int, points:int, source:str). source is one of
    override | cache | fetched | funded | pending — `pending` means unseen and not yet
    enriched, and it is deliberately scored as T4 so an unknown company stays silent
    until it has actually been measured."""
    cache = load_cache() if cache is None else cache
    ob = override_band(company, profile)
    if ob:
        return ob, BAND_POINTS[ob], "override"

    raise_usd = (funded or {}).get("amount") if funded else None
    if not raise_usd:
        # Fall back to the PERSISTENT Form D history, not just the rolling 14-day window.
        # Without this the funding signal only fires for companies that raised this month,
        # which is why MaintainX (T4 on 58k followers) and Anduril (T3) were mis-banded.
        try:
            from radar.funding_history import lookup as _fund_lookup
            hit = _fund_lookup(company)
            raise_usd = hit and hit.get("amount")
        except Exception:
            pass
    for k in _key_candidates(company):
        hit = cache.get(k)
        if hit and not hit.get("needs_resolution"):
            # A cached band can go stale the moment a company raises. Funding is checked on
            # every read and the better band wins, so a fresh round promotes immediately
            # instead of waiting out the 180-day TTL.
            b = min(hit["band"], band_from_signals(None, None, raise_usd))
            return b, BAND_POINTS[b], "cache" if k == _key(company) else "cache:parent"
    k = _key(company)
    if allow_fetch:
        f, e, slug = scrape_linkedin(company)
        b = band_from_signals(f, e, raise_usd)
        cache[k] = {"company": company, "followers": f, "employees": e, "slug": slug,
                    "raise_usd": raise_usd, "band": b, "ts": int(time.time()),
                    # no slug survived the name gate -> hand to the Claude joint, do not guess
                    # Name-collision guard: the gate catches wrong slugs and wrong names, but
                    # NOT two real companies sharing a name. linkedin.com/company/etched is a
                    # 340-follower firm, not the chip startup that raised $300M. If the money
                    # says serious and the page says tiny, trust neither — send it to Claude.
                    "needs_resolution": slug is None or bool(
                        raise_usd and raise_usd >= 25_000_000 and (f or 0) < 25_000)}
        save_cache(cache)
        return b, BAND_POINTS[b], "fetched"

    if raise_usd:
        b = band_from_signals(None, None, raise_usd)
        return b, BAND_POINTS[b], "funded"
    return 4, 0, "pending"


def unresolved(cache=None):
    """Companies whose slug never passed the name gate — the Claude joint's work queue."""
    cache = load_cache() if cache is None else cache
    return [v["company"] for v in cache.values() if v.get("needs_resolution")]


def resolve_slug_via_search(company, engines=("duckduckgo", "bing")):
    """Fallback when every slug guess fails the gate. LinkedIn's own 301 is untrustworthy
    (it invents a nearest match on a foreign host), so ask a search engine which company
    page actually belongs to this name and take the slug from the result URL.

    Deterministic — no model. Claude is only reached if this fails too."""
    from radar.fetch import validated_fetch
    urls = {"duckduckgo": "https://html.duckduckgo.com/html/?q={q}",
            "bing": "https://www.bing.com/search?q={q}"}
    q = f"{company} linkedin company".replace(" ", "+")
    for eng in engines:
        try:
            # allow_redirect_host: search endpoints bounce between their own hosts and we
            # are reading result LINKS, not asserting the page's identity.
            p, ok, _why = validated_fetch(urls[eng].format(q=q), allow_redirect_host=True)
            if not ok:
                continue
            hits = re.findall(r"linkedin\.com/company/([a-z0-9\-_.]+)", p.get_all_text() + str(p.body), re.I)
            seen = []
            for h in hits:
                h = h.strip("/.").lower()
                if h and h not in seen and not h.startswith(("about", "setup", "showcase")):
                    seen.append(h)
            for slug in seen[:5]:
                f, e, ok = _try_slug(slug, company)
                if ok:
                    return f, e, slug
        except Exception:
            pass
        finally:
            time.sleep(0.8)
    return (None, None, None)


def _try_slug(slug, company):
    """Fetch one slug through both identity gates (radar/fetch.py).
    Returns (followers, employees, passed)."""
    from radar.fetch import validated_fetch
    p, ok, why = validated_fetch(f"https://www.linkedin.com/company/{slug}/", expect=company)
    if not ok:
        if p is not None and "status" not in why:     # wrong-200: log WHY, a miss must not
            print(f"[tiers] rejected {slug!r} for {company!r}: {why}")   # look like a 404
        return (None, None, False)
    text = p.get_all_text()
    f = re.findall(r"([\d][\d,.]*[KMkm]?)\s*followers", text)
    e = re.findall(r"([\d][\d,.]*[KMkm]?)\s*employees", text)
    return ((_num(f[0]) if f else None), (_num(e[0]) if e else None), bool(f))


def resolve(company):
    """Full deterministic chain: slug guesses -> search-engine slug lookup.
    Anything still unresolved is queued for the Claude joint via needs_resolution."""
    f, e, slug = scrape_linkedin(company)
    if slug:
        return f, e, slug, "guess"
    f, e, slug = resolve_slug_via_search(company)
    return (f, e, slug, "search") if slug else (None, None, None, "unresolved")


def resolve_unresolved_with_claude(limit=25, timeout=900):
    """Consume the needs_resolution queue. Deterministic resolution already failed twice here
    (slug guesses, then a search-engine lookup), so what is left needs judgment: which of
    several same-named companies is the real one, or what a company renamed itself to.

    Claude gets Scrapling and web search and must return STRICT JSON mapping company -> slug.
    Every returned slug is then re-verified through the SAME gates as any other fetch — a
    model's answer earns no trust the deterministic path would not have gotten."""
    import json

    from radar.joints import run_joint
    cache = load_cache()
    pending = [v["company"] for v in cache.values() if v.get("needs_resolution")][:limit]
    if not pending:
        return {"resolved": 0, "pending": 0}

    prompt = (
        "For each company below, find its REAL LinkedIn company-page slug (the segment in "
        "linkedin.com/company/<slug>). You have Scrapling "
        "(`from scrapling.fetchers import StealthyFetcher`) and web search.\n\n"
        "Beware two traps that already broke the deterministic resolver:\n"
        "1. linkedin.com/company/uber 301-redirects to a UK creative agency. Verify the page "
        "you land on is actually the company asked for.\n"
        "2. Name collisions are real: linkedin.com/company/etched is a ~340-follower firm, NOT "
        "the AI-chip startup. Cross-check headcount and description against what you know of "
        "the company.\n\n"
        "Return ONLY JSON: {\"Company Name\": \"slug\"}. Omit any company you cannot verify — "
        "an omission is correct, a guess is not.\n\nCOMPANIES:\n" + "\n".join(pending))
    try:
        out = run_joint("slug_resolve", prompt, timeout=timeout).stdout
        body = out.split("```")[1].lstrip("json").strip() if "```" in out else out.strip()
        mapping = json.loads(body[body.find("{"):body.rfind("}") + 1])
    except Exception as ex:
        return {"resolved": 0, "pending": len(pending), "error": str(ex)[:120]}

    resolved = 0
    for company, slug in (mapping or {}).items():
        f, e, ok = _try_slug(str(slug).strip("/ "), company)   # re-verified, not trusted
        if not ok:
            continue
        raise_usd = None
        try:
            from radar.funding_history import lookup as _fl
            hit = _fl(company)
            raise_usd = hit and hit.get("amount")
        except Exception:
            pass
        b = band_from_signals(f, e, raise_usd)
        cache[_key(company)] = {"company": company, "followers": f, "employees": e, "slug": slug,
                                "raise_usd": raise_usd, "band": b, "ts": int(time.time()),
                                "needs_resolution": False, "resolved_by": "claude"}
        resolved += 1
    save_cache(cache)
    return {"resolved": resolved, "pending": len(pending) - resolved}


def backfill(companies, cache=None, limit=None):
    """Enrich a list of company names. This is the long Scrapling run that turns `pending`
    (silent, T4) into a real band. Cache-first, so re-running is cheap and resumable."""
    cache = load_cache() if cache is None else cache
    todo = [c for c in dict.fromkeys(companies)
            if _key(c) not in cache and not override_band(c, {"tiers": {}})][:limit]
    done = 0
    for c in todo:
        f, e, slug, how = resolve(c)
        raise_usd = None
        try:
            from radar.funding_history import lookup as _fl
            hit = _fl(c)
            raise_usd = hit and hit.get("amount")
        except Exception:
            pass
        b = band_from_signals(f, e, raise_usd)
        cache[_key(c)] = {"company": c, "followers": f, "employees": e, "slug": slug,
                          "raise_usd": raise_usd, "band": b, "ts": int(time.time()),
                          "needs_resolution": slug is None, "how": how}
        done += 1
        if done % 20 == 0:
            save_cache(cache)
    save_cache(cache)
    return {"enriched": done, "cached_total": len(cache)}
