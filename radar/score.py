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
    # Full country list, not the hand-typed partial one it replaced. The original omitted
    # Estonia, Uzbekistan, Latvia, Lithuania, Serbia, Croatia, Bulgaria, Slovakia,
    # Pakistan and Bangladesh among others, so postings there passed the US-only gate
    # silently. Found 2026-08-09 when the LLM eligibility pass caught a Tallinn role and
    # a Tashkent role the regex had waved through -- a model compensating for a
    # deterministic bug is a signal to fix the deterministic layer, not to lean on it.
    r"\bafghanistan\b", r"\balbania\b", r"\balgeria\b", r"\bandorra\b", r"\bangola\b", r"\bargentina\b",
    r"\barmenia\b", r"\baustralia\b", r"\baustria\b", r"\bazerbaijan\b", r"\bbahamas\b", r"\bbahrain\b",
    r"\bbangladesh\b", r"\bbarbados\b", r"\bbelarus\b", r"\bbelgium\b", r"\bbelize\b", r"\bbenin\b",
    r"\bbhutan\b", r"\bbolivia\b", r"\bbosnia\b", r"\bbotswana\b", r"\bbrazil\b", r"\bbrunei\b",
    r"\bbulgaria\b", r"\bburkina\b", r"\bburundi\b", r"\bcambodia\b", r"\bcameroon\b", r"\bcanada\b",
    r"\bchile\b", r"\bchina\b", r"\bcolombia\b", r"\bcongo\b", r"\bcroatia\b",
    r"\bcosta[ .-]?rica\b", r"\bcuba\b", r"\bcyprus\b", r"\bczechia\b", r"\bczech\b", r"\bdenmark\b", r"\bdjibouti\b",
    r"\bdominican?\b", r"\becuador\b", r"\begypt\b", r"\bel[ .-]?salvador\b", r"\bestonia\b", r"\beswatini\b",
    r"\bethiopia\b", r"\bfiji\b", r"\bfinland\b", r"\bfrance\b", r"\bgabon\b", r"\bgambia\b",
    r"\bgermany\b", r"\bghana\b", r"\bgreece\b", r"\bgrenada\b", r"\bguatemala\b",
    r"\bguyana\b", r"\bhaiti\b", r"\bhonduras\b", r"\bhungary\b", r"\biceland\b",
    r"\bindia\b", r"\bindonesia\b", r"\biran\b", r"\biraq\b", r"\bireland\b", r"\bisrael\b",
    r"\bitaly\b", r"\bjamaica\b", r"\bjapan\b", r"\bkazakhstan\b", r"\bkenya\b",
    r"\bkosovo\b", r"\bkuwait\b", r"\bkyrgyzstan\b", r"\blaos\b", r"\blatvia\b", 
    r"\blesotho\b", r"\bliberia\b", r"\blibya\b", r"\bliechtenstein\b", r"\blithuania\b", r"\bluxembourg\b",
    r"\bmadagascar\b", r"\bmalawi\b", r"\bmalaysia\b", r"\bmaldives\b", r"\bmali\b", 
    r"\bmauritania\b", r"\bmauritius\b", r"\bmoldova\b", r"\bmonaco\b", r"\bmongolia\b",
    r"\bmontenegro\b", r"\bmorocco\b", r"\bmozambique\b", r"\bmyanmar\b", r"\bnamibia\b", r"\bnepal\b",
    r"\bnetherlands\b", r"\bnew[ .-]?zealand\b", r"\bnicaragua\b", r"\bnigeria\b", r"\bnorth[ .-]?macedonia\b",
    r"\bnorway\b", r"\boman\b", r"\bpakistan\b", r"\bpanama\b", r"\bpapua\b",
    r"\bparaguay\b", r"\bphilippines\b", r"\bpoland\b", r"\bportugal\b", r"\bqatar\b",
    r"\bromania\b", r"\brussia\b", r"\brwanda\b", r"\bsaudi\b", r"\bsenegal\b", r"\bserbia\b",
    r"\bseychelles\b", r"\bsierra[ .-]?leone\b", r"\bsingapore\b", r"\bslovakia\b", r"\bslovenia\b", r"\bsomalia\b",
    r"\bsouth[ .-]?africa\b", r"\bsouth[ .-]?korea\b", r"\bsouth[ .-]?sudan\b", r"\bspain\b", r"\bsri[ .-]?lanka\b", r"\bsudan\b",
    r"\bsuriname\b", r"\bsweden\b", r"\bswitzerland\b", r"\bsyria\b", r"\btaiwan\b", r"\btajikistan\b",
    r"\btanzania\b", r"\bthailand\b", r"\btogo\b", r"\btrinidad\b", r"\btunisia\b", r"\bturkey\b",
    r"\bturkiye\b", r"\bturkmenistan\b", r"\buganda\b", r"\bukraine\b", r"\bunited[ .-]?arab[ .-]?emirates\b", r"\bunited[ .-]?kingdom\b",
    r"\buruguay\b", r"\buzbekistan\b", r"\bvanuatu\b", r"\bvenezuela\b", r"\bvietnam\b", r"\byemen\b",
    r"\bzambia\b", r"\bzimbabwe\b", r"\bengland\b", r"\bscotland\b", r"\bwales\b", r"\bnorthern[ .-]?ireland\b",
    r"\bGBR\b", r"\bDEU\b", r"\bFRA\b", r"\bESP\b", r"\bITA\b", r"\bNLD\b", r"\bCHE\b", r"\bPOL\b", r"\bBRA\b", r"\bMEX\b", r"\bIND\b", r"\bCHN\b", r"\bJPN\b", r"\bKOR\b", r"\bSGP\b",
    r"\bAUS\b", r"\bISR\b", r"\bUAE\b", r"\bCAN\b", r"\bEST\b", r"\bLVA\b", r"\bLTU\b", r"\bUZB\b", r"\bPAK\b", r"\bBGD\b", r"\bPHL\b", r"\bIDN\b", r"\bMYS\b", r"\bTHA\b", r"\bVNM\b",
    r"\bZAF\b", r"\bNGA\b", r"\bKEN\b", r"\bEGY\b", r"\bTUR\b", r"\bARG\b", r"\bCHL\b", r"\bCOL\b", r"\bPER\b", r"\bNZL\b", r"\bIRL\b", r"\bSWE\b", r"\bNOR\b", r"\bDNK\b", r"\bFIN\b",
    r"\bEMEA\b", r"\bAPAC\b", r"\bLATAM\b", r"\bEurope\b", r"\bU\.?K\.?\b",
]# Bare city names (no country given). Checked only AFTER a US signal is ruled out,
# so "Milan, TN" stays a US role while a bare "Milano" does not. Prefixes, not whole
# words, so native spellings match (Milano/Milan, Torino/Turin, Roma/Rome).
_FOREIGN_CITY = [
    # AMBIGUOUS: each of these is also a US state or town (Georgia; Lebanon PA; Jordan MN;
    # Peru IN; Mexico MO; Palestine TX). They live here, NOT in _FOREIGN_COUNTRY, because this
    # list is consulted only after an explicit US signal has been ruled out -- so "Georgia,
    # United States" and "Mexico, MO" survive while a bare "Tbilisi, Georgia" does not.
    r"\bgeorgia(?!,? ?(us|usa|united states|[A-Z]{2}\b))", r"\blebanon\b", r"\bjordan\b",
    r"\bperu\b", r"\bmexico\b", r"\bpalestine\b", r"\bchad\b", r"\bniger\b",
    r"\bguinea\b", r"\bmalta\b",
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
    # Bare-city batch 2 (2026-08-09, NEXT.md item 5): capitals/hubs with no notable US
    # namesake. Deliberately ABSENT because a real US city owns the bare name: St
    # Petersburg (FL), Victoria (TX), Wellington (FL) — those residuals belong to the
    # eligibility joint. Moscow ID / Glasgow KY / Belfast ME are small enough that the US
    # ones always ship with a state, so the bare name means the foreign city.
    r"\btashkent\b", r"\bankara\b", r"\baccra\b", r"\briyadh\b", r"\bjeddah\b", r"\bmanama\b",
    r"\bhong kong\b", r"\bkarachi\b", r"\blahore\b", r"\bislamabad\b", r"\bdhaka\b",
    r"\bcolombo\b", r"\bkathmandu\b", r"\bkyiv\b", r"\bkiev\b", r"\bmoscow\b", r"\bminsk\b",
    r"\briga\b", r"\bvilnius\b", r"\btallinn\b", r"\bbelgrade\b", r"\bzagreb\b", r"\bsofia\b",
    r"\bsarajevo\b", r"\bskopje\b", r"\btirana\b", r"\bbratislava\b", r"\bljubljana\b",
    r"\bporto\b", r"\bbilbao\b", r"\blyon\b", r"\bmarseille\b", r"\btoulouse\b",
    r"\bhamburg\b", r"\bfrankfurt\b", r"\bcologne\b", r"\bk[öo]ln\b", r"\bstuttgart\b",
    r"\bd[üu]sseldorf\b", r"\bleipzig\b", r"\bdresden\b", r"\bantwerp\b", r"\bghent\b",
    r"\beindhoven\b", r"\bthe hague\b", r"\butrecht\b", r"\bg[öo]teborg\b", r"\bgothenburg\b",
    r"\bmalm[öo]\b", r"\baarhus\b", r"\bespoo\b", r"\btampere\b", r"\breykjavik\b",
    r"\btunis\b", r"\balgiers\b", r"\baddis ababa\b", r"\bkampala\b", r"\bdar es salaam\b",
    r"\bkigali\b", r"\bdakar\b", r"\babidjan\b", r"\bquito\b", r"\bcaracas\b",
    r"\bmontevideo\b", r"\basunci[óo]n\b", r"\bla paz\b", r"\btegucigalpa\b", r"\bmanagua\b",
    r"\bhavana\b", r"\bsanto domingo\b", r"\bedinburgh\b", r"\bglasgow\b", r"\bleeds\b",
    r"\bcardiff\b", r"\bbelfast\b", r"\bquebec\b", r"\bmississauga\b", r"\bsaskatoon\b",
    r"\bchristchurch\b", r"\badelaide\b", r"\bcanberra\b", r"\bhobart\b",
    # Canadian province + NZ codes, comma-anchored AND end/comma-terminated so prose like
    # "Chicago, on-site" cannot match: catches "Waterloo, ON", "Halifax, NS", "Victoria, BC".
    r",\s*(on|bc|ab|sk|mb|ns|nb|qc|pe|nl|yt|nt|nu)(?=$|,)",
    r",\s*nz(?=$|,)",
]
_US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
              "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
_US = [r"\bunited states\b", r"\bU\.?S\.?A\b", r"\bUSA\b", r"\bUS\b(?=$|[,\s\)])",
       r"\bremote\s*[-–,(]?\s*(us|usa|united states)\b",
       # NOTE: "georgia" is deliberately absent from this alternation -- it is both a US state and a
       # country, and listing it here made "Tbilisi, Georgia" match as a positive US signal.
       # Atlanta still passes via ", GA"; "Georgia, United States" via "united states".
       r"\b(california|texas|new york|florida|washington|massachusetts|illinois|virginia|"
       r"colorado|arizona|ohio|michigan|oregon|nevada|utah|maryland|"
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
    from radar.tiers import name_match
    cl = company.lower()
    for industry, names in profile.get("industries", {}).items():
        if any(name_match(n, cl) for n in names):
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
        from radar.tiers import name_match
        cl = company.lower()
        for fk, fv in funded.items():
            if fk and name_match(fk, cl):
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
    # a T1/T2 company to data/dropped_unmatched.jsonl (local machine only; gitignored, so
    # cloud-runner drops are ephemeral). Mining it for title variants is a MANUAL agent ask
    # today — no automated pass exists. Proposals go to a human; nothing is auto-added.
    if best_cluster is None:
        if band <= 2:
            _log_unmatched(company, title, posting.get("url", ""), band)
        return None, None

    score = min(round(best_weight + tier_score + bonus + offcycle_pts + fund_pts), 100)
    # Angles are OFF when `angles` is absent/empty in profile.yaml — there is no pause flag.
    # While off, angle_pitch is NOT in the brief at all: a stale consumer that assumes the
    # key raises KeyError instead of rendering blank text into an email (poll.py shipped a
    # 'Lead with your `` angle:' line for a day when this was "" behind an angles_paused flag).
    angle_key = profile["clusters"][best_cluster]["angle"] if best_cluster else "founder"
    brief = {
        "cluster": best_cluster or ("recent-raise" if fund_hit else "unmatched-title"),
        "tier": tier_name,
        "angle": angle_key,
        "matched_keywords": [m.strip("\\b") for m in matched_bonus],
        "offcycle": offcycle,
    }
    _angles = profile.get("angles") or {}
    if _angles.get(angle_key):
        brief["angle_pitch"] = _angles[angle_key]
    if fund_hit:
        brief["funding"] = f"raised ${fund_hit.get('amount',0)/1e6:.0f}M ({fund_hit.get('date','recent')})"
    brief["industry"] = classify_industry(company, posting.get("source", ""), profile)
    return score, brief
