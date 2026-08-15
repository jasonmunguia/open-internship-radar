"""Morning digest — runs LOCALLY on the operator's Mac at 7:20am via launchd.
Sends up to THREE emails — SMTP (tools/mailer.py) primary, Composio fallback:
  #1 NETWORKING HEADS-UP: programs opening within 14 days (nags daily until tapped done) -> pre-warm referrals.
  #2 DAILY APPLY LIST: roles open <=14 days, color-coded by industry, AI eligibility-filtered.
  #3 BURNING/just-dropped: handled in real time by the cloud poller as GitHub-issue emails (0-token) — not here.
"""
import json, os, subprocess, sys, time
from datetime import date, datetime, timedelta
import yaml

REPO_DIR = os.path.expanduser("~/.internship-radar")
STATE = os.path.expanduser("~/.internship-radar-digest-state.json")

INDUSTRY_COLOR = {
    "defense": "#7f1d1d", "space": "#3730a3", "robotics": "#1d4ed8", "ai_lab": "#6b21a8",
    "corporate": "#374151", "consulting": "#c2410c", "vc_portfolio": "#166534",
    "gov": "#111827", "aggregator": "#0f766e", "startup_other": "#0e7490",
}
INDUSTRY_LABEL = {
    "defense": "Defense", "space": "Space", "robotics": "Robotics/Physical-AI", "ai_lab": "AI Lab",
    "corporate": "Corporate", "consulting": "Consulting", "vc_portfolio": "VC-backed startup",
    "gov": "Gov/Intel", "aggregator": "Startup (board)", "startup_other": "Startup",
}

def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)

DRY = bool(os.environ.get("IR_DRY"))

from radar.settings import REPO, TO_ADDR, SEND_AS, WORK_DOMAINS, MENTION, RELAY_BASE

import base64
import re as _re
from radar.score import is_us_location
from email.message import EmailMessage

# Named channel in ~/.claude/tools/mailer.py (app password in macOS Keychain).
# Personal account on purpose: never originate a job search from an employer mailbox,
# and a different sender means it lands in the school INBOX instead of burying itself in Sent.

# Employer mailboxes — never originate a job-search digest from these (their admins can read Sent).

WRAP_OPEN = ("<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,"
             "sans-serif;font-size:14px;color:#111;max-width:900px\">")

def _cx(slug, payload):
    """Run a Composio tool with a JSON payload file; return (ok, parsed_data)."""
    pf = f"/tmp/ir-cx-{slug.lower()}-{abs(hash(json.dumps(payload, sort_keys=True))) % 99999}.json"
    with open(pf, "w") as fh:
        json.dump(payload, fh)
    r = sh(f"composio execute {slug} -d @{pf}")
    try:
        d = json.loads(r.stdout)
    except Exception:
        return False, {}
    data = d.get("data") or {}
    return bool(d.get("successful")), (data.get("response_data") or data)

def _raw_message(subject, body_html, frm, to):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = to
    m["Subject"] = subject                     # handles UTF-8/emoji header encoding
    m.set_content("This digest is HTML. Open in an HTML-capable client.")
    m.add_alternative(body_html, subtype="html")
    return base64.urlsafe_b64encode(m.as_bytes()).decode()

def send_email(subject, body_html):
    """Clean-subject HTML email into the operator's inbox — no '[owner/repo]' prefix, full color.

    Composio's active Gmail connection drifts across his accounts, so branch on it:
      * active IS the school mailbox -> INSERT the message straight into it, then label INBOX+UNREAD.
        (Plain SEND would self-bury in Sent, since example.edu and g.example.edu are one mailbox.)
      * active is any other account -> SEND from there to school (different sender = normal inbox arrival).
    Either branch yields a clean subject + full HTML. Falls back to the GitHub-issue relay only if
    Composio fails outright, so a delivery outage still reaches him (just with the botty prefix)."""
    if DRY:
        p = f"/tmp/ir-dry-{abs(hash(subject)) % 9999}.html"
        open(p, "w").write(f"<!--{subject}-->\n{body_html}")
        print(f"[dry] would email: {subject} -> {p}")
        return True

    # PRIMARY: named-account SMTP (deterministic sender, clean subject, full HTML).
    try:
        sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
        import mailer
        if mailer.has_password(SEND_AS):
            mailer.send(SEND_AS, TO_ADDR, subject, body_html)
            return True
    except Exception as ex:
        print(f"[warn] mailer send failed ({subject}): {ex} — falling back to Composio")

    ok, prof = _cx("GMAIL_GET_PROFILE", {"user_id": "me"})
    active = (prof.get("emailAddress") or "").lower() if ok else ""

    # NEVER send a job-search digest from an employer mailbox — it would sit in that company's
    # Sent folder, visible to its Workspace admins. Fall back to the GitHub relay instead.
    if any(active.endswith(d) for d in WORK_DOMAINS):
        print(f"[guard] active Composio account is a work mailbox ({active}) — using GitHub relay instead")
        return _queue_github(subject, body_html)

    # Same-mailbox guard, config-driven (was a hardcoded "example.edu" — a cold audit found
    # the open twin shipped it scrubbed to a dead "example.edu" branch): if the ACTIVE
    # account's domain is the destination's domain (or a subdomain alias of it, e.g.
    # g.example.edu -> example.edu), a plain SEND self-buries in Sent; INSERT+label instead.
    _to_dom = TO_ADDR.split("@")[-1].lower()
    _act_dom = active.split("@")[-1] if "@" in active else ""
    if _act_dom and (_act_dom == _to_dom or _act_dom.endswith("." + _to_dom)
                     or _to_dom.endswith("." + _act_dom)):
        ok, res = _cx("GMAIL_INSERT_MESSAGE", {
            "raw": _raw_message(subject, body_html, f"Internship Radar <{TO_ADDR}>", TO_ADDR),
            "user_id": "me"})
        mid = res.get("id") if ok else None
        if mid:
            lok, _ = _cx("GMAIL_ADD_LABEL_TO_EMAIL",
                         {"message_id": mid, "add_label_ids": ["INBOX", "UNREAD"]})
            if lok:
                return True
            print(f"[warn] inserted but labeling failed ({subject}) — message is in All Mail")
    elif active:
        ok, _ = _cx("GMAIL_SEND_EMAIL", {"recipient_email": TO_ADDR, "subject": subject,
                                         "body": body_html, "is_html": True})
        if ok:
            return True

    print(f"[warn] composio delivery failed for [{subject}] (active={active or 'unknown'}) "
          f"-> falling back to GitHub relay")
    return _queue_github(subject, body_html)

def _queue_github(subject, body_html):
    """Fallback channel: notify.yml turns this into a bot-authored issue -> GitHub emails him."""
    pend = os.path.join(REPO_DIR, "data", "pending")
    os.makedirs(pend, exist_ok=True)
    slug = _re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:40] or "digest"
    open(os.path.join(pend, f"{slug}.md"), "w").write(
        f"TITLE:{subject}\n{body_html}\n\n_{MENTION} — daily digest (fallback channel)_")
    return "github"

def badge(industry):
    c = INDUSTRY_COLOR.get(industry, "#0e7490")
    return (f"<span style='background:{c};color:#fff;padding:2px 7px;border-radius:4px;"
            f"font-size:11px;white-space:nowrap'>{INDUSTRY_LABEL.get(industry, industry)}</span>")

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")).strip()

md = esc  # body builders call md(); keep the name, now HTML-escaping

def within_days(r, days):
    pa = str(r.get("posted_at") or "")
    if len(pa) >= 10:
        try:
            return (date.today() - date.fromisoformat(pa[:10])).days <= days
        except Exception:
            pass
    # no reliable posted date -> use first-seen
    return (time.time() - r.get("ts", 0)) <= days * 86400

def sync_repo():
    """Self-healing sync. This clone is a pure MIRROR of origin/main — the only thing written here
    is data/pending (fallback digests, committed+pushed immediately). So snap to origin
    unconditionally: that covers BEHIND (normal), AHEAD (stray local commit), DIVERGED, and DIRTY
    (hand edits). `pull --ff-only` silently no-ops when AHEAD, which is how stale code once survived
    here and required a manual fix."""
    if not os.path.isdir(REPO_DIR):
        sh(f"git clone https://github.com/{REPO}.git {REPO_DIR}")
        return "cloned"
    sh(f"git -C {REPO_DIR} fetch -q origin")
    before = sh(f"git -C {REPO_DIR} rev-parse HEAD").stdout.strip()
    target = sh(f"git -C {REPO_DIR} rev-parse origin/main").stdout.strip()
    dirty = bool(sh(f"git -C {REPO_DIR} status --porcelain").stdout.strip())
    if before == target and not dirty:
        return "ok"
    # Preserve anything uncommitted before snapping to origin. The mirror reset is correct for
    # operation but silently destroyed in-progress edits three times during development.
    if sh(f"git -C {REPO_DIR} status --porcelain").stdout.strip():
        sh(f'git -C {REPO_DIR} stash push -u -m "auto-stash before mirror reset"')
    sh(f"git -C {REPO_DIR} reset --hard origin/main -q")
    sh(f"git -C {REPO_DIR} clean -fdq -e data/pending")
    status = "self-healed" if dirty or not target else "updated"
    print(f"[sync] {status}: {before[:7]} -> {target[:7]}")
    return status

def report_local_health(status, sent):
    """Publish local proof-of-life to the repo so the CLOUD watchdog can see this Mac.
    Without it, a dead 7:20am digest is invisible — the cloud can't inspect the laptop."""
    try:
        json.dump({"last_digest": int(time.time()), "sent": sent, "sync": status,
                   "host_date": datetime.now().isoformat(timespec="seconds")},
                  open(os.path.join(REPO_DIR, "data", "digest_heartbeat.json"), "w"))
        sh(f"git -C {REPO_DIR} add data/digest_heartbeat.json")
        sh(f'git -C {REPO_DIR} -c user.name=radar-local -c user.email=radar@local '
           f'commit -q -m "digest heartbeat [skip ci]"')
        sh(f"git -C {REPO_DIR} pull --rebase -X ours -q")
        sh(f"git -C {REPO_DIR} push -q")
    except Exception as ex:
        print(f"[warn] could not publish local heartbeat: {ex}")

def _mark_deferred(reason):
    """Record WHY we deferred so the dead-man's-switch tells waiting apart from broken.

    COMMITTED AND PUSHED, not just written: sync_repo() snaps this clone to origin/main
    at the start of every retry, so a local-only record was destroyed before anything
    could read it — observed 2026-08-09, when a real outage deferral left
    deferred_reason None an hour later and the watchdog had nothing to distinguish
    "waiting" from "broken"."""
    try:
        hb = os.path.join(REPO_DIR, "data", "digest_heartbeat.json")
        cur = json.load(open(hb)) if os.path.exists(hb) else {}
        cur["deferred_at"] = datetime.now().isoformat(timespec="seconds")
        cur["deferred_reason"] = reason
        json.dump(cur, open(hb, "w"), indent=1)
        sh(f"git -C {REPO_DIR} add data/digest_heartbeat.json")
        sh(f'git -C {REPO_DIR} -c user.name=radar-local -c user.email=radar@local '
           f'commit -q -m "digest deferred [skip ci]"')
        sh(f"git -C {REPO_DIR} pull --rebase -X ours -q")
        sh(f"git -C {REPO_DIR} push -q")
    except Exception:
        pass


def _network_up(host="api.github.com"):
    """A Mac woken from sleep often has no DNS yet. Sending into that burns the day's send on
    every channel at once. Observed 2026-08-09: 'Could not resolve host: github.com'."""
    import socket
    try:
        socket.getaddrinfo(host, 443)
        return True
    except Exception:
        return False


def _llm_available(timeout=45):
    """Capability probe — delegates to radar/joints.py, which ACTUALLY invokes the CLI.
    (The lesson lives there: a check that only asserted the binary existed let degraded
    digests ship for days. Exercise the capability, don't assert its existence.)"""
    try:
        from radar.joints import llm_available
        return llm_available(timeout)
    except Exception as ex:
        print(f"[defer] claude probe failed: {type(ex).__name__}")
        return False


def _sent_today():
    """Guard so the hourly retries cannot produce a second digest once one has gone out.

    last_digest is an EPOCH INT (report_local_health writes int(time.time())), but this
    guard compared its first ten DIGITS to an ISO date string — never equal, so the guard
    never fired and every awake hourly retry re-sent the full digest (five landed on
    2026-08-09 before anyone noticed; the defer gates had been masking it on mornings the
    laptop slept). Both encodings are now accepted; epoch is what production writes."""
    try:
        with open(os.path.join(REPO_DIR, "data", "digest_heartbeat.json")) as fh:
            last = json.load(fh).get("last_digest", "")
        if str(last).isdigit():
            return date.fromtimestamp(int(last)) == date.today()
        return str(last)[:10] == date.today().isoformat()
    except Exception:
        return False


def main():
    # A DRY run must be READ-ONLY beyond /tmp: it used to sync (or clone!) production,
    # advance last_ts (destroying tomorrow's ⭐ markers), start day-N clocks in
    # shown.json and fire Wayback requests — "verify before trusting it" mutated live
    # state. Caught by a 2026-08-10 cold audit exercising SETUP.md's own verify step.
    sync_status = sync_repo() if not DRY else "dry-skip"
    sys.path.insert(0, REPO_DIR)

    profile = yaml.safe_load(open(os.path.join(REPO_DIR, "config", "profile.yaml")))
    fresh_days = profile["scoring"].get("fresh_days", 14)
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"last_ts": 0, "notified_programs": []}
    since = state.get("last_ts", 0)
    notified = set(state.get("notified_programs", []))
    today = date.today()

    # Sent-today check FIRST: every hourly retry after a successful send was burning
    # 2-4 minutes of model time re-annotating 40 display rows before reaching the guard
    # (observed 2026-08-10). Nothing downstream matters if today's email already went.
    if not DRY and _sent_today():
        print("digest already sent today — nothing to do")
        return

    # ---- load queue ----
    allrows = []
    qpath = os.path.join(REPO_DIR, "data", "queue.jsonl")
    if os.path.exists(qpath):
        for line in open(qpath):
            try:
                allrows.append(json.loads(line))
            except Exception:
                continue
    # delta (new since last digest) — newsletters only; gov now flows through the main list
    newsletters = [r for r in allrows if r.get("ts", 0) > since and (r.get("cluster") == "newsletter" or r.get("type") == "newsletter")]

    # Rescue pass: AI-recheck EVERY new drop scoring >=40 (not just >=55), so the rule-scorer's
    # borderline calls get a semantic second opinion before anything is hidden. Updates scores in place.
    if not DRY:
        try:
            from radar.eligibility import filter_ineligible, last_run_quality, reset_quality
            new_drops = [r for r in allrows if r.get("ts", 0) > since and r.get("score", 0) >= 40
                         and r.get("cluster") != "newsletter"]   # gov included (T1 target)
            reset_quality()
            filter_ineligible(new_drops)
            _ok_b, _bad_b = last_run_quality()
            # "Is it available" and "did it work" are different questions. Overnight the probe
            # passed and then every batch timed out at 120s, so keyword-only scores shipped --
            # the exact degradation this logic exists to prevent. Judge the OUTPUT, not the tool.
            if _bad_b and _bad_b >= _ok_b and datetime.now().hour < 18:
                print(f"[defer] eligibility filter degraded ({_ok_b} ok / {_bad_b} failed) — not sending")
                _mark_deferred(f"eligibility filter degraded: {_ok_b} ok / {_bad_b} failed batches")
                return
        except Exception as ex:
            print(f"[warn] rescue eligibility filter unavailable: {ex}")

    # STANDING apply list: every role currently open <=fresh_days, fit >=55, deduped by company+title.
    display_floor = 55
    seen_ct, roles = set(), []
    for r in allrows:
        # gov/usajobs are NO LONGER dropped (2026-08-08): IC + cleared roles are a T1 target.
        # Only newsletter rows are excluded here — they are leads, not postings.
        if r.get("cluster") == "newsletter":
            continue
        if r.get("score", 0) < display_floor or not within_days(r, fresh_days):
            continue
        # US-only. Belt-and-braces: catches rows scored before the location gate existed.
        if not is_us_location(r.get("location", ""), r.get("department", "")):
            continue
        key = (r.get("company", "").lower(), r.get("title", "").lower())
        if key in seen_ct:
            continue
        seen_ct.add(key)
        r["_new"] = r.get("ts", 0) > since   # starred in the email
        roles.append(r)

    # QUEUE STATE: a row leaves the apply list only when the operator taps it. Nothing ages out on
    # its own — the "day N" counter is the pressure instead. See radar/queue_state.py.
    from radar import queue_state as qs
    _done = qs.acted_ids()
    roles = [r for r in roles if qs.job_id(r) not in _done]
    # 👍/👎 verdict taps (2026-08-15): a 👎 is a tap, so the row leaves the list —
    # consistent with "rows leave only when tapped". A 👍 keeps the row (the operator
    # still has to apply) and marks it. Mis-taps recover via the flip link, last tap wins.
    _verd = qs.verdicts()
    roles = [r for r in roles if _verd.get(qs.job_id(r)) != "no"]
    _shown = qs.mark_shown(roles) if not DRY else {}   # mark_shown writes shown.json + Wayback
    _relay = RELAY_BASE                                # unset -> raw links, never dead links

    # ---- sort: freshest postings first ----
    # MUST run before the display eligibility pass below: that pass vets only the first
    # 40 un-noted rows, and slicing before sorting meant "top slice" was queue-file
    # order, not email order — a full-time "Product Manager | International" shipped
    # unvetted at the TOP of the 2026-08-15 email while 40 rows the operator would never
    # scroll to were vetted instead. Sorting first makes the vetted slice the visible slice.
    roles.sort(key=lambda r: (str(r.get("posted_at") or "0000"), r.get("ts", 0), r.get("score", 0)), reverse=True)

    # Re-rank what we are ABOUT TO DISPLAY, not only what is new. The rescue pass above is
    # incremental (ts > since), so on any queue with history the backlog never meets the model
    # and the email shows rows with no reasoning at all — verified: 117 displayed rows, 0
    # reasons. Bounded to the top slice so a large queue cannot blow the digest's time budget.
    if not DRY:
        try:
            from radar.eligibility import filter_ineligible as _fi, last_run_quality as _lq, reset_quality as _rq
            stale = [r for r in roles if not r.get("eligibility_note")][:40]
            if stale:
                # batch_size 10, not 20: a 20-row batch still exceeded 300s on the small model
                # (observed 1 of 2 batches failing), and a failed batch means those rows show
                # with no reasoning at all. Smaller batches fail less and fail cheaper.
                _rq(); _fi(stale, band=(0, 100), batch_size=10, timeout=900)
                _o, _b = _lq()
                print(f"[eligibility] display pass: {len(stale)} rows, {_o} ok / {_b} failed")
                if _b and _b >= _o and datetime.now().hour < 18:
                    # Same rule as the rescue pass. Rows reaching the email with no reasoning
                    # is the degradation, and it was ungated here.
                    print("[defer] display eligibility filter degraded — not sending; will retry")
                    _mark_deferred(f"display eligibility filter degraded: {_o} ok / {_b} failed")
                    return
        except Exception as ex:
            print(f"[warn] display eligibility filter unavailable: {ex}")
        # Drop ONLY what the model flagged as impossible to apply to. Re-applying the score
        # floor here would let the model silently delete qualifying jobs — which is what it was
        # doing when it graded "fit + interest + career value" instead of eligibility.
        _cut = [r for r in roles if r.get("ineligible")]
        roles = [r for r in roles if not r.get("ineligible")]
        if _cut:
            print("[eligibility] removed as ineligible: " +
                  "; ".join(f"{r.get('company','?')} — {r.get('eligibility_note','')}" for r in _cut))

    # ---- DEFER, DON'T DEGRADE (2026-08-08 per the operator) ----
    # A 10/10 email at 9am beats a 7/10 at 7:20. If the local Claude eligibility filter cannot run —
    # laptop asleep, CLI missing, session dead — do NOT send a rule-scored-only digest.
    # Exit quietly; launchd retries hourly and fires the moment the machine is usable.
    # Hard backstop at 18:00: a late good email beats a bad one, but NO email beats both.
    if not DRY and _sent_today():
        print("digest already sent today — nothing to do")
        return
    if not DRY and not _network_up() and datetime.now().hour < 18:
        print("[defer] no network (likely just woke) — not sending; will retry")
        _mark_deferred("no network at wake")
        return
    if not DRY and not _llm_available() and datetime.now().hour < 18:
        # Record the deferral so the dead-man's-switch can tell "waiting for a usable machine"
        # apart from "the digest is broken". Without this, every deferred morning would page
        # the operator with a false stale-digest alarm and the alert would stop meaning anything.
        _mark_deferred("local Claude eligibility filter unavailable")
        print("[defer] LLM unavailable and it is before 18:00 — not sending; will retry")
        return

    sent = []

    # ================= EMAIL #1 — NETWORKING HEADS-UP =================
    # Missing calendar = email #1 quietly absent, never a crash (a fresh fork has no
    # calendar yet; the example ships in the open repo and the nightly joint refreshes it)
    _calp = os.path.join(REPO_DIR, "config", "release_calendar.yaml")
    cal = (yaml.safe_load(open(_calp)) or []) if os.path.exists(_calp) else []
    horizon = today + timedelta(days=14)
    # NAGS DAILY (changed 2026-08-08). The old `notified` set showed each program EXACTLY ONCE,
    # ever — so a single busy morning meant that networking window was never mentioned again.
    # A program now repeats every day until the operator taps "done", and stops on its own when the
    # req actually posts, which is the only real end state for pre-networking.
    _netdone = qs.acted_ids("networked")
    upcoming = []
    for e in cal:
        try:
            d = date.fromisoformat(str(e.get("expected_open", "")))
        except Exception:
            continue
        if today <= d <= horizon and qs.program_id(e.get("program", "")) not in _netdone:
            upcoming.append((d, e))
    upcoming.sort(key=lambda t: t[0])
    # Standing reminder on every email (2026-08-15): warm-intro lookup exists but is
    # on-demand only — the operator asks their agent; nothing auto-runs.
    REMIND = ("<p style='background:#f0f9ff;border-left:3px solid #0284c7;padding:6px 10px;"
              "font-size:12px;color:#0c4a6e;margin:0 0 12px'>💡 Tip: ask your agent to find "
              "warm-intro contacts for any role here before you apply — e.g. a FullEnrich "
              "alumni lookup (people from your school at the hiring company). See "
              "“Warm intros” in the README.</p>")
    if upcoming:
        h = [WRAP_OPEN, REMIND,
             "<h2 style='margin:0 0 4px'>🔔 Opening within 14 days — start referral outreach NOW</h2>",
             "<p style='color:#555;margin:0 0 14px'>Repeats daily until you tap <b>done</b>, or until the req posts "
             "and moves to your apply list. <b>find people</b> opens the LinkedIn search; it never clears the row.</p><ul>"]
        for d, e in upcoming:
            pid = qs.program_id(e.get("program", ""))
            find = qs.people_search_url(e.get("company", "") or e.get("program", ""))
            donel = qs.relay("", {"url": "", "company": e.get("program", "")}, _relay,
                             action="networked", override_id=pid)
            days_out = (d - today).days
            h.append(f"<li style='margin-bottom:10px'><b>{md(e['program'])}</b> — expected ~{d} "
                     f"<span style='color:#b45309'>({days_out}d out)</span> "
                     f"<a href='{find}' style='color:#1d4ed8'>find people</a> · "
                     f"<a href='{donel}' style='color:#059669'>✓ done</a><br>"
                     f"({e.get('confidence','?')} confidence). {md(e.get('deadline_behavior',''))} "
                     f"<i style='color:#777'>{md(e.get('requirements',''))}</i></li>")
        h.append("</ul></div>")
        if send_email("📜Pre-network for these roles dropping in 2 weeks", "".join(h)):
            sent.append(f"#1 networking ({len(upcoming)})")

    # ================= EMAIL #2 — DAILY APPLY LIST =================
    n_new = sum(1 for r in roles if r.get("_new"))
    h = [WRAP_OPEN, REMIND,
         f"<h2 style='margin:0 0 6px'>📥 Your apply list — {len(roles)} open, none drop off until you tap "
         f"<span style='color:#666;font-weight:normal'>({n_new} ⭐new since yesterday)</span></h2>",
         "<p style='font-size:12px;margin:0 0 12px'>" + " ".join(badge(k) for k in
             ["defense", "space", "robotics", "ai_lab", "consulting", "corporate", "vc_portfolio", "startup_other"]) + "</p>"]
    if roles:
        h.append("<table cellpadding=6 style='border-collapse:collapse;width:100%'>")
        h.append("<tr style='border-bottom:2px solid #ccc'><th align=left>Type</th><th align=left>Score</th>"
                 "<th align=left>Company</th><th align=left>Role</th><th align=left>Why / note</th><th></th></tr>")
        # No cap (2026-08-08): the apply list is a queue the operator works to zero, so silently
        # truncating at 60 loses roles. Volume is bounded by the T3 floor, not by a slice.
        # Grouped by WHEN THE ROLE WAS POSTED, newest bucket first, so the freshest reqs —
        # the ones where applying early actually moves the odds — sit at the top.
        buckets = {}
        for r in roles:
            buckets.setdefault(qs.bucket(r), []).append(r)
        for bname in qs.BUCKET_ORDER:
            brows = buckets.get(bname)
            if not brows:
                continue
            h.append(f"<tr><td colspan=6 style='padding:15px 6px 5px;font-weight:700;"
                     f"border-bottom:1px solid #ddd'>{bname} ({len(brows)})</td></tr>")
            for r in brows:
                note = md(r.get("eligibility_note") or r.get("funding") or "")[:180]   # 20-word reasons need the room
                # Why-matched (2026-08-15): the system's own reasons, already computed —
                # cluster, tier, matched keywords. Deterministic, no model call. Lets a
                # mis-scored row be spotted at a glance.
                _kw = ", ".join(r.get("matched_keywords", [])[:3])
                why = " · ".join(x for x in (r.get("cluster", ""), r.get("tier", ""), _kw) if x)
                if why:
                    note = f"<span style='color:#9ca3af;font-size:11px'>[{md(why)}]</span><br>{note}"
                posted = r.get("posted_at") or datetime.fromtimestamp(r.get("ts", 0)).strftime("%m-%d") + "~"
                star = "⭐ " if r.get("_new") else ""
                nd = qs.days_shown(r, _shown)
                # Sitting-here-N-days pressure. Silence would let a role rot quietly; this is
                # what replaces the old 14-day auto-expiry.
                age = (f"<span style='color:#b45309;font-size:11px'> · day {nd}</span>" if nd >= 1 else "")
                # Pay when the board published it (Lever/Ashby/speedrun carry it; most don't).
                pay = (f" · <span style='color:#059669'>{md(str(r.get('pay','')))[:24]}</span>"
                       if r.get("pay") else "")
                link = qs.relay(r.get("url", ""), r, _relay)
                # 👍/👎 verdict buttons: relay taps with no destination — they log feedback
                # and land on a confirmation page, never on the posting. 👍 marks the row;
                # 👎 removes it tomorrow. Weekly, the taps train the matching (proposals only).
                thumb = " 👍" if _verd.get(qs.job_id(r)) == "yes" else ""
                ylink = qs.relay("", r, _relay, action="yes")
                nlink = qs.relay("", r, _relay, action="no")
                vbtns = ("" if not _relay else
                         f"<br><a href='{ylink}' style='background:#059669;color:#fff;padding:1px 7px;"
                         f"border-radius:4px;text-decoration:none;font-size:11px'>✓</a>&nbsp;"
                         f"<a href='{nlink}' style='background:#dc2626;color:#fff;padding:1px 7px;"
                         f"border-radius:4px;text-decoration:none;font-size:11px'>✗</a>")
                h.append("<tr style='border-bottom:1px solid #eee'>"
                         f"<td>{badge(r.get('industry','startup_other'))}</td>"
                         f"<td>{star}<b>{r.get('score',0)}</b></td>"
                         f"<td>{md(r.get('company',''))}{thumb}</td>"
                         f"<td>{md(r.get('title',''))}{' 🔄' if r.get('offcycle') else ''}"
                         f"<br><span style='color:#888;font-size:11px'>{posted} · "
                         f"{md(r.get('location',''))[:35]}{pay}</span>{age}</td>"
                         f"<td style='font-size:12px;color:#444'>{note}</td>"
                         f"<td><a href='{link}' style='color:#1d4ed8'>apply→</a>{vbtns}</td></tr>")
        h.append("</table>")
    else:
        h.append("<p>No fresh matches today.</p>")

    # Weekly verdict patterns (2026-08-15): what the 👍/👎 taps imply, per the
    # feedback_patterns joint. Proposals only — the operator applies any of them by
    # telling their agent in a session; the digest never edits config. Shown while
    # fresh (<8 days), then silent until the next analysis.
    try:
        _fpp = os.path.join(REPO_DIR, "data", "feedback_patterns.json")
        _fp = json.load(open(_fpp)) if os.path.exists(_fpp) else {}
        if _fp.get("proposals") and time.time() - _fp.get("ts", 0) < 8 * 86400:
            h.append(f"<h3>🧠 What your taps say ({_fp.get('verdict_count', 0)} verdicts analyzed)</h3><ul>")
            for p in _fp["proposals"][:7]:
                h.append(f"<li><b>{md(p.get('pattern',''))}</b> "
                         f"<span style='color:#888'>({md(p.get('evidence',''))})</span><br>"
                         f"<i style='color:#0c4a6e'>Proposal: {md(p.get('proposal',''))}</i></li>")
            h.append("</ul><p style='font-size:12px;color:#555'>To act on any of these, "
                     "tell your agent — nothing is applied automatically.</p>")
    except Exception as ex:
        print(f"[warn] feedback patterns section skipped: {ex}")

    # funding radar + newsletters as compact intel sections
    try:
        from radar.funding import recent_big_form_ds
        raises = recent_big_form_ds(days=1, min_amount=60_000_000)[:10]
    except Exception:
        raises = []
    if raises:
        h.append("<h3>💰 Fresh $60M+ raises (last 24h) — staffing up soon, get in early</h3><ul>")
        for r in raises:
            h.append(f"<li>${r['amount']/1e6:.0f}M — <b>{md(r['company'])}</b> ({md(r['industry'])}) "
                     f"— <a href='{r['filing']}'>filing</a></li>")
        h.append("</ul>")
    if newsletters:
        h.append(f"<h3>📰 Newsletter drops ({len(newsletters)})</h3><ul>")
        for r in newsletters[:12]:
            h.append(f"<li><b>{md(r['company'])}</b>: <a href='{r['url']}'>{md(r['title'])}</a></li>")
        h.append("</ul>")
    # gov weekly section REMOVED 2026-08-08: gov/IC now flows through the main apply list
    # daily like every other family. The 'Gov/Intel' badge still labels those rows.

    r2 = send_email(f"📜Review & Apply — {len(roles)} open (≤ {fresh_days}d)", "".join(h))
    if r2:
        sent.append(f"#2 daily ({len(roles)})")

    # ---- persist state (never on DRY: advancing last_ts on a dry run erases the
    # new-since-yesterday window for the real morning send) ----
    if not DRY:
        state["last_ts"] = int(time.time())
        state["notified_programs"] = sorted(notified)
        json.dump(state, open(STATE, "w"))

    # Only if a send fell back to the GitHub relay does anything need pushing.
    pend_dir = os.path.join(REPO_DIR, "data", "pending")
    if not DRY and os.path.isdir(pend_dir) and os.listdir(pend_dir):
        sh(f"git -C {REPO_DIR} add data/pending")
        sh(f'git -C {REPO_DIR} -c user.name=radar-local -c user.email=radar@local commit -m "digest pending (fallback)"')
        sh(f"git -C {REPO_DIR} pull --rebase -X ours")
        push = sh(f"git -C {REPO_DIR} push")
        if push.returncode != 0:
            print("push failed:", push.stderr[:200])
    print("digest done:", ", ".join(sent) if sent else "nothing sent")
    if not DRY:
        report_local_health(sync_status, sent)

if __name__ == "__main__":
    main()
