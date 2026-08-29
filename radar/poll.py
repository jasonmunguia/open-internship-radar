"""Main poller: fetch -> diff -> score -> alert (GitHub issue) -> persist state."""
import hashlib, json, os, re, sys, time, urllib.request
import yaml
from radar.fetchers import fetch_all, fetch_substack, watch_page, is_posting_live
from radar.queue_state import relay as qs_relay
from radar.score import score_posting, is_us_location
from radar.settings import MENTION, RELAY_BASE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN = os.path.join(ROOT, "data", "seen.json")
QUEUE = os.path.join(ROOT, "data", "queue.jsonl")
FUNDED = os.path.join(ROOT, "data", "funded_watch.json")

def load_funded():
    """{company_substr_lower: {amount,date,industry}} within a rolling 120-day window."""
    if not os.path.exists(FUNDED):
        return {}
    import datetime as dt
    raw = json.load(open(FUNDED))
    # 14-day window: startups staff up right after a raise, so recency is the signal
    cutoff = (dt.date.today() - dt.timedelta(days=14)).isoformat()
    return {k: v for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict) and str(v.get("date", "")) >= cutoff}

def refresh_funded():
    """Run the SEC Form D radar once per day; merge $60M+ raises into the watchlist."""
    import datetime as dt
    data = json.load(open(FUNDED)) if os.path.exists(FUNDED) else {}
    today = dt.date.today().isoformat()
    if data.get("_last_run") == today:
        return data
    try:
        from radar.funding import recent_big_form_ds
        for r in recent_big_form_ds(days=2, min_amount=60_000_000):
            key = re.sub(r"[^a-z0-9 ]", "", r["company"].lower()).strip()
            key = re.sub(r"\b(inc|llc|corp|corporation|ltd|co|technologies|labs|holdings)\b", "", key).strip()
            if len(key) >= 4:
                data[key] = {"amount": r["amount"], "date": today, "industry": r.get("industry", "?"),
                             "full_name": r["company"]}
    except Exception as ex:
        print(f"[warn] funding refresh: {ex}", file=sys.stderr)
    data["_last_run"] = today
    json.dump(data, open(FUNDED, "w"))
    return data

def pid(p):
    return hashlib.sha1(f"{p['company']}|{p['title']}|{p['url']}".lower().encode()).hexdigest()[:16]

def discovered_postings(path=None):
    """Rows found by the nightly model-first discovery joint (radar/discover.py) re-enter
    the pipeline HERE — same scoring, same family+tier gates, same seen-dedupe (pid) as
    any polled board. Discovery widens the funnel; it never bypasses the filters.

    Always logs its count when the file exists, INCLUDING zero: a dead ingest must look
    different from an empty one, or discovery can die silently the way the scraped v1 did
    (it reported success while returning nothing, twice, for different reasons)."""
    path = path or os.path.join(ROOT, "data", "discovered.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if str(d.get("url", "")).startswith("http") and d.get("title"):
            out.append({"company": d.get("company", ""), "title": d.get("title", ""),
                        "location": d.get("location", ""), "url": d["url"],
                        "source": "discovery"})
    print(f"[discovery] ingested {len(out)} rows from data/discovered.jsonl")
    return out

def send_alert_email(subject, body_md):
    """Burning alert as a real email from the operator's personal Gmail — clean subject, no
    '[owner/repo]' prefix. Creds come from repo secrets. Returns True if sent."""
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    sender = os.environ.get("GMAIL_SENDER", "")
    to = os.environ.get("ALERT_TO", "")
    if not (pw and sender and to):
        return False
    import smtplib, ssl, re as _re
    from email.message import EmailMessage
    # light markdown -> html so the email reads well
    html = _re.sub(r"^## (.+)$", r"<h2>\1</h2>", body_md, flags=_re.M)
    html = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = _re.sub(r"^(https?://\S+)$", r'<a href="\1">\1</a>', html, flags=_re.M)
    html = ("<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,"
            "sans-serif;font-size:14px;color:#111;max-width:800px\">" +
            html.replace("\n", "<br>") + "</div>")
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = subject
    m.set_content("This alert is HTML. Open in an HTML-capable client.")
    m.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(sender, pw)
        s.send_message(m)
    return True

def create_issue(repo, token, title, body, labels):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body, "labels": labels}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "internship-radar"})
    urllib.request.urlopen(req, timeout=20)

def company_blurb(company, intel):
    cl = company.lower()
    for k, v in intel.items():
        if k in cl:
            return v
    return ""

def fit_brief_md(p, score, brief, intel=None):
    intel = intel or {}
    lines = [
        f"## {p['company']} — {p['title']}",
        f"**Fit score: {score}/100** | tier: {brief['tier']} | cluster: {brief['cluster']}"
        + (" | **off-cycle ✅**" if brief["offcycle"] else ""),
        f"**Location:** {p.get('location','?')}" + (f" | **Posted:** {p['posted_at']}" if p.get("posted_at") else ""),
        f"**Apply:** {p['url']}",
    ]
    # ✓/✗ verdict buttons on burning alerts too (2026-08-29 per the operator) — the digest had
    # them, the Apply-Now emails didn't, so alert rows never fed the tap training. Same
    # relay and job_id as the digest, so a tap here and a tap there collapse to one
    # verdict. Raw HTML anchors survive send_alert_email's md->html regexes untouched and
    # degrade to plain links in the GitHub-issue fallback. RELAY_BASE unset -> no
    # buttons, never dead links.
    if RELAY_BASE:
        y = qs_relay("", p, RELAY_BASE, action="yes")
        n = qs_relay("", p, RELAY_BASE, action="no")
        a = qs_relay(p.get("url", ""), p, RELAY_BASE, action="applied")
        lines.append(
            f"<a href='{y}' style='background:#059669;color:#fff;padding:2px 10px;"
            f"border-radius:4px;text-decoration:none'>✓ good fit</a>&nbsp;&nbsp;"
            f"<a href='{n}' style='background:#dc2626;color:#fff;padding:2px 10px;"
            f"border-radius:4px;text-decoration:none'>✗ not for me</a>&nbsp;&nbsp;"
            f"<a href='{a}' style='background:#1d4ed8;color:#fff;padding:2px 10px;"
            f"border-radius:4px;text-decoration:none'>I applied ✅</a>")
    blurb = company_blurb(p["company"], intel)
    if blurb:
        lines.append(f"**What they do:** {blurb}")
    if brief.get("funding"):
        lines.append(f"**💰 Just raised:** {brief['funding']} — staffing up, apply now.")
    lines += ["",
        # angle_pitch exists in the brief ONLY when `angles` is enabled in profile.yaml
        # (absent-means-off, no flag). The .get() guard is the correct consumer pattern:
        # render only if present. An unguarded brief['angle_pitch'] would (rightly) KeyError.
        (f"**Lead with your `{brief['angle']}` angle:** {brief['angle_pitch']}"
         if brief.get("angle_pitch") else "")]
    if brief["matched_keywords"]:
        lines.append(f"**Hooks to echo in app:** {', '.join(brief['matched_keywords'])}")
    lines += ["",
        "**Move fast:** rolling reviews reward first-72h applicants. Want warm-path contacts at this "
        "company (recruiters / your university alumni / chiefs of staff)? Reply to this and I'll pull them.",
        "", f"_source: {p['source']}_ {MENTION}"]
    return "\n".join(lines)

def main():
    with open(os.path.join(ROOT, "config", "profile.yaml")) as f:
        profile = yaml.safe_load(f)
    with open(os.path.join(ROOT, "config", "sources.yaml")) as f:
        sources = yaml.safe_load(f)
    intel_path = os.path.join(ROOT, "config", "company_intel.yaml")
    intel = yaml.safe_load(open(intel_path)) if os.path.exists(intel_path) else {}
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {}
    first_run = not seen

    postings, errors, counts = fetch_all(sources)
    for e in errors:
        print(f"[warn] {e}", file=sys.stderr)
    postings += discovered_postings()

    refresh_funded()          # SEC Form D $60M+ radar, once/day
    funded = load_funded()    # rolling 120-day watchlist -> scorer promotes these companies

    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    threshold = profile["scoring"]["high_fit_threshold"]
    new_count = alert_count = 0

    with open(QUEUE, "a") as q:
        for p in postings:
            k = pid(p)
            if k in seen:
                continue
            seen[k] = int(time.time())
            score, brief = score_posting(p, profile, funded)
            if score is None:
                continue
            new_count += 1
            rec = {**p, "score": score, **brief, "ts": int(time.time())}
            q.write(json.dumps(rec) + "\n")
            # burning alert on high fit. Prestige giants are dream-tier (+40), so their business/ops/
            # product roles clear the bar and burn fast, while off-fit SWE/design roles stay below it (no spam).
            # first run seeds state silently — don't flood 500 issues
            # cross-source dedup: the same role often lists on a company board AND a VC portfolio board;
            # alert on it once (by company+title), not once per board.
            akey = "alert:" + p.get("company", "").lower().strip() + "|" + p.get("title", "").lower().strip()
            if not first_run and score >= threshold and gh_token and akey not in seen:
                # Liveness gate (career-ops doctrine): only alert on a posting that's still open.
                # Cheap because it runs ONLY on the handful that clear the alert threshold.
                if not is_posting_live(p.get("url", "")):
                    print(f"[skip] dead posting: {p['company']} — {p['title']}")
                    continue
                subj = f"📜Apply Now — {p['company']}: {p['title']} [{score}]"
                body = fit_brief_md(p, score, brief, intel)
                try:
                    if not send_alert_email(subj, body):      # clean-subject email preferred
                        create_issue(gh_repo, gh_token, subj, body, ["alert", brief["tier"]])
                    seen[akey] = int(time.time())
                    alert_count += 1
                    time.sleep(1)
                except Exception as ex:
                    print(f"[warn] alert failed ({p['company']}): {ex}", file=sys.stderr)
                    try:                                       # last resort: GitHub issue
                        create_issue(gh_repo, gh_token, subj, body, ["alert", brief["tier"]])
                        seen[akey] = int(time.time())
                        alert_count += 1
                    except Exception as ex2:
                        print(f"[warn] issue fallback failed: {ex2}", file=sys.stderr)

    # Fold today's Form D filings into PERSISTENT funding history. Without this the funding
    # tier signal only ever knew the ~14-day rolling window, which is why MaintainX banded T4.
    try:
        from radar.funding import recent_big_form_ds
        from radar.funding_history import ingest as _fh_ingest
        _fh_ingest(recent_big_form_ds(days=2, min_amount=25_000_000))
    except Exception as ex:
        print(f"[warn] funding history ingest skipped: {ex}", file=sys.stderr)

    # newsletters: new issues -> digest queue (no instant alert)
    with open(QUEUE, "a") as q:
        for nl in sources.get("newsletters", []):
            try:
                for item in fetch_substack(nl["name"], nl["sub"]):
                    k = pid(item)
                    if k in seen:
                        continue
                    seen[k] = int(time.time())
                    if not first_run:
                        q.write(json.dumps({**item, "score": 0, "cluster": "newsletter",
                                            "angle": "", "ts": int(time.time())}) + "\n")
            except Exception as ex:
                print(f"[warn] newsletter {nl['name']}: {ex}", file=sys.stderr)

    # fellowship page watchers: content change -> instant issue
    for w in sources.get("watch_pages", []):
        try:
            h = watch_page(w["name"], w["url"])
            key = f"page:{w['url']}"
            old = seen.get(key)
            seen[key] = h
            if old and old != h and gh_token:
                create_issue(gh_repo, gh_token,
                             f"[watch] {w['name']} page changed — possible cohort/app opening",
                             f"{w['url']} content changed since last check. If applications opened, "
                             f"apply day-one and start referral outreach. {MENTION}", ["watch"])
        except Exception as ex:
            print(f"[warn] watch {w['name']}: {ex}", file=sys.stderr)

    # ---- health monitoring: catch sources that silently went dark (ATS migration, dead token) ----
    HEALTH = os.path.join(ROOT, "data", "health.json")
    health = json.load(open(HEALTH)) if os.path.exists(HEALTH) else {}
    for name, n in counts.items():
        h = health.get(name, {"streak": 0, "ever_good": False, "alerted": False})
        if n > 0:
            h = {"streak": 0, "ever_good": True, "alerted": False}
        elif h.get("ever_good"):   # was healthy, now 0 or errored
            h["streak"] = h.get("streak", 0) + 1
            # 3 consecutive dark runs (~6h) on a previously-good source -> alert once
            if h["streak"] >= 3 and not h.get("alerted") and gh_token:
                try:
                    create_issue(gh_repo, gh_token,
                                 f"⚠️ [health] source '{name}' went dark ({'errors' if n < 0 else '0 results'} x{h['streak']})",
                                 f"`{name}` returned {'errors' if n < 0 else 'zero postings'} for {h['streak']} "
                                 f"consecutive polls but was healthy before. Likely an ATS migration or dead token — "
                                 f"needs a token re-check in config/sources.yaml. {MENTION}", ["health"])
                    h["alerted"] = True
                except Exception as ex:
                    print(f"[warn] health issue failed: {ex}", file=sys.stderr)
        health[name] = h
    json.dump(health, open(HEALTH, "w"))

    # ---- self-heal: strip any non-US rows that predate (or slipped past) the location gate ----
    # Rows scored before a gate existed stay in the queue forever otherwise. Re-checking every
    # run means a rule change retroactively cleans history with no manual purge.
    if os.path.exists(QUEUE):
        from radar.score import _any
        _gates = profile["scoring"]["gate_patterns"]
        _excl = profile["scoring"].get("exclude_patterns", [])
        _relic_log = os.path.join(ROOT, "data", "dropped_relics.jsonl")
        kept_rows, dropped_foreign, dropped_relic = [], 0, 0
        for line in open(QUEUE):
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("cluster") != "newsletter" and not is_us_location(
                    row.get("location", ""), row.get("department", "")):
                dropped_foreign += 1
                continue
            # Gate-relic purge (2026-08-15): rows scored under OLD gate patterns stay
            # queued forever otherwise — bare 'intern' matched inside 'International'
            # until the 08-14 word-boundary fix, and a full-time "Product Manager |
            # International" topped the email a day AFTER the gate was fixed. Re-check
            # against CURRENT patterns. Caveat: scoring saw the description, the queue
            # row doesn't carry it — so a row gated in via description alone would be
            # dropped here. Every drop is therefore LOGGED to dropped_relics.jsonl
            # (never silent), same posture as dropped_unmatched.jsonl.
            if row.get("cluster") != "newsletter":
                _rowtext = " ".join(str(row.get(k, "")) for k in ("title", "department", "location"))
                if not _any(_gates, _rowtext) or _any(_excl, row.get("title", "")):
                    dropped_relic += 1
                    with open(_relic_log, "a") as rl:
                        rl.write(json.dumps(row) + "\n")
                    continue
            kept_rows.append(json.dumps(row) + "\n")
        if dropped_foreign or dropped_relic:
            with open(QUEUE, "w") as q:
                q.writelines(kept_rows)
            print(f"[self-heal] removed {dropped_foreign} non-US rows, "
                  f"{dropped_relic} gate-relic rows (logged to dropped_relics.jsonl)")

    # ---- pruning: keep seen/queue bounded to a 90-day window so the repo never bloats over years ----
    RETAIN = 90 * 86400
    cutoff = int(time.time()) - RETAIN
    before = len(seen)
    seen = {k: v for k, v in seen.items()
            if k.startswith("page:") or (isinstance(v, int) and v >= cutoff)}
    if os.path.exists(QUEUE):
        kept = []
        for line in open(QUEUE):
            try:
                if json.loads(line).get("ts", 0) >= cutoff:
                    kept.append(line if line.endswith("\n") else line + "\n")
            except Exception:
                continue
        with open(QUEUE, "w") as q:
            q.writelines(kept)
    json.dump(seen, open(SEEN, "w"))

    # ---- heartbeat: proof-of-life for the dead-man's switch (a separate watcher reads this) ----
    dark = sorted(k for k, v in health.items() if v.get("streak", 0) >= 3)
    json.dump({"last_poll": int(time.time()), "postings": len(postings),
               "new_scored": new_count, "alerts": alert_count,
               "dark_sources": dark, "seen_pruned_from": before, "seen_now": len(seen)},
              open(os.path.join(ROOT, "data", "heartbeat.json"), "w"))

    print(f"postings={len(postings)} new_scored={new_count} alerts={alert_count} "
          f"dark={len(dark)} seen={before}->{len(seen)} first_run={first_run}")

if __name__ == "__main__":
    main()
