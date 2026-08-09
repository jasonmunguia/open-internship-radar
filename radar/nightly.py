"""Nightly deep pass — the work that needs a laptop, a model, and no hurry.

the operator keeps his machine open, so the expensive judgment-heavy jobs run at 2am rather than
competing with the 7:20am digest. Each stage is independently wrapped: a stage that fails
must not prevent the ones after it, because a partial refresh beats no refresh.

Order is deliberate. Funding first (cheap, feeds tier bands), then tier backfill (long
Scrapling run), then Claude slug resolution on whatever the deterministic path could not
resolve, then discovery, then calendar research last because it is the slowest.
"""
import json, os, sys, time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "data", "nightly.json")


def _companies_from_queue():
    """Every company the radar has actually seen — the real backfill target list. Sourced from
    the live queue rather than sources.yaml, because a board we poll is not the same thing as
    a company that has ever posted a role we care about."""
    names = []
    try:
        with open(os.path.join(ROOT, "data", "queue.jsonl")) as fh:
            for line in fh:
                try:
                    c = json.loads(line).get("company")
                    if c:
                        names.append(c)
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return list(dict.fromkeys(names))


def _stage(name, fn, report):
    t0 = time.time()
    try:
        report[name] = {"ok": True, "result": fn(), "secs": round(time.time() - t0, 1)}
    except Exception as ex:
        report[name] = {"ok": False, "error": str(ex)[:200], "secs": round(time.time() - t0, 1)}
    print(f"[nightly] {name}: {json.dumps(report[name])[:220]}", flush=True)


def main():
    report = {"ts": date.today().isoformat()}

    def funding():
        from radar.funding import recent_big_form_ds
        from radar.funding_history import ingest
        # Windowed, not one wide query: EDGAR full-text search returns FEWER hits for wider
        # ranges (days=7 gave 0 while days=1 gave 1), so sweep day-by-day and union.
        total = 0
        for back in range(1, 8):
            total += ingest(recent_big_form_ds(days=back, min_amount=25_000_000))
        return {"ingested": total}

    def backfill():
        from radar.tiers import backfill as bf
        return bf(_companies_from_queue(), limit=int(os.environ.get("IR_BACKFILL_LIMIT", "150")))

    def slugs():
        from radar.tiers import resolve_unresolved_with_claude
        return resolve_unresolved_with_claude()

    def discovery():
        from radar.discover import discover
        found = discover()
        with open(os.path.join(ROOT, "data", "discovered.jsonl"), "a") as fh:
            for r in found:
                fh.write(json.dumps(r) + "\n")
        return {"found": len(found)}

    def calendar():
        from radar.calendar_research import run
        return run()

    # NOTE: no bookface stage. See radar/bookface.py — disabled on operating-security
    # grounds, not technical ones. Do not re-add it.
    for name, fn in [("funding", funding), ("tier_backfill", backfill),
                     ("slug_resolution", slugs), ("discovery", discovery),
                     ("calendar_research", calendar)]:
        _stage(name, fn, report)

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    json.dump(report, open(REPORT, "w"), indent=1)
    failed = [k for k, v in report.items() if isinstance(v, dict) and not v.get("ok", True)]
    print(f"[nightly] done. failed stages: {failed or 'none'}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    sys.exit(main())
