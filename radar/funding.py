"""SEC Form D funding radar: surface companies that just raised >= $50M."""
import json, re, time, urllib.request
from datetime import date, timedelta

FUND_INDUSTRIES = {"Pooled Investment Fund", "Hedge Fund", "Private Equity Fund",
                   "Venture Capital Fund", "Real Estate", "Commercial Banking",
                   "Insurance", "Investing", "Other Banking and Financial Services"}

from radar.settings import USER_AGENT

UA = {"User-Agent": USER_AGENT}

def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")

def recent_big_form_ds(days=1, min_amount=50_000_000, cap=150):
    start = (date.today() - timedelta(days=days)).isoformat()
    end = date.today().isoformat()
    url = (f"https://efts.sec.gov/LATEST/search-index?q=%22offering%22&forms=D"
           f"&startdt={start}&enddt={end}")
    try:
        hits = json.loads(_get(url)).get("hits", {}).get("hits", [])
    except Exception as ex:
        # Never swallow this silently. EDGAR full-text search rejects wide date ranges and
        # rate-limits, and a bare `return []` makes a broken endpoint look exactly like "no
        # companies raised money" — the failure reads as a valid answer. Observed 2026-08-08:
        # days=1 returned 1 hit, days=7 returned 0.
        import sys as _s
        print(f"[warn] EDGAR query failed ({start}..{end}): {type(ex).__name__}: {ex}", file=_s.stderr)
        return []
    out = []
    for h in hits[:cap]:
        try:
            src = h["_source"]
            adsh = src["adsh"].replace("-", "")
            cik = src["ciks"][0].lstrip("0")
            xml = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/primary_doc.xml")
            amt_m = re.search(r"<totalOfferingAmount>(\d+)</totalOfferingAmount>", xml)
            sold_m = re.search(r"<totalAmountSold>(\d+)</totalAmountSold>", xml)
            name_m = re.search(r"<entityName>([^<]+)</entityName>", xml)
            ind_m = re.search(r"<industryGroupType>([^<]+)</industryGroupType>", xml)
            amt = int(sold_m.group(1)) if sold_m else (int(amt_m.group(1)) if amt_m else 0)
            industry = ind_m.group(1) if ind_m else "?"
            company = name_m.group(1) if name_m else ""
            # Most big Form D filings are investment vehicles raising a FUND, not operating
            # companies raising a round — they hire nobody and would flood the radar with noise.
            # The SEC's own industryGroupType catches ~90% of them; the name patterns catch the rest.
            is_fund = (industry in FUND_INDUSTRIES
                       or re.search(r"\b(fund|l\.?p\.?|scsp|sicav|trust|partners|capital|"
                                    r"realty|advisors|holdings)\b", company, re.I))
            if amt >= min_amount and company and not is_fund:
                out.append({"company": company, "amount": amt,
                            "industry": industry,
                            "filing": f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}"})
            time.sleep(0.15)
        except Exception:
            continue
    return sorted(out, key=lambda x: -x["amount"])

if __name__ == "__main__":
    for r in recent_big_form_ds(days=2):
        print(f"${r['amount']/1e6:.0f}M  {r['company']}  ({r['industry']})")
