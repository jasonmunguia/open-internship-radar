"""Actions-minutes budget: the poll must stay a 1-minute run, and the heartbeat must warn
before the plan's included minutes run out (when they do, GitHub stops every workflow,
the watcher included, so nothing else would report it).
"""
import json, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from radar import fetchers, heartbeat  # noqa: E402


def run(start, secs, status="completed"):
    t0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end = datetime.fromtimestamp(t0.timestamp() + secs, timezone.utc)
    return {"status": status, "run_started_at": t0.isoformat().replace("+00:00", "Z"),
            "updated_at": end.isoformat().replace("+00:00", "Z")}


def test_each_run_bills_whole_minutes_rounded_up():
    runs = [run("2026-10-28T05:00:00", 9), run("2026-10-28T05:20:00", 59),
            run("2026-10-28T05:40:00", 61), run("2026-10-28T06:00:00", 30, status="in_progress")]
    assert heartbeat.billed_minutes(runs) == 1 + 1 + 2


def test_projection_scales_by_share_of_month_elapsed():
    halfway = datetime(2026, 11, 16, tzinfo=timezone.utc)      # November: 30 days
    assert heartbeat.project_month(1500, halfway) == 3000
    assert heartbeat.project_month(100, datetime(2026, 12, 31, 12, tzinfo=timezone.utc)) == 102


def _fake_api(runs, open_issues):
    def api(path, token):
        if "/actions/runs" in path:
            page = int(path.split("&page=")[1].split("&")[0])
            return {"workflow_runs": runs[(page - 1) * 100: page * 100]}
        return open_issues
    return api


def test_alarm_fires_once_when_the_month_projects_over_90_percent(monkeypatch):
    created = []
    monkeypatch.setattr(heartbeat, "create_issue", lambda *a: created.append(a))
    now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
    hot = [run("2026-11-01T00:07:00", 70)] * 650                 # 2 billed min each
    monkeypatch.setattr(heartbeat, "_api", _fake_api(hot, []))
    used, projected = heartbeat.minutes_check("o/r", "t", 3000, now)
    assert used == 1300 and projected > 2700 and len(created) == 1
    assert created[0][4] == ["health", "minutes"]

    monkeypatch.setattr(heartbeat, "_api", _fake_api(hot, [{"number": 1}]))
    heartbeat.minutes_check("o/r", "t", 3000, now)
    assert len(created) == 1                                      # open issue = already warned


def test_alarm_stays_silent_at_the_planned_pace(monkeypatch):
    created = []
    monkeypatch.setattr(heartbeat, "create_issue", lambda *a: created.append(a))
    now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
    pace = [run("2026-11-01T00:07:00", 45)] * (72 * 9 + 24)      # 20-min polls, 1 min each
    monkeypatch.setattr(heartbeat, "_api", _fake_api(pace, []))
    used, projected = heartbeat.minutes_check("o/r", "t", 3000, now)
    assert used == 72 * 9 + 24 and 2000 < projected < 2700 and created == []


def test_speedrun_pages_keep_order_and_stop_at_the_first_gap(monkeypatch):
    def fake_get(url):
        page = int(url.rsplit("page=", 1)[1])
        if page == 4:
            raise OSError("timeout")
        return json.dumps({"total_pages": 99, "jobs": [{"title": f"p{page}-{i}", "url": f"u{page}{i}"}
                                                        for i in range(2)]})
    monkeypatch.setattr(fetchers, "_get", fake_get)
    titles = [j["title"] for j in fetchers.fetch_speedrun(pages=6)]
    assert titles == ["p1-0", "p1-1", "p2-0", "p2-1", "p3-0", "p3-1"]


def test_speedrun_never_asks_past_the_last_page(monkeypatch):
    asked = []
    def fake_get(url):
        asked.append(int(url.rsplit("page=", 1)[1]))
        return json.dumps({"total_pages": 2, "jobs": [{"title": "t", "url": "u"}]})
    monkeypatch.setattr(fetchers, "_get", fake_get)
    assert len(fetchers.fetch_speedrun()) == 2 and sorted(asked) == [1, 2]
