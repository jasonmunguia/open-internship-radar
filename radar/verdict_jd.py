"""JD capture for verdict rows (2026-08-29 per the operator): every tapped row gets its
posting's job-description text fetched and stored, so the weekly feedback_patterns
joint can learn WHY from role CONTENT, not just title/tier/score. The incident that
forced this: the Palantir Neurodivergent Fellowship shipped as a dream-tier 78 and got
a 👎 — the JD is for hypertechnical engineers, which the title never said.

Deterministic, no model call. Plain GET first; Scrapling stealth render as the
fallback for bot-walled pages AND for pages whose static HTML is only site chrome
(lifeattiktok.com renders the posting client-side, so a GET returns the site menu —
that chrome was being stored as the "JD" until 2026-09-30). Runs in the nightly on the
local machine, where Scrapling exists — the cloud poller never calls this. A row that fails both
fetches is recorded with an empty jd and not retried under the same capture version
(die-once per CAPTURE_VERSION, like liveness's no-URL rule): retrying a dead posting URL
nightly buys nothing, and the verdict's title/tier facts still reach the joint without
it. Bumping CAPTURE_VERSION buys every failed or chrome-only record exactly one retry —
that is how the Scrapling bytes bug's 42 casualties get re-fetched.
"""
import json
import os
import re
from html import unescape as _unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDBACK = os.path.join(ROOT, "data", "feedback.jsonl")
QUEUE = os.path.join(ROOT, "data", "queue.jsonl")
OUT = os.path.join(ROOT, "data", "verdict_jd.jsonl")

JD_CAP = 2500          # stored chars; enough for the meat of any JD
CAPTURE_VERSION = 2    # v2 (2026-09-30): bytes-safe Scrapling, chrome detection, JD trimming
_TAG_JUNK = re.compile(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
# Phrases a real job description uses and a careers site's menu does not. Two distinct
# hits = a JD; fewer = chrome, a pulled-req notice, or a login wall.
_JD_SIGNAL = re.compile(r"responsib|qualification|requirement|you will|you'll|what you|"
                        r"experience (with|in)|about the (role|team|job|position)|"
                        r"job description|preferred|minimum|skills", re.I)
# Where a JD starts when the posting title cannot be found on the page.
_JD_START = re.compile(r"job description|about the (role|job|position|team|opportunity)|"
                       r"responsibilities|what you('| wi)ll do", re.I)


def visible_text(html, cap=JD_CAP):
    """Visible page text: drop script/style blocks, strip tags, collapse whitespace.
    Good enough for pattern evidence — this feeds a model, not a renderer.
    Accepts bytes: Scrapling >=0.4 returns page.body as BYTES, and a str regex over
    bytes raises TypeError — every Scrapling fallback died on exactly that from the
    day this module shipped until 2026-09-30 (42 of 143 captures, recorded as
    "error:TypeError" and never retried)."""
    if not html:
        return ""
    if isinstance(html, (bytes, bytearray)):
        html = html.decode("utf-8", "replace")
    text = _TAG_JUNK.sub(" ", html)
    text = _unescape(_TAGS.sub(" ", text))       # &#x27; -> ' ; the joint reads words
    text = _WS.sub(" ", text)
    text = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
    return text[:cap] if cap else text


def jd_text(text, title=""):
    """The page text from where the posting starts: at the posting's title when it
    appears on the page, else at the first JD section heading, else unchanged. Drops
    the careers-site menu that precedes the JD (it ate the whole 600-char excerpt the
    pattern joint sees on every TikTok row)."""
    if not text:
        return ""
    t = (title or "").strip().rstrip(".… ")      # boards truncate titles with "..."
    if len(t) >= 8:
        i = text.lower().find(t[:40].lower())
        if i >= 0:
            return text[i:]
    m = _JD_START.search(text)
    return text[m.start():] if m else text


def looks_like_jd(text):
    """True when the text carries at least two distinct JD phrases."""
    hits = {m.group(0).lower() for m in _JD_SIGNAL.finditer(text or "")}
    return len(text or "") >= 300 and len(hits) >= 2


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


def _fetch_jd(url, title=""):
    """(text, how). Plain GET -> Scrapling stealth render -> give up. Mirrors liveness's
    cheap-first layering; import inside so the cloud poller can import this module
    without Scrapling installed. A GET only counts when its text reads as a JD — a
    JS-rendered careers site returns its menu to a GET, which is long enough to pass
    any length test and carries no role content."""
    from radar.fetchers import _get
    try:
        text = jd_text(visible_text(_get(url, timeout=20, retries=1), cap=None), title)
        if looks_like_jd(text):
            return text[:JD_CAP], "get"
    except Exception:
        pass
    try:
        from radar.scrapling_fetch import _stealth
        page = _stealth(url)
        text = jd_text(visible_text(page.body if hasattr(page, "body") else str(page),
                                    cap=None), title)
    except Exception as ex:
        return "", f"error:{type(ex).__name__}"
    if looks_like_jd(text):
        return text[:JD_CAP], "scrapling"
    # Rendered, still no JD: a pulled req, a login wall, or chrome only. Recorded
    # empty (die-once) — storing chrome as a JD is what poisoned the evidence.
    return "", "error:NoJDText"


def _settled(rec):
    """A capture record that needs no retry: it holds a real JD, it was made by the
    current capture version, or it has no URL to fetch."""
    if rec.get("v", 1) >= CAPTURE_VERSION:
        return True
    if rec.get("jd") and looks_like_jd(jd_text(rec["jd"], rec.get("title", ""))):
        return True
    return rec.get("how") == "error:NoURL"


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
    latest = {}
    for r in _read_jsonl(OUT):
        latest[r.get("job_id")] = r              # file order: the last record wins
    # Never-captured verdicts first, then one-time retries of pre-v2 failures.
    new = [(jid, v) for jid, v in verdicts.items() if jid not in latest]
    retry = [(jid, v) for jid, v in verdicts.items()
             if jid in latest and not _settled(latest[jid])]
    todo = (new + retry)[:limit]

    fetched = failed = 0
    with open(OUT, "a") as fh:
        for jid, v in todo:
            q = rows_by_id.get(jid, {})
            prev = latest.get(jid, {})           # a retried row may have left the queue
            company = q.get("company") or prev.get("company", "")
            title = q.get("title") or prev.get("title", "")
            url = q.get("url") or v.get("url") or prev.get("url") or ""
            if url:
                jd, how = _fetch_jd(url, title)
            else:
                jd, how = "", "error:NoURL"
            fetched += 1 if jd else 0
            failed += 0 if jd else 1
            fh.write(json.dumps({
                "job_id": jid, "verdict": v.get("action"),
                "company": company, "title": title,
                "url": url, "ts": v.get("ts", 0), "how": how, "jd": jd,
                "v": CAPTURE_VERSION,
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
    n_new = min(len(new), limit)
    return {"new": n_new, "retried": len(todo) - n_new, "fetched": fetched,
            "failed": failed, "retry_backlog": len(retry) - (len(todo) - n_new),
            "total_captured": len(set(latest) | {jid for jid, _ in todo})}


def excerpts(cap=600):
    """{job_id: jd_excerpt} for feedback_analysis to join into its evidence rows.
    Trimmed to where the posting starts, and chrome-only text is dropped — a menu
    excerpt is worse than none, because the joint reads it as role content."""
    out = {}
    for r in _read_jsonl(OUT):                   # file order: a v2 retry overrides v1
        text = jd_text(r.get("jd", ""), r.get("title", ""))
        if looks_like_jd(text):
            out[r["job_id"]] = text[:cap]
    return out


def records():
    """{job_id: {company, title, url}} — the row's identity as captured at tap time.
    feedback_analysis falls back to this when a row has since left the queue (a rule
    added later removed it), which is what blanked 16 verdicts' facts."""
    out = {}
    for r in _read_jsonl(OUT):
        cur = out.setdefault(r.get("job_id"), {"company": "", "title": "", "url": ""})
        for k in cur:
            if r.get(k):
                cur[k] = r[k]
    return out
