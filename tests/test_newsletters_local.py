"""Job newsletters load on the Mac's daily scrape (Substack 403s GitHub's runners), queue once,
and skip the backlog from the months the cloud fetch was blocked."""
import io, json, os, sys
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import radar.fetchers  # noqa: E402
from radar.local_scrape import queue_newsletters  # noqa: E402

NOW = datetime(2026, 10, 28, 14, tzinfo=timezone.utc)


def item(title, days_old):
    return {"company": "next play", "title": title, "location": "", "url": f"https://x/{title}",
            "department": "", "type": "newsletter", "source": "substack:nextplayso",
            "posted_at": format_datetime(NOW - timedelta(days=days_old)) if days_old is not None else ""}


def test_fresh_issues_queue_once_and_the_backlog_is_only_marked_seen(monkeypatch):
    feed = [item("this-week", 2), item("undated", None), item("june", 120)]
    monkeypatch.setattr(radar.fetchers, "fetch_substack", lambda name, sub: feed)
    seen, q = {}, io.StringIO()
    nl = [{"name": "next play", "sub": "nextplayso"}]

    assert queue_newsletters(nl, seen, q, now=NOW.timestamp()) == 2
    rows = [json.loads(line) for line in q.getvalue().splitlines()]
    assert [r["title"] for r in rows] == ["this-week", "undated"]
    assert all(r["cluster"] == "newsletter" and r["score"] == 0 for r in rows)
    assert len(seen) == 3                                   # the old issue is seen, not queued

    assert queue_newsletters(nl, seen, q, now=NOW.timestamp()) == 0   # next day: no repeats


def test_one_blocked_feed_does_not_stop_the_others(monkeypatch):
    def fetch(name, sub):
        if sub == "blocked":
            raise OSError("HTTP Error 403: Forbidden")
        return [item("ok", 1)]
    monkeypatch.setattr(radar.fetchers, "fetch_substack", fetch)
    n = queue_newsletters([{"name": "a", "sub": "blocked"}, {"name": "b", "sub": "fine"}],
                          {}, io.StringIO(), now=NOW.timestamp())
    assert n == 1
