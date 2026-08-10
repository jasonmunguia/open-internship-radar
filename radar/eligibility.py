"""Eligibility filter — removes roles that are IMPOSSIBLE to apply to, using local
Claude Code (headless, no API key). Runs in the LOCAL digest only (not the cloud poller).

This is a FILTER, not a ranker. It may only remove hard barriers (wrong degree level,
non-US, full-time/new-grad titles); it never expresses preference. Which roles are worth
showing is decided upstream by role family + company tier. It was previously named
`rerank`, and that name hid a real bug: nobody asked what a "reranker" ranked ON while it
silently graded resume-fit and deleted qualifying jobs. Renamed 2026-08-09."""
import json, os

from radar.joints import JOINTS, run_joint

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _eligibility_facts():
    """The operator's hard facts, read from config/profile.yaml (eligibility_facts) at
    call time — NEVER hardcoded here. radar/*.py must not carry a name, class year, or
    preference (the ARCHITECTURE.md boundary); a 2026-08-10 cold audit caught this
    module violating that with a baked-in "class of 2028" block. A missing config block
    raises loudly: judging with unknown facts is worse than not judging, and the raise
    flows into the batch-failure counter, so the digest DEFERS instead of sending."""
    import yaml
    facts = (yaml.safe_load(open(os.path.join(_ROOT, "config", "profile.yaml")))
             or {}).get("eligibility_facts") or {}
    if not facts:
        raise RuntimeError("config/profile.yaml has no eligibility_facts block — the "
                           "eligibility joint refuses to judge with unknown facts. "
                           "See config/profile.example.yaml (open repo) or SETUP.md.")
    lines = "\n".join(f"- {v}" for v in facts.values())
    return (f"HARD ELIGIBILITY FACTS (the only thing you may judge):\n{lines}\n\n"
            "You are NOT judging interest, prestige, career value, or fit to a person. "
            "Whether this role is desirable has ALREADY been decided upstream by "
            "role-family matching and company tier. Your only job is to catch roles the "
            "keyword scorer wrongly let through because they are IMPOSSIBLE to apply to.")


def _prompt(batch):
    roles = [{"i": i, "company": r.get("company", ""), "title": r.get("title", ""),
              "location": r.get("location", ""), "dept": r.get("department", "")}
             for i, r in enumerate(batch)]
    return (f"{_eligibility_facts()}\n\n"
            f"For each role return:\n"
            f"  eligible: true/false — false ONLY for a hard, checkable barrier: wrong degree level,\n"
            f"    class-year restriction (freshman/sophomore-only), full-time/new-grad/senior title,\n"
            f"    non-US location, or a stated demographic/program restriction that excludes them.\n"
            f"    If you are unsure, eligible is TRUE. Ambiguity is not a barrier.\n"
            f"  why: <=20 words. If eligible, describe WHAT THE ROLE IS so they can triage at a glance.\n"
            f"    If ineligible, name the specific barrier. Never comment on how good the role is.\n\n"
            f"ROLES:\n{json.dumps(roles)}\n\n"
            f"Return ONLY a JSON array: [{{\"i\":<idx>,\"eligible\":<true|false>,\"why\":\"<=20 words\"}}]. No prose.")

_OK, _FAILED = {"n": 0}, {"n": 0}


# Model, timeout and batch size come from the JOINTS registry (radar/joints.py) — the one
# place that answers "where does this system use judgment, and how is each call set up".
# The incidents behind those numbers (a frontier model slower than its own 120s timeout ->
# 0 of 1,313 rows ever carried an AI reason; an uncapped hang eating the whole day's send
# because _sent_today() blocks every hourly retry) are documented there.
def filter_ineligible(items, band=(40, 82), batch_size=None, timeout=None):
    """Flag items in the score band that are impossible to apply to. Mutates & returns items.
    Degrades gracefully: on any failure the keyword score stands -- which is exactly why this
    failing silently went unnoticed for so long. Callers must check last_run_quality()."""
    batch_size = batch_size or JOINTS["eligibility"]["batch"]
    idx = [i for i, r in enumerate(items) if band[0] <= r.get("score", 0) <= band[1]]
    for s in range(0, len(idx), batch_size):
        chunk = idx[s:s + batch_size]
        batch = [items[i] for i in chunk]
        try:
            out = run_joint("eligibility", _prompt(batch), timeout=timeout)
            txt = out.stdout.strip()
            js = txt[txt.find("["):txt.rfind("]") + 1]
            for v in json.loads(js):
                r = batch[int(v["i"])]
                r["eligibility_note"] = v.get("why", "")
                # The model may only REMOVE the impossible. It may not re-rank by taste:
                # deciding which roles are worth showing is the deterministic scorer's job
                # (role family + company tier), settled upstream. An earlier version graded
                # "fit + interest + career value" against a personal profile and silently
                # deleted qualifying jobs from the email — the exact resume-fit inference the
                # scoring rewrite existed to remove, running one layer down where nobody saw it.
                if v.get("eligible") is False:
                    r["kw_score"] = r["score"]
                    r["score"] = 0
                    r["ineligible"] = True
        except Exception as ex:
            print(f"[eligibility] batch failed, keeping keyword scores: {ex}")
            _FAILED["n"] += 1
        else:
            _OK["n"] += 1
    return items


def last_run_quality():
    """(ok_batches, failed_batches). The caller MUST check this: a re-rank that silently kept
    keyword scores produced exactly the degraded output the defer logic exists to prevent."""
    return _OK["n"], _FAILED["n"]


def reset_quality():
    _OK["n"] = _FAILED["n"] = 0
