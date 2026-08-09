"""Rule-based fit scoring against config/profile.yaml."""
import json
import os
import re
import time

def _any(patterns, text):
    return [p for p in patterns if re.search(p, text, re.I)]

# ---------------------------------------------------------------- US-only gate
# the operator can only take US-based roles. Location strings vary wildly by ATS
# ("United States", "Austin, TX", "Sao Paulo, BRA", "Toronto, ON, Canada", "").
# Rule: an explicit foreign signal rejects; an explicit US signal accepts;
# anything unreadable (blank, "Remote", bare city) is KEPT — the company set is
# US-centric, so silence is far more likely to be a US role than a foreign one,
# and dropping on missing data would lose good postings.
# Countries/regions are unambiguous -> they outrank everything.
_FOREIGN_COUNTRY = [
    r"\bcanada\b", r"\bCAN\b", r"\bunited kingdom\b", r"\bengland\b", r"\bscotland\b",
    r"\bwales\b", r"\bireland\b", r"\bGBR\b", r"\bU\.?K\.?\b",
    r"\bgermany\b", r"\bDEU\b", r"\bfrance\b", r"\bFRA\b", r"\bspain\b", r"\bESP\b",
    r"\bitaly\b", r"\bITA\b", r"\bnetherlands\b", r"\bNLD\b", r"\bbelgium\b",
    r"\bswitzerland\b", r"\bCHE\b", r"\bsweden\b", r"\bnorway\b", r"\bdenmark\b",
    r"\bfinland\b", r"\bpoland\b", r"\bPOL\b", r"\bportugal\b", r"\baustria\b",
    r"\bczech\b", r"\bromania\b", r"\bgreece\b", r"\bhungary\b", r"\bukraine\b",
    r"\bbrazil\b", r"\bBRA\b", r"\bmexico\b", r"\bMEX\b", r"\bargentina\b", r"\bchile\b",
    r"\bcolombia\b", r"\bperu\b", r"\bcosta rica\b", r"\bindia\b", r"\bIND\b",
    r"\bchina\b", r"\bCHN\b", r"\bjapan\b", r"\bJPN\b", r"\bkorea\b", r"\bKOR\b",
    r"\bsingapore\b", r"\bSGP\b", r"\bhong kong\b", r"\btaiwan\b", r"\bthailand\b",
    r"\bvietnam\b", r"\bphilippines\b", r"\bindonesia\b", r"\bmalaysia\b",
    r"\baustralia\b", r"\bAUS\b", r"\bnew zealand\b", r"\bisrael\b", r"\bISR\b",
    r"\bunited arab emirates\b", r"\bUAE\b", r"\bqatar\b", r"\bsaudi\b", r"\bturkey\b",
    r"\bturkiye\b", r"\begypt\b", r"\bmorocco\b", r"\bsouth africa\b", r"\bnigeria\b",
    r"\bkenya\b", r"\bEMEA\b", r"\bAPAC\b", r"\bLATAM\b", r"\bEurope\b",
]
# Bare city names (no country given). Checked only AFTER a US signal is ruled out,
# so "Milan, TN" stays a US role while a bare "Milano" does not. Prefixes, not whole
# words, so native spellings match (Milano/Milan, Torino/Turin, Roma/Rome).
_FOREIGN_CITY = [
    r"\blondon\b", r"\bparis\b", r"\bberlin\b", r"\bmunich", r"\bm[üu]nchen",
    r"\bmadrid\b", r"\bbarcelona\b", r"\bsevilla\b", r"\bvalencia\b",
    r"\bmilan", r"\brom[ae]\b", r"\btorino\b", r"\bturin\b", r"\bfirenze\b", r"\bnapoli\b",
    r"\bdublin\b", r"\bamsterdam\b", r"\brotterdam\b", r"\bbrussels\b", r"\bbruxelles\b",
    r"\bz[üu]rich\b", r"\bgeneva\b", r"\bgen[èe]ve\b", r"\bvienna\b", r"\bwien\b",
    r"\bstockholm\b", r"\bcopenhagen\b", r"\boslo\b", r"\bhelsinki\b", r"\blisbon\b",
    r"\blisboa\b", r"\bwarsaw\b", r"\bwarszawa\b", r"\bkrak[óo]w\b", r"\bgliwice\b",
    r"\bprague\b", r"\bpraha\b", r"\bbudapest\b", r"\bbucharest\b", r"\bathens\b",
    r"\btoronto\b", r"\bmontreal\b", r"\bottawa\b", r"\bcalgary\b", r"\bedmonton\b",
    r"\bwinnipeg\b", r"\bvancouver,\s*BC\b", r"\bs[ãa]o paulo\b", r"\brio de janeiro\b",
    r"\bbogot[áa]\b", r"\blima,\s*peru\b", r"\bmexico city\b", r"\bguadalajara\b",
    r"\bmonterrey\b", r"\bbuenos aires\b", r"\bsantiago,\s*chile\b",
    r"\bbengaluru\b", r"\bbangalore\b", r"\bhyderabad\b", r"\bmumbai\b", r"\bnew delhi\b",
    r"\bchennai\b", r"\bpune\b", r"\bgurgaon\b", r"\bgurugram\b", r"\bnoida\b",
    r"\bshanghai\b", r"\bbeijing\b", r"\bshenzhen\b", r"\bguangzhou\b",
    r"\btokyo\b", r"\bosaka\b", r"\bseoul\b", r"\btaipei\b", r"\bsydney\b",
    r"\bmelbourne\b", r"\bbrisbane\b", r"\bperth,\s*", r"\bauckland\b",
    r"\bdubai\b", r"\babu dhabi\b", r"\bdoha\b", r"\btel aviv\b", r"\bhaifa\b",
    r"\bcasablanca\b", r"\bcairo\b", r"\bnairobi\b", r"\blagos\b", r"\bjohannesburg\b",
    r"\bcape town\b", r"\bmanila\b", r"\bjakarta\b", r"\bbangkok\b", r"\bkuala lumpur\b",
    r"\bho chi minh\b", r"\bhanoi\b", r"\bistanbul\b", r"\bnovara\b", r"\bpiedmont\b",
]
_US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
              "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
_US = [r"\bunited states\b", r"\bU\.?S\.?A\b", r"\bUSA\b", r"\bUS\b(?=$|[,\s\)])",
       r"\bremote\s*[-–,(]?\s*(us|usa|united states)\b",
       r"\b(california|texas|new york|florida|washington|massachusetts|illinois|virginia|"
       r"colorado|georgia|arizona|ohio|michigan|oregon|nevada|utah|maryland|"
       r"pennsylvania|minnesota|wisconsin|missouri|tennessee|indiana|alabama|"
       r"nebraska|connecticut|new jersey|north carolina|south carolina|new mexico|"
       r"oklahoma|kansas|iowa|arkansas|louisiana|kentucky|mississippi|idaho|montana|"
       r"wyoming|alaska|hawaii|maine|vermont|new hampshire|rhode island|delaware|"
       r"west virginia|north dakota|south dakota)\b"]
_US += [r",\s*" + st + r"\b" for st in _US_STATES]          # "Austin, TX"

def is_us_location(location, text=""):
    """True unless the posting is clearly outside the US.
    Order matters: an explicit foreign COUNTRY beats everything; then an explicit US
    signal (state/'United States') beats a bare foreign CITY name, so Milan TN survives
    while Milano does not. Unreadable locations are kept — the company set is US-centric."""
    loc = str(location or "").strip()
    if not loc:
        return True                                     # unknown -> keep
    if _any(_FOREIGN_COUNTRY, loc):
        return False                                    # explicit foreign country
    if _any(_US, f"{loc} {text}"):
        return True                                     # explicit US
    if _any(_FOREIGN_CITY, loc):
        return False                                    # bare foreign city
    return True                                         # unreadable -> keep

def classify_industry(company, source, profile):
    cl = company.lower()
    for industry, names in profile.get("industries", {}).items():
        if any(n in cl for n in names):
            return industry
    if source.startswith("usajobs"):
        return "gov"
    if source.startswith(("getro:", "consider:", "speedrun")):
        return "vc_portfolio"
    if source.startswith("github:"):
        return "aggregator"
    return "startup_other"


_UNMATCHED = os.path.join(os.path.dirname(__file__), "..", "data", "dropped_unmatched.jsonl")


def _log_unmatched(company, title, url, band):
    """Titles dropped at T1/T2 companies. Not an error log — a discovery queue: if a strong
    company posts a product role under a name no pattern knows, that name is worth learning."""
    try:
        os.makedirs(os.path.dirname(_UNMATCHED), exist_ok=True)
        with open(_UNMATCHED, "a") as fh:
            fh.write(json.dumps({"company": company, "title": title, "url": url,
                                 "band": band, "ts": int(time.time())}) + "\n")
    except Exception:
        pass                       # discovery telemetry must never break scoring


def score_posting(posting, profile, funded=None, tier_cache=None):
    """funded: optional {company_substr_lower: {amount, date, industry}} from the funding radar.
    A recently well-funded company is auto-promoted and its cluster-gate relaxed
    (the operator's filter is stage+recency, not sector — a cool Series-C/$60M+ co counts even if SaaS).
    posting: {company, title, location, url, source, description?}
    Returns (score, brief_dict) or (None, None) if gated out."""
    title = posting.get("title", "")
    company = posting.get("company", "")
    text = " ".join(str(posting.get(k, "")) for k in ("title", "description", "department", "location"))

    # US-only: the operator cannot take roles based outside the United States.
    if not is_us_location(posting.get("location", ""), posting.get("department", "")):
        return None, None

    gates = profile["scoring"]["gate_patterns"]
    if not _any(gates, title) and not _any(gates, text):
        return None, None

    # eligibility exclusions apply to the title (the operator: internships/fellowships/undergrad only)
    excludes = profile["scoring"].get("exclude_patterns", [])
    if _any(excludes, title):
        return None, None

    best_cluster, best_weight = None, 0
    for name, c in profile["clusters"].items():
        if _any(c["patterns"], title) or _any(c["patterns"], posting.get("department", "")):
            if c["weight"] > best_weight:
                best_cluster, best_weight = name, c["weight"]
    if best_cluster is None:
        # description-level cluster match at half weight
        for name, c in profile["clusters"].items():
            if _any(c["patterns"], text) and c["weight"] / 2 > best_weight:
                best_cluster, best_weight = name, c["weight"] / 2

    # funding-driven promotion: a recently well-funded company (stage+recency filter)
    fund_hit = None
    if funded:
        cl = company.lower()
        for fk, fv in funded.items():
            if fk and fk in cl:
                fund_hit = fv
                break

    # Tier is COMPUTED from observable signals (followers / employees / funding), with the
    # hand lists surviving as an override. See radar/tiers.py for the why and the thresholds.
    # T1 40 | T2 30 | T3 20 | T4 0 -> family weight 40 + T3 20 == 60 == high_fit_threshold,
    # so any of the 7 families at a T3-or-better company alerts, and below T3 stays silent.
    from radar.tiers import band_for
    band, tier_score, tier_src = band_for(company, profile, funded=fund_hit, cache=tier_cache)
    tier_name = f"T{band}" if band < 4 else "unknown"

    fund_pts = 0
    if fund_hit:
        fund_pts = 30
        if tier_name == "unknown":
            tier_name = "funded"

    matched_bonus = _any(profile["bonus_keywords"], text)
    bonus = min(len(matched_bonus) * 5, 15)
    offcycle = bool(_any(profile["offcycle_patterns"], title) or _any(profile["offcycle_patterns"], posting.get("term", "")))
    # Off-cycle no longer scored (2026-08-08 per the operator): a fall/winter/spring co-op ranks EQUAL
    # to summer. `offcycle` stays computed so the digest can still LABEL the term.
    offcycle_pts = 0

    # dream-tier OR recently-funded companies don't need a cluster match (the operator: cool + well-funded counts)
    # A strong company with an unusual title (Figma "Product Research Intern") must not be
    # discarded just because no cluster regex matched — T1/T2 bypass the cluster gate.
    # NO PRESTIGE BYPASS (the operator, 2026-08-08). If the title is not one of the 7 families or a
    # variant doing the same job, it does not ship — a T1 logo does not buy a role onto the
    # apply list. The old dream-tier bypass is gone with it.
    # Consequence, accepted deliberately: title+description regex is now the ONLY route in,
    # so pattern coverage is the single point of failure. Mitigated by logging every drop at
    # a T1/T2 company to data/dropped_unmatched.jsonl, which the nightly Claude pass mines for
    # real title variants and PROPOSES as new patterns. It proposes; it never auto-adds.
    if best_cluster is None:
        if band <= 2:
            _log_unmatched(company, title, posting.get("url", ""), band)
        return None, None

    score = min(round(best_weight + tier_score + bonus + offcycle_pts + fund_pts), 100)
    # Briefs stay blind to the operator's history while angles are paused — he picks the resume.
    angles_off = profile.get("angles_paused", False)
    angle_key = profile["clusters"][best_cluster]["angle"] if best_cluster else "founder"
    brief = {
        "cluster": best_cluster or ("recent-raise" if fund_hit else "unmatched-title"),
        "tier": tier_name,
        "angle": angle_key,
        "angle_pitch": "" if angles_off else profile["angles"].get(angle_key, ""),
        "matched_keywords": [m.strip("\\b") for m in matched_bonus],
        "offcycle": offcycle,
    }
    if fund_hit:
        brief["funding"] = f"raised ${fund_hit.get('amount',0)/1e6:.0f}M ({fund_hit.get('date','recent')})"
    brief["industry"] = classify_industry(company, posting.get("source", ""), profile)
    return score, brief
