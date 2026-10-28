"""LOCAL pre-digest job (launchd ~7:05am): Scrapling-fetch bot-walled public corporates,
score them, append new ones to the repo queue, push. The 6:00 digest then includes them.
Also refreshes deadline pages weekly (Sundays) via Scrapling where they're public."""
import json, os, subprocess, sys, time
import yaml

REPO = os.path.expanduser("~/.internship-radar")
sys.path.insert(0, REPO)

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO)

def queue_newsletters(newsletters, seen, q, now=None, max_age_days=14):
    """Job newsletters (Substack RSS) -> digest queue, no instant alert. Moved here from the
    cloud poll 2026-10-28: Substack answers GitHub's runners with 403 on every run, so the
    digest's newsletter section had gone empty. From the Mac the feeds load. Issues older
    than max_age_days are marked seen but not queued, so the backlog from the blocked
    months doesn't flood one digest."""
    import hashlib
    from email.utils import parsedate_to_datetime
    from radar.fetchers import fetch_substack
    now = now or time.time()
    n = 0
    for nl in newsletters:
        try:
            for item in fetch_substack(nl["name"], nl["sub"]):
                k = hashlib.sha1(f"{item['company']}|{item['title']}|{item['url']}".lower().encode()).hexdigest()[:16]
                if k in seen:
                    continue
                seen[k] = int(now)
                try:
                    age_days = (now - parsedate_to_datetime(item["posted_at"]).timestamp()) / 86400
                except (TypeError, ValueError):
                    age_days = 0          # undated: queue it rather than lose it
                if age_days > max_age_days:
                    continue
                q.write(json.dumps({**item, "score": 0, "cluster": "newsletter",
                                    "angle": "", "ts": int(now)}) + "\n")
                n += 1
        except Exception as ex:
            print(f"[warn] newsletter {nl['name']}: {ex}")
    return n

def main():
    sh("git pull --ff-only")
    from radar.scrapling_fetch import fetch_all_scrapling
    from radar.score import score_posting
    import hashlib

    profile = yaml.safe_load(open(os.path.join(REPO, "config", "profile.yaml")))
    seenp = os.path.join(REPO, "data", "seen.json")
    qp = os.path.join(REPO, "data", "queue.jsonl")
    seen = json.load(open(seenp)) if os.path.exists(seenp) else {}
    funded = {}
    fp = os.path.join(REPO, "data", "funded_watch.json")
    if os.path.exists(fp):
        funded = {k: v for k, v in json.load(open(fp)).items() if not k.startswith("_") and isinstance(v, dict)}

    postings, errors = fetch_all_scrapling()
    for e in errors:
        print("[warn]", e)
    n = 0
    with open(qp, "a") as q:
        for p in postings:
            k = hashlib.sha1(f"{p['company']}|{p['title']}|{p['url']}".lower().encode()).hexdigest()[:16]
            if k in seen:
                continue
            seen[k] = int(time.time())
            score, brief = score_posting(p, profile, funded)
            if score is None:
                continue
            q.write(json.dumps({**p, "score": score, **brief, "ts": int(time.time())}) + "\n")
            n += 1
    json.dump(seen, open(seenp, "w"))
    print(f"scrapling scraped {len(postings)} listings, {n} new scored")

    sources = yaml.safe_load(open(os.path.join(REPO, "config", "sources.yaml")))
    with open(qp, "a") as q:
        nn = queue_newsletters(sources.get("newsletters", []), seen, q)
    json.dump(seen, open(seenp, "w"))
    print(f"newsletters: {nn} new issues queued")

    # ---- Cloudflare-walled deadline trackers: alert on change (Scrapling gets 200 where plain GET 403s).
    # These are calendars, not job lists, so they're watched for edits rather than parsed into postings.
    watch = {
        "Consulting application deadlines (ManagementConsulted)":
            "https://managementconsulted.com/consulting-application-deadlines/",
    }
    try:
        from scrapling.fetchers import StealthyFetcher
        import re as _re
        for name, url in watch.items():
            try:
                page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
                if page.status != 200:
                    print(f"[warn] watch {name}: HTTP {page.status}")
                    continue
                body = _re.sub(r"\s+", " ", page.get_all_text())
                digest_ = hashlib.sha1(body.encode()).hexdigest()
                key = f"cfwatch:{url}"
                prev = seen.get(key)
                seen[key] = digest_
                if prev and prev != digest_:
                    sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
                    import mailer

                    # identity comes from settings, never a literal (cold-audit fix)
                    from radar.settings import SEND_AS, TO_ADDR
                    mailer.send(SEND_AS, TO_ADDR,
                                f"📜Deadline page changed — {name}",
                                f"<p><b>{name}</b> changed since the last check.</p>"
                                f"<p><a href='{url}'>{url}</a></p>"
                                f"<p>Consulting cycles move fast and these are hard deadlines — "
                                f"check what shifted.</p>")
                    print(f"[alert] {name} changed -> emailed")
            except Exception as ex:
                print(f"[warn] watch {name}: {ex}")
    except Exception as ex:
        print(f"[warn] scrapling watch unavailable: {ex}")
    json.dump(seen, open(seenp, "w"))
    sh("git add data/")
    sh('git -c user.name=radar -c user.email=radar@localhost commit -m "local scrapling corporates [skip ci]"')
    # seen.json merges as a key union (radar/merge_seen.py); without the driver configured,
    # this pull falls back to -X ours and drops every key this run just recorded.
    sh('git config merge.seen.driver "python3 -m radar.merge_seen %O %A %B"')
    sh("git pull --rebase -X ours")
    sh("git push")

if __name__ == "__main__":
    main()
