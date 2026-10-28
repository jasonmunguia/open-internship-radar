"""seen.json merges as a key union, through a REAL git rebase (the path the poll takes).

The race: the Mac pushes seen.json while a cloud poll is running; the poll's rebase
conflicted on the one-line file, the push failed, and that run's alert keys were lost,
so the next poll re-sent its Apply-Now emails.
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from radar.merge_seen import merge  # noqa: E402

DRIVER = f'{sys.executable} -m radar.merge_seen %O %A %B'


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": ROOT, "GIT_AUTHOR_NAME": "t",
                               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"})


def write_seen(d, data):
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    json.dump(data, open(os.path.join(d, "data", "seen.json"), "w"))


def test_merge_is_a_union_keeping_later_timestamps():
    assert merge({"a": 1, "b": 5, "page:x": "h1"}, {"b": 3, "c": 2, "page:x": "h2"}) == \
        {"a": 1, "b": 5, "c": 2, "page:x": "h2"}


def test_concurrent_writers_rebase_without_losing_keys(tmp_path):
    origin, cloud, mac = (str(tmp_path / n) for n in ("origin", "cloud", "mac"))
    git(str(tmp_path), "init", "-q", "--bare", "-b", "main", origin)
    git(str(tmp_path), "clone", "-q", origin, mac)
    open(os.path.join(mac, ".gitattributes"), "w").write("data/seen.json merge=seen\n")
    write_seen(mac, {"old": 1})
    git(mac, "add", "-A"); git(mac, "commit", "-qm", "seed"); git(mac, "push", "-q", "origin", "HEAD:main")
    git(str(tmp_path), "clone", "-q", origin, cloud)
    for d in (cloud, mac):
        git(d, "config", "merge.seen.driver", DRIVER)

    write_seen(mac, {"old": 1, "mac-key": 2})                          # Mac pushes first
    git(mac, "commit", "-qam", "mac"); git(mac, "push", "-q", "origin", "HEAD:main")
    write_seen(cloud, {"old": 1, "alert:req:wd:jr115941": 3})          # poll alerted meanwhile
    git(cloud, "commit", "-qam", "poll")
    git(cloud, "pull", "-q", "--rebase")                               # the poll.yml step
    git(cloud, "push", "-q", "origin", "HEAD:main")

    merged = json.load(open(os.path.join(cloud, "data", "seen.json")))
    assert merged == {"old": 1, "mac-key": 2, "alert:req:wd:jr115941": 3}
