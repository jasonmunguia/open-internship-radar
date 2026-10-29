"""A careers scraper that fails must say so (2026-10-28): Meta and Google returned 0 rows
for weeks with only a log line, and a Meta intern the operator applied to never reached the radar.

Run locally:  python3 -m pytest tests/test_scraper_alarm.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.local_scrape import scraper_alarms  # noqa: E402

OK = [{"source": "scrapling:apple"}, {"source": "scrapling:google"}, {"source": "scrapling:meta"}]
NO_META = OK[:2]


def test_one_bad_morning_is_quiet_the_second_emails():
    h = {}
    assert scraper_alarms(NO_META, [], h, "2026-10-29") == []
    alarms = scraper_alarms(NO_META, [], h, "2026-10-30")
    assert [(n, s) for n, s, _ in alarms] == [("meta", 2)] and "0 rows" in alarms[0][2]


def test_raised_error_counts_and_carries_its_reason():
    h = {}
    scraper_alarms(OK[1:], ["apple: RuntimeError: HTTP 403"], h, "2026-10-29")
    alarms = scraper_alarms(OK[1:], ["apple: RuntimeError: HTTP 403"], h, "2026-10-30")
    assert alarms[0][0] == "apple" and "403" in alarms[0][2]


def test_same_day_rerun_is_not_a_new_morning():
    h = {}
    scraper_alarms(NO_META, [], h, "2026-10-29")
    assert scraper_alarms(NO_META, [], h, "2026-10-29") == []
    assert h["meta"]["streak"] == 1


def test_recovery_resets_and_reminders_are_weekly():
    h = {}
    days = [f"2026-11-{d:02d}" for d in range(1, 12)]
    fired = [d for d in days if scraper_alarms(NO_META, [], h, d)]
    assert fired == ["2026-11-02", "2026-11-09"]          # 2nd morning, then a week later
    scraper_alarms(OK, [], h, "2026-11-12")
    assert h["meta"]["streak"] == 0
