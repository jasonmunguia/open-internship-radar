"""SEC Form D data changes daily, so the poll fetches it once a day: one request feeds both the
persistent funding history ($25M+) and the 14-day watchlist ($60M+). It used to run every poll,
13s of SEC requests per run, enough to push a poll past 60s and bill 2 minutes."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import radar.funding, radar.funding_history  # noqa: E402,E401
from radar import poll  # noqa: E402


def test_one_fetch_per_day_feeds_history_and_watchlist(tmp_path, monkeypatch):
    calls, ingested = [], []
    rows = [{"company": "Big Robotics Inc", "amount": 80_000_000, "industry": "Other Technology"},
            {"company": "Mid Software Corp", "amount": 30_000_000, "industry": "Other Technology"}]
    monkeypatch.setattr(radar.funding, "recent_big_form_ds", lambda **kw: calls.append(kw) or rows)
    monkeypatch.setattr(radar.funding_history, "ingest", lambda r: ingested.append(r))
    monkeypatch.setattr(poll, "FUNDED", str(tmp_path / "funded_watch.json"))

    data = poll.refresh_funded()
    poll.refresh_funded()                                     # second poll the same day

    assert calls == [{"days": 2, "min_amount": 25_000_000}]   # one SEC fetch per day
    assert ingested == [rows]                                 # history gets every $25M+ row
    assert "big robotics" in data and "mid software" not in data
    assert json.load(open(poll.FUNDED))["_last_run"]
