"""Dead-man's switch. Runs DAILY on GitHub Actions, independent of the poller.
- If the poller hasn't succeeded in >8h -> open a 🚨 SYSTEM DOWN issue (you get emailed).
- On Mondays, if healthy -> open a ✅ weekly heartbeat with stats.
- Otherwise stays silent.
If THIS stops emailing on Mondays, the whole system (incl. this watcher) is down -> investigate.
Its own daily run also keeps the repo active so GitHub never auto-disables the schedules."""
import json, os, time, urllib.request
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
                     f"- Dedup memory: {hb.get('seen_now','?')} entries (pruned to 90d)\n"
                     f"- Dark sources: {', '.join(dark) if dark else 'none 🎉'}\n"
                     f"- Morning digest: {('ran %.1fh ago' % dage_h) if dage_h is not None else 'no report yet'}\n\n"
                     f"If you ever stop getting this Monday email, the whole radar is down. {MENTION}",
                     ["health", "heartbeat"])
        print("weekly heartbeat sent")
    else:
        print(f"healthy, silent (age {age_h:.1f}h)")

if __name__ == "__main__":
    main()
