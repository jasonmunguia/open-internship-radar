"""The JOINTS registry is enforced, not advisory.

"Deterministic spine, LLM at the joints" used to exist only as prose. This test makes it
structural: every model invocation in radar/ must (a) go through joints.run_joint and
(b) name a registered joint. A sixth model call added anywhere else fails CI — a new
joint now requires a deliberate registry entry, which is the entire point.

Run locally:  python3 -m tests.test_joints
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar.joints import JOINTS  # noqa: E402

RADAR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "radar")

# A direct CLI invocation looks like subprocess.run([CLAUDE, ...]) or
# subprocess.run(["claude", ...]) or a variable holding the binary path. Only joints.py
# (the single runner + the capability probe) is allowed to contain one.
_DIRECT_CLI = re.compile(r"subprocess\.run\(\s*\[\s*(?:CLAUDE|claude|[\"']claude[\"'])")


def _sources():
    for fn in sorted(os.listdir(RADAR)):
        if fn.endswith(".py"):
            with open(os.path.join(RADAR, fn)) as fh:
                yield fn, fh.read()


def test_no_cli_call_outside_the_registry():
    offenders = [fn for fn, src in _sources() if fn != "joints.py" and _DIRECT_CLI.search(src)]
    assert not offenders, (
        f"direct claude CLI invocation outside radar/joints.py in: {offenders}. "
        f"Model calls must go through joints.run_joint() with a registry entry.")


def test_every_joint_has_exactly_one_call_site():
    used = []
    for fn, src in _sources():
        if fn == "joints.py":
            continue
        used += re.findall(r"run_joint\(\s*[\"']([a-z_]+)[\"']", src)
    assert sorted(set(used)) == sorted(JOINTS), (
        f"registry/call-site mismatch: registered={sorted(JOINTS)} used={sorted(set(used))}. "
        f"Either a joint lost its caller (dead registry entry) or a call names an "
        f"unregistered joint.")
    assert len(used) == len(JOINTS), (
        f"expected one call site per joint ({len(JOINTS)}), found {len(used)}: {used}. "
        f"A second caller of the same joint deserves its own registry entry and contract.")


def test_registry_entries_are_complete():
    for name, j in JOINTS.items():
        assert j.get("model"), f"joint {name!r} has no explicit model — never inherit a default"
        assert isinstance(j.get("timeout"), int) and j["timeout"] > 0, \
            f"joint {name!r} has no timeout cap — an uncapped hang costs the whole day's run"
        assert j.get("contract"), f"joint {name!r} has no contract line"


if __name__ == "__main__":
    test_no_cli_call_outside_the_registry()
    test_every_joint_has_exactly_one_call_site()
    test_registry_entries_are_complete()
    print(f"joints registry OK: {len(JOINTS)} joints, all registered, all confined")
