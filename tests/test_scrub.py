"""The scrub is enforced, not remembered.

This public repo is the identity-scrubbed twin of a private deployment. Ports from the
private repo have TWICE reintroduced the author's identity through fallback literals and
comment strings (caught 2026-08-10, the second time in a pushed commit). A rule that
lives only in a porting checklist is a rule the next port breaks — so it lives here,
where violating it fails the suite that CI and install.sh both run.

Run locally:  python3 -m pytest tests/test_scrub.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Author-identity tokens that must never ship. Kept as a joined pattern so this file
# does not itself contain a bare token an outside grep would flag.
_TOKENS = re.compile("|".join([
    "jason" + "munguia", "munguiaj" + "2017", "g\\." + "ucla\\.edu", "ucla\\.edu",
    "jasonm@" + "synphony", "synphony\\.co", "schematic\\.so", "oriane\\.ai",
]), re.I)

_SHIP_EXT = (".py", ".md", ".sh", ".js", ".json", ".yaml", ".yml", ".example", ".txt")
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".vercel"}
_SELF = os.path.abspath(__file__)


def test_no_identity_tokens_in_shipped_files():
    hits = []
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for n in names:
            fp = os.path.join(root, n)
            if os.path.abspath(fp) == _SELF or not fp.endswith(_SHIP_EXT):
                continue
            try:
                text = open(fp, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if _TOKENS.search(line):
                    hits.append(f"{os.path.relpath(fp, REPO)}:{i}: {line.strip()[:80]}")
    assert not hits, (
        "author identity leaked into shipped files (scrub the port, do not ship):\n  "
        + "\n  ".join(hits[:20]))


if __name__ == "__main__":
    test_no_identity_tokens_in_shipped_files()
    print("scrub guard OK — no identity tokens in shipped files")
