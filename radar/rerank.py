"""Semantic re-rank of borderline roles using local Claude Code (headless, no API key).
Runs in the LOCAL digest only (not the cloud poller). Promotes/demotes by true fit
so oddly-titled great roles surface and keyword-matching duds sink."""
import json, os, subprocess, shutil

CLAUDE = os.path.expanduser("~/.local/bin/claude")
if not os.path.exists(CLAUDE):
    CLAUDE = shutil.which("claude") or "claude"

PROFILE_BLURB = """the operator — your university Business Econ, class of 2028. Eligible ONLY for internships,
fellowships, co-ops, undergrad programs (NOT full-time/new-grad/senior).
Operator profile: 2x co-founder/COO (1 exit), GTM + business operations, consulting (MLT Fellow),
some product. Terms wanted: Fall 2026, Winter/Spring 2027, Summer 2027; will take a gap quarter for full-time internships.
Strong interest, in rough priority: defense tech & national security (Palantir/Anduril/Saronic type),
physical AI & robotics, frontier hard tech (space, energy, advanced manufacturing), frontier AI labs,
VC/American Dynamism, intel/gov (CIA/IQT/DIU). ALSO any sector — incl. SaaS — IF the company is a cool
idea at Series C or a recent $60M+ (ideally $100M+) raise. Best-fit role types: Deployment Strategist/
Forward-Deployed, Chief of Staff/Founder's Associate/BizOps, GTM/BD, Product, Strategy/Consulting, VC investment."""

def _prompt(batch):
    roles = [{"i": i, "company": r.get("company", ""), "title": r.get("title", ""),
              "location": r.get("location", ""), "dept": r.get("department", "")}
             for i, r in enumerate(batch)]
    return (f"{PROFILE_BLURB}\n\nRate each role 0-100 for TRUE fit to the operator (eligibility + interest + "
            f"career value). 0-30 wrong/ineligible, 40-60 plausible, 70-85 strong, 90+ dream. "
            f"Be strict on eligibility (kill full-time/senior). Reward cool Series-C/well-funded companies even if SaaS.\n\n"
            f"ROLES:\n{json.dumps(roles)}\n\n"
            f"Return ONLY a JSON array: [{{\"i\":<idx>,\"fit\":<0-100>,\"why\":\"<=10 words\"}}]. No prose.")

def rerank(items, band=(40, 82), batch_size=20, timeout=120):
    """Re-score items whose keyword score is in the borderline band. Mutates & returns items.
    Degrades gracefully: on any failure the keyword score stands."""
    idx = [i for i, r in enumerate(items) if band[0] <= r.get("score", 0) <= band[1]]
    for s in range(0, len(idx), batch_size):
        chunk = idx[s:s + batch_size]
        batch = [items[i] for i in chunk]
        try:
            out = subprocess.run([CLAUDE, "-p", _prompt(batch), "--output-format", "text"],
                                 capture_output=True, text=True, timeout=timeout)
            txt = out.stdout.strip()
            js = txt[txt.find("["):txt.rfind("]") + 1]
            for v in json.loads(js):
                r = batch[int(v["i"])]
                r["kw_score"] = r["score"]
                r["score"] = int(v["fit"])
                r["rerank_why"] = v.get("why", "")
        except Exception as ex:
            print(f"[warn] rerank batch failed, keeping keyword scores: {ex}")
    return items
