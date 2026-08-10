"""THE REGISTRY OF LLM JOINTS — every place this system exercises model judgment.

"Deterministic spine, LLM at the joints" is the system's most important architectural
rule, and until 2026-08-09 it lived only as prose in TOOLS.md and METHODOLOGY.md. This
file IS the rule, encoded: every model call reads its config from here and goes through
run_joint(), and tests/test_joints.py fails the moment a CLI call appears that is not
registered. A new joint requires a deliberate entry in this dict — it cannot appear by
accident. (The registry earned its keep the day it was written: building it surfaced a
fifth joint, source_heal, that the original prose inventory had forgotten.)

Model selection rule, with its incident: MATCH THE MODEL TO THE JOB. Scoring rows
against a fixed profile is a small-model task; invoking a frontier model made it slower
than its own timeout, so every batch failed, every failure silently fell back to keyword
scores, and the feature had NEVER run across 1,313 rows while looking implemented.
Fixed schema + mechanical judgment -> small model. Open-ended research, disambiguation,
or writing -> larger model. ALWAYS set the model explicitly; never inherit a default.

Timeouts are a real parameter, not a constant: set them from observed batch time (~30x),
and cap rather than disable — an uncapped hang costs the whole day's run, because the
digest's sent-today guard blocks every hourly retry too.
"""
import os, shutil, subprocess

CLAUDE = os.path.expanduser("~/.local/bin/claude")
if not os.path.exists(CLAUDE):
    CLAUDE = shutil.which("claude") or "claude"

JOINTS = {
    "eligibility": {
        "model": os.environ.get("IR_ELIGIBILITY_MODEL", "sonnet"),
        "timeout": 1800, "batch": 10,
        "argv_extra": ["--output-format", "text"],
        "contract": "returns {eligible, why}; may ONLY remove the impossible; defaults "
                    "to eligible when unsure; never expresses preference",
    },
    "slug_resolve": {
        "model": "sonnet", "timeout": 900,
        "argv_extra": ["--permission-mode", "bypassPermissions"],
        "contract": "returns {company: slug}; every answer re-verified through the same "
                    "gates as a guessed slug; omission is correct, guessing is not",
    },
    "discovery": {
        "model": "sonnet", "timeout": 900,
        "argv_extra": ["--permission-mode", "bypassPermissions"],
        "contract": "returns postings actually seen; never constructs plausible URLs; "
                    "empty array is a valid answer",
    },
    "calendar": {
        "model": "sonnet", "timeout": 1800,
        "argv_extra": ["--permission-mode", "bypassPermissions"],
        "contract": "may revise dates with a cited evidence URL; may not invent "
                    "programs; malformed output is a no-op, never a partial write",
    },
    # Not in the original four-joint sketch — found while building this registry, which is the point.
    "source_heal": {
        "model": "sonnet", "timeout": 900,
        "argv_extra": ["--permission-mode", "acceptEdits"],
        "contract": "may edit ONLY the failed source's entry in sources.yaml (or remove "
                    "it and note the gap in README); must verify the fix returns jobs; "
                    "never commits",
    },
}


def run_joint(name, prompt, timeout=None, model=None, **run_kw):
    """The ONLY door to the CLI. Every model invocation in radar/ builds its argv here,
    so the registry above is the complete inventory of judgment in this system —
    tests/test_joints.py enforces that by counting call sites.

    Returns the CompletedProcess: callers parse stdout and judge output quality
    themselves, because degrading gracefully without REPORTING quality is how the
    eligibility filter died silently for days."""
    j = JOINTS[name]
    argv = [CLAUDE, "-p", prompt] + list(j.get("argv_extra", [])) + ["--model", model or j["model"]]
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout or j["timeout"], **run_kw)


def llm_available(timeout=45):
    """ACTUALLY invoke the CLI. An earlier version returned `shutil.which("claude") is
    not None` — true whenever the binary is on disk, i.e. always — so the digest's defer
    guard never fired once and degraded digests shipped for days. A capability check
    must exercise the capability, not assert its existence."""
    try:
        r = subprocess.run([CLAUDE, "-p", "Reply with exactly: OK"],
                           capture_output=True, text=True, timeout=timeout)
        return "OK" in (r.stdout or "")
    except Exception:
        return False
