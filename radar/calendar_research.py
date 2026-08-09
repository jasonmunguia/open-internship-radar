"""Daily calendar research — keeps the pre-network email from decaying into fiction.

THE PROBLEM THIS SOLVES
config/release_calendar.yaml was hand-researched once (2026-07-26) and never refreshed.
Every `expected_open` is a decaying estimate, and a wrong date fails in the worst direction:
the pre-network email says "opens in 9 days" for a req that opened last week, so the operator
networks toward a window that already closed and never sees the posting until the digest
catches it — losing the entire pre-network advantage, which is the whole point of email #1.

WHY THIS IS A CLAUDE JOINT AND NOT A SCRAPER
"When does this program open?" has no API and no consistent markup. The answer lives in
prose across career pages, university writeups, and last cycle's postings, and it requires
judgment: distinguishing a stated window from a guess, noticing a program was renamed,
recognising that an entry became a full-time role. Regex cannot do it; a coding-agent CLI
with Scrapling and web search can.

CONTRACT
Claude is handed the current calendar and asked to return a STRICT YAML list. It may:
  - revise expected_open when it finds better evidence (must cite it)
  - add programs it discovers
  - flag entries that look dead
It may NOT invent programs, and every changed entry must carry an `evidence:` URL.
Output is validated and diffed before anything is written; a malformed response is a no-op,
never a partial overwrite.
"""
import json, os, subprocess, tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(ROOT, "config", "release_calendar.yaml")
REPORT = os.path.join(ROOT, "data", "calendar_research.json")

PROMPT = """You are refreshing an internship release-date calendar. Today is {today}.

You have Scrapling installed (`from scrapling.fetchers import StealthyFetcher`) for pages that
block plain fetches, and web search. Use both. Work from primary sources: official career
pages, official university-recruiting pages, and live job postings. Secondary writeups are
acceptable only when they quote a date.

For EACH program in the calendar below, determine whether `expected_open` is still the best
estimate for the stated term. Also check https://apmlist.com and official APM/PM program pages
for programs the calendar is missing entirely.

Rules, in order of importance:
1. NEVER invent a program. If you cannot find evidence, leave the entry unchanged.
2. Any entry you change or add MUST have an `evidence:` field containing a real URL you read.
3. If a posting is ALREADY LIVE, set expected_open to today and say so in deadline_behavior.
4. If a program appears discontinued or converted to full-time only, set confidence: dead.
5. Prefer a stated window ("posts August through September") over an inferred one, and say
   which you used in deadline_behavior.

Return ONLY a YAML list, no prose, no code fences. Each item:
  program, company, expected_open (YYYY-MM-DD), confidence (high|medium|low|dead),
  cadence, terms, deadline_behavior, requirements, evidence

CURRENT CALENDAR:
{calendar}
"""


def run(timeout=1800, model=None):
    """Invoke the local Claude CLI to refresh the calendar. Returns a change report.

    Never partially writes: the response is parsed and validated in full, and only a
    structurally valid list replaces the file. A bad run leaves yesterday's calendar intact,
    which is strictly better than a half-updated one."""
    import yaml
    current = open(CAL).read()
    prompt = PROMPT.format(today=date.today().isoformat(), calendar=current)

    cmd = ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]
    if model:
        cmd += ["--model", model]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception as ex:
        return {"ok": False, "error": f"claude invocation failed: {ex}"}

    body = out.strip()
    if "```" in body:                       # tolerate fences even though we asked for none
        body = body.split("```")[1].lstrip("yaml").strip()
    try:
        new = yaml.safe_load(body)
    except Exception as ex:
        return {"ok": False, "error": f"unparseable YAML: {ex}"}
    if not isinstance(new, list) or len(new) < 5:
        return {"ok": False, "error": f"refusing to write: got {type(new).__name__} len "
                                      f"{len(new) if hasattr(new,'__len__') else '?'}"}

    old = {e.get("program"): e for e in (yaml.safe_load(current) or [])}
    changed, added, dead = [], [], []
    for e in new:
        if not isinstance(e, dict) or not e.get("program"):
            return {"ok": False, "error": "entry missing `program` — refusing to write"}
        p, o = e["program"], old.get(e.get("program"))
        if o is None:
            added.append(p)
        elif str(o.get("expected_open")) != str(e.get("expected_open")):
            changed.append({"program": p, "was": str(o.get("expected_open")),
                            "now": str(e.get("expected_open")), "evidence": e.get("evidence", "")})
        if str(e.get("confidence")) == "dead":
            dead.append(p)

    with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(CAL)) as fh:
        yaml.safe_dump(new, fh, sort_keys=False, allow_unicode=True, width=100)
        tmp = fh.name
    os.replace(tmp, CAL)                    # atomic: never a truncated calendar on disk

    report = {"ok": True, "ts": date.today().isoformat(), "total": len(new),
              "changed": changed, "added": added, "dead": dead}
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    json.dump(report, open(REPORT, "w"), indent=1)
    return report


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=1)[:2000])
