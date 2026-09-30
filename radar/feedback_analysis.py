"""Weekly pattern analysis over the operator's 👍/👎 digest taps (2026-08-15).

The taps land in data/feedback.jsonl (via the click relay -> Actions, same rail as
applied.jsonl). This module joins each verdict to its queue row's facts and, once a
week's worth has accumulated, asks the feedback_patterns joint what the taps imply —
"they reject every defense row below T2", "yes-rate on hourly-paid rows is 3x".

PROPOSALS ONLY. The output file is rendered in the digest for the operator to read;
nothing here touches profile.yaml. The digest stays deterministic about what ships —
this loop only proposes how the config might change, and the operator applies changes
in conversation. (Same posture as dropped_unmatched.jsonl: patterns propose, never
auto-add.)

Gates, all three required before a model call is spent:
  - >= MIN_VERDICTS total verdicts (patterns from 3 taps are astrology)
  - >= MIN_SPAN_DAYS between first and last verdict (a week of taste, not one mood)
  - new verdicts since the last analysis (else the same answer re-bought weekly)
"""
import json, os, re, time

from radar.joints import run_joint

ROOT = os.path.join(os.path.dirname(__file__), "..")
FEEDBACK = os.path.join(ROOT, "data", "feedback.jsonl")
QUEUE = os.path.join(ROOT, "data", "queue.jsonl")
OUT = os.path.join(ROOT, "data", "feedback_patterns.json")
REPLIES = os.path.join(ROOT, "data", "feedback_replies.jsonl")   # learning_loop check-in replies

MIN_VERDICTS = 10
MIN_SPAN_DAYS = 7

# Row facts worth reasoning over. score/tier/cluster are the system's own judgment —
# the point is to find where the operator's taps DISAGREE with it.
_FACTS = ("company", "title", "cluster", "tier", "industry", "location", "score", "pay", "source")


def _read_jsonl(path):
    try:
        with open(path) as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except Exception:
        return []


def _rules_now():
    """row -> what the CURRENT rules do with it: "excluded" or "cluster / tier / score".
    Lets the joint see which rejections today's config already handles, so it stops
    re-proposing them (the sales exclusion shipped 2026-09-04, and the 2026-09-29 run
    still proposed it off pre-exclusion taps). Cache-only, no network, no model.
    None when the radar is not configured (no profile.yaml) — the field is then omitted."""
    try:
        import yaml
        from radar.score import score_posting
        from radar.tiers import load_cache
        profile = yaml.safe_load(open(os.path.join(ROOT, "config", "profile.yaml")))
        cache = load_cache()
    except Exception as ex:
        # Visible, not silent: the field vanishing from every row would look like success.
        print(f"[feedback] rules_now unavailable, field omitted: {type(ex).__name__}: {ex}")
        return None

    def now(row):
        s, brief = score_posting(dict(row), profile, tier_cache=cache)
        return "excluded" if s is None else f"{brief['cluster']} / {brief['tier']} / {s}"
    return now


def _evidence():
    """Last-wins verdicts joined to row facts, ready to show the model.
    Returns (joined, first_ts, last_ts, unresolved): `unresolved` counts taps that no
    record can name (test taps like "test-verify") — they are not evidence and are left
    out, but counted, because a silent drop is indistinguishable from a lost verdict."""
    from radar.queue_state import job_id
    verdicts = {}
    for r in _read_jsonl(FEEDBACK):
        if r.get("action") not in ("yes", "no") or not r.get("job_id"):
            continue
        verdicts[r["job_id"]] = r
    rows_by_id = {}
    for row in _read_jsonl(QUEUE):
        rows_by_id.setdefault(job_id(row), row)
    # JD text captured nightly by verdict_jd — role CONTENT the title hides. Absent
    # for rows whose fetch failed (die-once); the join degrades to facts-only. The same
    # capture recorded each row's identity at tap time, which is the fallback when the
    # row has since LEFT the queue (a rule added later removed it) — without it those
    # verdicts reached the joint with blank company/title/tier/score.
    try:
        from radar.verdict_jd import excerpts, records
        jds, captured = excerpts(), records()
    except (ImportError, OSError, ValueError):
        jds, captured = {}, {}
    now = _rules_now()
    joined, first_ts, last_ts, unresolved = [], None, None, 0
    for jid, v in verdicts.items():
        row = rows_by_id.get(jid) or {}
        if not (row.get("company") or row.get("title")):
            row = captured.get(jid) or {}
        if not (row.get("company") or row.get("title")):
            unresolved += 1
            continue
        rec = {"verdict": v["action"], **{k: row.get(k, "") for k in _FACTS}}
        if now:
            rec["rules_now"] = now(row)
        if jds.get(jid):
            rec["jd_excerpt"] = jds[jid]
        joined.append(rec)
        ts = v.get("ts", 0)
        first_ts = ts if first_ts is None else min(first_ts, ts)
        last_ts = ts if last_ts is None else max(last_ts, ts)
    return joined, first_ts, last_ts, unresolved


def run():
    """Called by the nightly; internally gated so it spends a model call at most weekly.
    Returns a status string for the nightly report — every skip says WHY, because a
    silent no-op is indistinguishable from a dead feature."""
    joined, first_ts, last_ts, unresolved = _evidence()
    if len(joined) < MIN_VERDICTS:
        return f"skip: {len(joined)} verdicts < {MIN_VERDICTS}" + \
            (f" ({unresolved} unresolvable taps left out)" if unresolved else "")
    if (last_ts - first_ts) < MIN_SPAN_DAYS * 86400:
        return f"skip: span {(last_ts - first_ts) // 86400}d < {MIN_SPAN_DAYS}d"
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT))
        except Exception:
            prev = {}
    replies = _read_jsonl(REPLIES)
    if (prev.get("verdict_count") == len(joined)
            and prev.get("reply_count", 0) == len(replies)):
        return "skip: no new verdicts or check-in replies since last analysis"

    prompt = (
        "You are analyzing a week+ of thumbs-up/thumbs-down verdicts a candidate gave on "
        "internship postings their radar emailed them. Each row: their verdict plus the row's "
        "facts (tier T1 best..T4, score 0-100 is the system's own fit guess).\n\n"
        f"{json.dumps(joined, indent=1)}\n\n"
        "Find the patterns their verdicts reveal, especially where they DISAGREE with the "
        "system's score/tier. Focus PRIMARILY on the rejections — the 'no' verdicts are "
        "the correction signal; a 'yes' only confirms what already ships. Rows may carry "
        "jd_excerpt, the posting's own description text: use it to catch role-content "
        "patterns the title hides (e.g. a neutral title over a hypertechnical "
        "engineering JD). Rows may carry rules_now, what TODAY's rules do with the "
        "row: \"excluded\" means the system already filters it out — do not propose a "
        "change for a pattern made only of excluded rows. Web-search a "
        "company only when its name alone is ambiguous. "
        "Reply with ONLY a JSON array (no prose, no fences), each element:\n"
        '{"pattern": "<one sentence>", "polarity": "no"|"yes"|"mixed", '
        '"evidence": "<counts, e.g. 0/6 yes on defense T3+>", '
        '"proposal": "<the single config/scoring change this suggests>"}\n'
        "3-7 elements, most of them polarity \"no\". Omit anything with fewer than 3 "
        "supporting verdicts. An empty array is a valid answer."
    )
    if replies:
        guidance = [{"date": time.strftime("%Y-%m-%d", time.localtime(g.get("ts", 0))),
                     "their_words": g.get("text", "")} for g in replies[-3:]]
        prompt += (
            "\n\nThe candidate has ALSO replied to earlier learning check-ins in their own "
            "words. Weight this explicit guidance ABOVE anything inferred from taps — "
            "an inferred pattern that contradicts it is wrong:\n"
            + json.dumps(guidance, indent=1))
    try:
        r = run_joint("feedback_patterns", prompt)
    except Exception as ex:
        return f"joint failed: {ex}"
    m = re.search(r"\[.*\]", r.stdout or "", re.S)
    if not m:
        return f"malformed output (no JSON array in {len(r.stdout or '')} bytes) — no-op"
    try:
        proposals = json.loads(m.group(0))
        assert isinstance(proposals, list)
    except Exception:
        return "malformed output (unparseable JSON) — no-op"
    with open(OUT, "w") as fh:
        json.dump({"ts": int(time.time()), "verdict_count": len(joined),
                   "reply_count": len(replies), "proposals": proposals}, fh, indent=1)
    return f"ok: {len(proposals)} proposals from {len(joined)} verdicts" + \
        (f" ({unresolved} unresolvable taps left out)" if unresolved else "")


if __name__ == "__main__":
    print(run())
