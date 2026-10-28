"""Dead-man's switch. Runs DAILY on GitHub Actions, independent of the poller.
- If the poller hasn't succeeded in >8h -> open a 🚨 SYSTEM DOWN issue (you get emailed).
- On Mondays, if healthy -> open a ✅ weekly heartbeat with stats.
- Otherwise stays silent.
If THIS stops emailing on Mondays, the whole system (incl. this watcher) is down -> investigate.
Its own daily run also keeps the repo active so GitHub never auto-disables the schedules."""
import json, math, os, time, urllib.request
from datetime import date, datetime, timezone

from radar.settings import MENTION

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def create_issue(repo, token, title, body, labels):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body, "labels": labels}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "internship-radar"})
    urllib.request.urlopen(req, timeout=20)

def _api(path, token):
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "internship-radar"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def billed_minutes(runs):
    """GitHub bills each job rounded UP to a whole minute, and every workflow here is one job,
    so a run costs ceil(seconds / 60). Run time includes a few seconds of queue, so this
    overestimates slightly, which is the safe direction for a budget alarm."""
    total = 0
    for r in runs:
        if r.get("status") != "completed" or not r.get("run_started_at"):
            continue
        start = datetime.fromisoformat(r["run_started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00"))
        total += max(1, math.ceil((end - start).total_seconds() / 60))
    return total

def project_month(used, now):
    """Straight-line projection of this month's minutes from the share of the month elapsed."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    elapsed = (now - start) / (nxt - start)
    return round(used / elapsed) if elapsed > 0 else used

def minutes_check(repo, token, quota, now=None):
    """Actions-minutes budget alarm (2026-10-28: frequent polling spends most of the plan's
    included minutes). When they run out GitHub stops every workflow, this watcher included,
    so nothing would report the outage. Warn while there is still time to act."""
    now = now or datetime.now(timezone.utc)
    runs, page = [], 1
    while True:
        got = _api(f"repos/{repo}/actions/runs?per_page=100&page={page}"
                   f"&created=>={now:%Y-%m}-01", token).get("workflow_runs", [])
        runs += got
        if len(got) < 100:
            break
        page += 1
    used = billed_minutes(runs)
    projected = project_month(used, now)
    if now.day >= 3 and projected > 0.9 * quota:
        if _api(f"repos/{repo}/issues?labels=minutes&state=open", token):
            return used, projected      # already warned; one open issue is enough
        create_issue(repo, token,
                     f"⚠️ Actions minutes: on pace for {projected:,} of {quota:,} this month",
                     f"**{used:,}** minutes used so far this month, projecting **{projected:,}** "
                     f"against the plan's **{quota:,}**. When they run out GitHub stops every "
                     f"workflow (alerts, apply-log taps, this watcher) until the 1st.\n\n"
                     f"Fixes: check why poll runs got slower (a run over 60s bills 2 minutes), "
                     f"poll less often in `.github/workflows/poll.yml`, or set an Actions budget at "
                     f"https://github.com/settings/billing. Close this issue once handled. {MENTION}",
                     ["health", "minutes"])
        print(f"minutes alert sent ({used} used, {projected} projected, quota {quota})")
    return used, projected

def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    hb_path = os.path.join(ROOT, "data", "heartbeat.json")
    hb = json.load(open(hb_path)) if os.path.exists(hb_path) else {}
    now = int(time.time())
    last = hb.get("last_poll", 0)
    if not last:
        print("no heartbeat yet (cold start) — staying silent")
        return
    age_h = (now - last) / 3600

    # Before the DOWN check, which returns early: a quota running out is one cause of DOWN.
    quota = int(os.environ.get("ACTIONS_MINUTES_QUOTA", "2000"))
    try:
        used, projected = minutes_check(repo, token, quota)
    except Exception as ex:
        used = projected = None
        print(f"[warn] minutes check failed: {ex}")

    if age_h > 8:
        create_issue(repo, token,
                     f"🚨 Radar DOWN — no successful poll in {age_h:.0f}h",
                     f"The poller has not written a heartbeat in **{age_h:.1f} hours** "
                     f"(last: {datetime.fromtimestamp(last, timezone.utc).isoformat() if last else 'never'}).\n\n"
                     f"The cloud engine may be broken or GitHub Actions disabled. Check the Actions tab: "
                     f"https://github.com/{repo}/actions . {MENTION}", ["health", "down"])
        print(f"DOWN alert sent (age {age_h:.1f}h)")
        return

    # Local-side watchdog: the 6:00am Mac digest publishes data/digest_heartbeat.json on each run.
    # Stale => that digest is dead (launchd unloaded, python broken, mail credential revoked) and
    # the operator would otherwise just assume the market went quiet. 40h tolerates a closed laptop.
    dage_h = None
    dpath = os.path.join(ROOT, "data", "digest_heartbeat.json")
    if os.path.exists(dpath):
        try:
            dhb = json.load(open(dpath))
            dage_h = (now - dhb.get("last_digest", 0)) / 3600
            if dage_h > 40:
                create_issue(repo, token,
                             f"⚠️ Morning digest silent for {dage_h:.0f}h",
                             f"Cloud polling is healthy, but the local 6:00am digest hasn't reported in "
                             f"**{dage_h:.1f}h**. Likely: Mac off for a long stretch, the launchd job was "
                             f"unloaded, or the Gmail app password was revoked.\n\nCheck "
                             f"`launchctl list | grep internship` and `tail /tmp/internship-digest.log`. "
                             f"{MENTION}", ["health", "digest"])
                print(f"digest-stale alert sent ({dage_h:.1f}h)")
        except Exception as ex:
            print(f"[warn] digest heartbeat unreadable: {ex}")

    if datetime.now(timezone.utc).weekday() == 0:  # Monday summary
        dark = hb.get("dark_sources", [])
        create_issue(repo, token,
                     f"✅ Radar weekly heartbeat — alive ({hb.get('postings','?')} scanned last run)",
                     f"System healthy. Last poll {age_h:.1f}h ago.\n\n"
                     f"- Postings scanned last run: **{hb.get('postings','?')}**\n"
                     f"- New roles scored: {hb.get('new_scored','?')}\n"
                     f"- Burning alerts last run: {hb.get('alerts','?')}\n"
                     f"- Dedup memory: {hb.get('seen_now','?')} entries (postings 90d, alerts 1y)\n"
                     f"- Actions minutes this month: {used if used is not None else '?'} used, "
                     f"on pace for {projected if projected is not None else '?'} of {quota}\n"
                     f"- Dark sources: {', '.join(dark) if dark else 'none 🎉'}\n"
                     f"- Morning digest: {('ran %.1fh ago' % dage_h) if dage_h is not None else 'no report yet'}\n\n"
                     f"If you ever stop getting this Monday email, the whole radar is down. {MENTION}",
                     ["health", "heartbeat"])
        print("weekly heartbeat sent")
    else:
        print(f"healthy, silent (age {age_h:.1f}h)")

if __name__ == "__main__":
    main()
