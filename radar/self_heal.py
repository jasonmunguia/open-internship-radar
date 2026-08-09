"""Self-healing for dark sources.

Runs LOCALLY via launchd whenever the Mac is awake (every 30 min + at load), so a failure that
occurs while the laptop is closed is repaired the moment it comes back on.

Escalation ladder — cheapest first, because most "source went dark" alerts are transient
(the Anduril alert on 2026-07-30 was a blip; its board served 2,142 jobs minutes later):

  1. RE-PROBE   — call the source again. Recovered? Close the issue, stay quiet. 0 tokens.
  2. REDISCOVER — assume an ATS migration (the common real failure: Skydio moved Greenhouse->Ashby
                  mid-build). Try slug variants across every known platform; if one serves jobs,
                  rewrite config/sources.yaml, commit, push. 0 tokens.
  3. ESCALATE   — hand full context to Claude Code headless (`claude -p`) to diagnose and patch.
                  Rate-limited to one escalation per source per 24h so a dead company can't loop.
  4. REPORT     — email the outcome either way. Silence is never the answer.
"""
import json
import os
import re
import subprocess
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HEALTH = os.path.join(ROOT, "data", "health.json")
SOURCES = os.path.join(ROOT, "config", "sources.yaml")
STATE = os.path.join(ROOT, "data", "heal_state.json")
DARK_STREAK = 3            # matches poll.py's alert threshold
ESCALATE_COOLDOWN = 86400


def _person():
    """Delivery settings from config/person.yaml when present; owner defaults otherwise."""
    try:
        with open(os.path.join(ROOT, "config", "person.yaml")) as fh:
            p = yaml.safe_load(fh) or {}
        return (p.get("identity", {}).get("repo") or "<you>/internship-radar",
                p.get("delivery", {}).get("to") or "you@example.edu",
                p.get("delivery", {}).get("send_as") or "personal")
    except Exception:
        return "<you>/internship-radar", "you@example.edu", "personal"


REPO, TO_ADDR, SEND_AS = _person()


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)


def _load(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default


def probe(ats, token):
    """Does this source return jobs right now? -> (ok, count_or_error)."""
    from radar import fetchers
    fns = {"greenhouse": fetchers.fetch_greenhouse, "lever": fetchers.fetch_lever,
           "ashby": fetchers.fetch_ashby, "getro": fetchers.fetch_getro,
           "consider": fetchers.fetch_consider, "manatal": fetchers.fetch_manatal,
           "workday": getattr(fetchers, "fetch_workday", None),
           "smartrecruiters": getattr(fetchers, "fetch_smartrecruiters", None),
           "eightfold": getattr(fetchers, "fetch_eightfold", None)}
    standalone = {"a16z": fetchers.fetch_a16z, "amazon": fetchers.fetch_amazon,
                  "bcg": fetchers.fetch_bcg, "rippling": fetchers.fetch_rippling,
                  "speedrun": fetchers.fetch_speedrun}
    try:
        if fns.get(ats):
            return True, len(fns[ats]("probe", token))
        if ats in standalone:
            return True, len(standalone[ats]())
    except Exception as ex:
        return False, str(ex)[:200]
    return False, f"no probe available for ats={ats}"


def slug_variants(company, current):
    """Plausible org slugs for a company whose board moved."""
    base = re.sub(r"[^a-z0-9 ]", "", company.lower()).strip()
    words = base.split()
    joined = "".join(words)
    cands = [current, joined, "-".join(words), (words[0] if words else joined),
             joined + "industries", joined + "careers", joined + "-careers",
             joined.replace("industries", ""), joined + "hq", joined + "inc"]
    seen, out = set(), []
    for s in cands:
        s = (s or "").strip("-")
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def rediscover(company, current_ats, current_token):
    """Hunt the company's board across standard ATSes. -> (ats, token, count) or None."""
    from radar import fetchers
    platforms = [("greenhouse", fetchers.fetch_greenhouse), ("ashby", fetchers.fetch_ashby),
                 ("lever", fetchers.fetch_lever)]
    if getattr(fetchers, "fetch_smartrecruiters", None):
        platforms.append(("smartrecruiters", fetchers.fetch_smartrecruiters))
    for ats, fn in platforms:
        for token in slug_variants(company, current_token):
            if ats == current_ats and token == current_token:
                continue
            try:
                jobs = fn(company, token)
                if jobs:
                    return ats, token, len(jobs)
            except Exception:
                pass
            time.sleep(0.15)
    return None


def apply_fix(name, new_ats, new_token):
    """Rewrite this source's entry in sources.yaml. True if the file changed."""
    with open(SOURCES) as fh:
        text = fh.read()
    pat = re.compile(r"(\{name:\s*%s\s*,\s*ats:\s*)([a-z0-9_]+)(\s*,\s*token:\s*)([^}]+)(\})"
                     % re.escape(name), re.I)
    new_text, n = pat.subn(lambda m: f"{m.group(1)}{new_ats}{m.group(3)}{new_token}{m.group(5)}", text)
    if n:
        with open(SOURCES, "w") as fh:
            fh.write(new_text)
    return bool(n)


def escalate(name, ats, token, err):
    """Last resort: Claude Code diagnoses and patches it, headlessly."""
    claude = os.path.expanduser("~/.local/bin/claude")
    if not os.path.exists(claude):
        claude = "claude"
    prompt = (
        f"The internship-radar job source '{name}' has failed {DARK_STREAK}+ consecutive polls and "
        f"automated repair could not fix it.\n\n"
        f"Configured as: ats={ats}, token={token} in config/sources.yaml\n"
        f"Probe error: {err}\n\n"
        f"Find this company's CURRENT public job-board API endpoint — they may have migrated ATS "
        f"platforms, renamed their org slug, or gone private. Then EITHER update its entry in "
        f"config/sources.yaml to the working platform/token, OR, if no public board exists anymore, "
        f"remove the entry and note it under 'Known gaps' in README.md.\n\n"
        f"Verify the fix actually returns jobs before finishing. Make the minimal edit; do not "
        f"refactor anything else; do not commit (the caller commits)."
    )
    try:
        r = subprocess.run([claude, "-p", prompt, "--permission-mode", "acceptEdits"],
                           cwd=ROOT, capture_output=True, text=True, timeout=900)
        return r.returncode == 0, (r.stdout or r.stderr or "")[-500:]
    except Exception as ex:
        return False, str(ex)[:300]


def close_issues(name):
    """Close open [health] issues for a source that works again."""
    gh = os.path.expanduser("~/.local/bin/gh")
    if not os.path.exists(gh):
        return
    q = sh(f'{gh} issue list --repo {REPO} --label health --state open --json number,title '
           f'-q \'.[] | select(.title | contains("{name}")) | .number\'')
    for num in [x for x in q.stdout.split() if x.isdigit()]:
        sh(f'{gh} issue close {num} --repo {REPO} -c "Auto-healed: source is serving jobs again."')


def notify(subject, body_html):
    try:
        sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
        import mailer
        if mailer.has_password(SEND_AS):
            mailer.send(SEND_AS, TO_ADDR, subject, body_html)
            return True
    except Exception as ex:
        print(f"[warn] notify failed: {ex}")
    return False


def main():
    sh("git fetch -q origin && git reset --hard origin/main -q && git clean -fd -q")

    health = _load(HEALTH, {})
    state = _load(STATE, {})
    sources = yaml.safe_load(open(SOURCES)) or {}
    by_name = {e["name"]: e for e in sources.get("ats", []) if isinstance(e, dict)}

    dark = [n for n, v in health.items()
            if isinstance(v, dict) and v.get("streak", 0) >= DARK_STREAK]
    if not dark:
        print("no dark sources — nothing to heal")
        return

    healed, fixed, failed = [], [], []
    for name in dark:
        entry = by_name.get(name)
        if not entry:
            print(f"[skip] {name}: not an ATS entry (repo/newsletter sources self-recover)")
            continue
        ats, token = entry.get("ats"), str(entry.get("token"))

        ok, info = probe(ats, token)                        # 1. re-probe
        if ok and info:
            print(f"[recovered] {name}: {info} jobs — transient failure")
            close_issues(name)
            healed.append(f"{name} ({info} jobs)")
            continue

        found = rediscover(entry["name"], ats, token)       # 2. rediscover
        if found:
            new_ats, new_token, count = found
            if apply_fix(name, new_ats, new_token):
                print(f"[fixed] {name}: {ats}:{token} -> {new_ats}:{new_token} ({count} jobs)")
                fixed.append(f"{name}: <code>{ats}:{token}</code> &rarr; "
                             f"<code>{new_ats}:{new_token}</code> ({count} jobs)")
                close_issues(name)
                continue

        last = state.get(name, {}).get("last_escalation", 0)  # 3. escalate
        if time.time() - last < ESCALATE_COOLDOWN:
            print(f"[skip] {name}: already escalated within 24h")
            continue
        state.setdefault(name, {})["last_escalation"] = int(time.time())
        print(f"[escalate] {name}: handing to Claude Code…")
        ok_c, out = escalate(name, ats, token, info)
        (fixed if ok_c else failed).append(
            f"{name}: Claude {'patched it' if ok_c else 'could not fix it'} — <code>{info}</code>")

    json.dump(state, open(STATE, "w"))

    if fixed:
        sh("git add config/sources.yaml README.md data/heal_state.json")
        sh('git -c user.name=radar-heal -c user.email=heal@localhost '
           'commit -q -m "self-heal: repair dark source(s)"')
        sh("git pull --rebase -X ours -q && git push -q")

    if fixed or failed:                                      # 4. report
        rows = "".join(f"<li>{x}</li>" for x in fixed + failed)
        notify(f"🔧 Radar self-heal — {len(fixed)} fixed, {len(failed)} still broken",
               f"<p>Dark sources were detected and acted on automatically.</p><ul>{rows}</ul>"
               f"<p>Recovered on re-probe: {', '.join(healed) or 'none'}.</p>")
    print(f"heal done: recovered={len(healed)} fixed={len(fixed)} failed={len(failed)}")


if __name__ == "__main__":
    main()
