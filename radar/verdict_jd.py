"""JD capture for verdict rows (2026-08-29 per the operator): every tapped row gets its
posting's job-description text fetched and stored, so the weekly feedback_patterns
joint can learn WHY from role CONTENT, not just title/tier/score. The incident that
forced this: the Palantir Neurodivergent Fellowship shipped as a dream-tier 78 and got
a 👎 — the JD is for hypertechnical engineers, which the title never said.

Deterministic, no model call. Plain GET first; Scrapling stealth render as the
fallback for bot-walled pages (same layering as liveness). Runs in the nightly on the
local machine, where Scrapling exists — the cloud poller never calls this. A row that fails both
fetches is recorded with an empty jd and not retried (die-once, like liveness's
no-URL rule): retrying a dead posting URL nightly buys nothing, and the verdict's
title/tier facts still reach the joint without it.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDBACK = os.path.join(ROOT, "data", "feedback.jsonl")
QUEUE = os.path.join(ROOT, "data", "queue.jsonl")
OUT = os.path.join(ROOT, "data", "verdict_jd.jsonl")

JD_CAP = 2500          # stored chars; enough for the meat of any JD
_TAG_JUNK = re.compile(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def visible_text(html):
    """Visible page text: drop script/style blocks, strip tags, collapse whitespace.
    Good enough for pattern evidence — this feeds a model, not a renderer."""
    if not html:
        return ""
    text = _TAG_JUNK.sub(" ", html)
    text = _TAGS.sub(" ", text)
    text = _WS.sub(" ", text)
    return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())[:JD_CAP]


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _fetch_jd(url):
    """(text, how). Plain GET -> Scrapling stealth -> give up. Mirrors liveness's
    cheap-first layering; import inside so the cloud poller can import this module
    without Scrapling installed."""
    from radar.fetchers import _get
    try:
        text = visible_text(_get(url, timeout=20, retries=1))
        if len(text) > 200:                     # a JS shell strips to almost nothing
            return text, "get"
    except Exception:
        pass
    try:
        from radar.scrapling_fetch import _stealth
        page = _stealth(url)
        return visible_text(page.body if hasattr(page, "body") else str(page)), "scrapling"
    except Exception as ex:
        return "", f"error:{type(ex).__name__}"


def capture(limit=20):
    """Fetch JDs for verdict rows not yet captured. Returns counts for the nightly
    report — including zero, because a dead capture must look different from an empty
    one (the discovery lesson)."""
    from radar.queue_state import job_id
    verdicts = {}
    for r in _read_jsonl(FEEDBACK):
        if r.get("action") in ("yes", "no") and r.get("job_id"):
            verdicts[r["job_id"]] = r
    rows_by_id = {}
    for row in _read_jsonl(QUEUE):
        rows_by_id.setdefault(job_id(row), row)
    done = {r.get("job_id") for r in _read_jsonl(OUT)}
    todo = [(jid, v) for jid, v in verdicts.items() if jid not in done][:limit]

    fetched = failed = 0
    with open(OUT, "a") as fh:
        for jid, v in todo:
            q = rows_by_id.get(jid, {})
            url = q.get("url") or v.get("url") or ""
            if url:
                jd, how = _fetch_jd(url)
            else:
                jd, how = "", "error:NoURL"
            fetched += 1 if jd else 0
            failed += 0 if jd else 1
            fh.write(json.dumps({
                "job_id": jid, "verdict": v.get("action"),
                "company": q.get("company", ""), "title": q.get("title", ""),
                "url": url, "ts": v.get("ts", 0), "how": how, "jd": jd,
            }) + "\n")
    # The writer protects its own output (the 2026-08-10 doctrine): this stage runs
    # HOURS before the nightly's end-of-run commit, and selfheal resets the clone every
    # 30 minutes — an uncommitted verdict_jd.jsonl was stash-wiped the very first night
    # it shipped (2026-08-30: captured 20, gone by morning). Commit immediately; push
    # failure is tolerated (the nightly's end push retries the same commit).
    if todo:
        import subprocess
        def _git(cmd):
            return subprocess.run(f"git -C {ROOT} {cmd}", shell=True,
                                  capture_output=True, text=True, check=False)
        _git(f"add {OUT}")
        _git('-c user.name=radar-nightly -c user.email=nightly@local '
             'commit -q -m "verdict JDs [skip ci]"')
        p = _git("push -q")
        if p.returncode != 0:
            print(f"[verdict_jd] push failed (nightly end-push will retry): {p.stderr[:120]}")
    return {"new": len(todo), "fetched": fetched, "failed": failed,
            "total_captured": len(done) + len(todo)}


def excerpts(cap=600):
    """{job_id: jd_excerpt} for feedback_analysis to join into its evidence rows."""
    return {r["job_id"]: r["jd"][:cap] for r in _read_jsonl(OUT) if r.get("jd")}
