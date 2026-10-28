"""git merge driver for data/seen.json — `python3 -m radar.merge_seen %O %A %B`.

seen.json is one line of JSON written by two machines: the cloud poll (every 30 min)
and the Mac's local scrape. Any overlap made `git pull --rebase` conflict on the whole
file, the push failed, and the alert keys that run had just recorded were lost — so the
next poll re-sent those Apply-Now emails (the "seen.json push race"). The file is a set
of keys, so the correct merge is the union: a key either side has seen stays seen.

Wired by `.gitattributes` (data/seen.json merge=seen) plus `git config merge.seen.driver`
in every writer: poll.yml, radar/local_scrape.py. Unconfigured, git silently falls back
to a text merge, which is the old conflict — so each writer configures it before pulling.
"""
import json, sys


def merge(a, b):
    """Union of keys. Timestamps keep the later value (pruning keys off it stays correct);
    page-watch hashes keep `b`, the side being replayed, which is the newer write."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, int) and isinstance(out.get(k), int):
            out[k] = max(out[k], v)
        else:
            out[k] = v
    return out


def main(argv):
    _, ours, theirs = argv[1:4]
    try:
        a, b = json.load(open(ours)), json.load(open(theirs))
    except (OSError, ValueError):
        return 1          # unreadable side: leave the conflict for a human, never guess
    json.dump(merge(a, b), open(ours, "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
