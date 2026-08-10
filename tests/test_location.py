"""Regression tests for the US-only location gate.

Runs in CI before every poll. If someone (human or model) loosens the filter and
foreign roles start leaking into the operator's inbox again, the workflow FAILS LOUDLY
instead of quietly emailing him jobs in Milan.

Run locally:  python3 -m tests.test_location
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar.score import is_us_location as us

MUST_KEEP = [
    # plain US
    "United States", "New York, NY, United States", "Austin, TX", "San Jose, CA",
    "Los Angeles, CA, United States", "Cincinnati, Ohio", "Honolulu, HI",
    "North Reading, Massachusetts, USA", "Westboro, Wisconsin, USA",
    "Arlington, Virginia, USA", "Kenosha, WI, United States",
    "Costa Mesa, California, United States", "Dallas, TX - Headquarters, United States of America",
    # US cities that collide with foreign city names — the subtle case
    "Milan, TN", "Milan, MI", "Vancouver, WA", "Paris, TX", "Berlin, NH",
    "Athens, GA", "Naples, FL", "Toledo, OH", "Rome, NY", "Dublin, OH",
    # unreadable / company-internal -> keep rather than lose a real role
    "", "Remote", "Flexible - Any SpaceX Site", "Sunnyvale", "North America",
]

MUST_REJECT = [
    # explicit countries / codes
    "Toronto, ON, Canada", "Sao Paulo, Sao Paulo, BRA", "United Kingdom",
    "Bengaluru, Karnataka, India", "Doha, Qatar", "Madrid, Spain", "Shanghai, CHN",
    "Novara, Piedmont, ITA", "Gliwice, Silesian Voivodeship, POL",
    "Mexico City, Mexico City, MEX", "Singapore", "Tokyo, Japan",
    # bare foreign cities, incl. native spellings that once slipped through
    "London", "Milano", "Munich", "München", "Torino", "Roma", "Zürich",
    "Warszawa", "Casablanca", "Rio de Janeiro", "Tel Aviv", "Sydney",
    "Vancouver, BC", "Brussels", "Oslo", "Helsinki", "Dublin", "Amsterdam",
    # bare-city batch 2 (NEXT.md item 5) — capitals/hubs with no notable US namesake
    "Tashkent", "Istanbul", "Ankara", "Cairo", "Lagos", "Accra", "Riyadh",
    "Hong Kong", "Karachi", "Dhaka", "Kyiv", "Moscow", "Minsk",
    "Riga", "Tallinn", "Belgrade", "Zagreb", "Sofia", "Bratislava", "Porto",
    "Lyon", "Marseille", "Hamburg", "Frankfurt", "Cologne", "Düsseldorf",
    "Antwerp", "The Hague", "Utrecht", "Gothenburg", "Malmö", "Reykjavik",
    "Tunis", "Addis Ababa", "Kigali", "Dakar", "Quito", "Caracas",
    "Montevideo", "La Paz", "Havana", "Edinburgh", "Glasgow", "Belfast",
    "Mississauga", "Saskatoon", "Christchurch", "Adelaide", "Canberra",
    # country-list gaps found by the item-5 probe (missing from the "full" list)
    "San Jose, Costa Rica", "Santo Domingo, Dominican Republic",
    # Canadian province / NZ codes without the country spelled out
    "Waterloo, ON", "Halifax, NS", "Victoria, BC", "Regina, SK", "Wellington, NZ",
]

# Bare names a US city OWNS — must KEEP even though a bigger foreign city shares the
# name. The residual ambiguity belongs to the eligibility joint, not this list. The
# ", on-site" case guards the comma-anchored Ontario code against matching prose.
MUST_KEEP += [
    "St. Petersburg, FL", "Victoria, TX", "Wellington, FL", "Moscow, ID",
    "Glasgow, KY", "Belfast, ME", "Frankfort, KY", "Chicago, on-site",
]

def main():
    failures = []
    for loc in MUST_KEEP:
        if not us(loc):
            failures.append(f"WRONGLY REJECTED a US role: {loc!r}")
    for loc in MUST_REJECT:
        if us(loc):
            failures.append(f"WRONGLY KEPT a foreign role: {loc!r}")

    total = len(MUST_KEEP) + len(MUST_REJECT)
    if failures:
        print(f"❌ location gate FAILED — {len(failures)}/{total} cases wrong:")
        for f in failures:
            print("   ", f)
        sys.exit(1)
    print(f"✅ location gate OK — {total}/{total} cases correct")

if __name__ == "__main__":
    main()
