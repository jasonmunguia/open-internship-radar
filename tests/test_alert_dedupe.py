"""Instant alerts dedupe by requisition id first, company+title only as a fallback.

2026-10-25: Microsoft's Cambridge "Product Manager Intern" (posted 10-23) never alerted
because a different Microsoft req with the same title alerted on 08-04.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import poll  # noqa: E402
from radar import queue_state as qs  # noqa: E402

AUG = 1786000000
OCT = AUG + 80 * 86400
REMOTE = {"company": "Microsoft", "title": "Product Manager Intern",
          "url": "https://apply.careers.microsoft.com/careers/job/1970393556953113"}
CAMBRIDGE = {"company": "Microsoft", "title": "Product Manager Intern",
             "url": "https://apply.careers.microsoft.com/careers/job/1970393557044772"}
JOBRIGHT = {"company": "Microsoft", "title": "Product Manager Intern",
            "url": "https://jobright.ai/jobs/info/abc"}


def test_new_req_same_title_alerts():
    seen = {}
    poll.mark_alerted(REMOTE, seen, AUG)
    assert poll.alert_suppressed(REMOTE, seen)
    assert not poll.alert_suppressed(CAMBRIDGE, seen)

def test_board_copy_without_req_id_still_collapses():
    seen = {}
    poll.mark_alerted(CAMBRIDGE, seen, OCT)
    assert poll.alert_suppressed(JOBRIGHT, seen)

def test_seed_backfills_only_rows_ingested_at_alert_time():
    seen = {"alert:microsoft|product manager intern": AUG}
    rows = [{**REMOTE, "ts": AUG + 600}, {**CAMBRIDGE, "ts": OCT}]
    poll.seed_req_alert_keys(seen, rows)
    assert poll.alert_suppressed(REMOTE, seen)        # the role that alerted in August
    assert not poll.alert_suppressed(CAMBRIDGE, seen)  # the October req is new

def test_apple_req_id_shared_across_locations():
    a = qs.req_id("https://jobs.apple.com/en-us/details/200673612-0157/applied-data-solutions")
    b = qs.req_id("https://jobs.apple.com/en-us/details/200673612/applied-data-solutions")
    assert a == b == "apple:200673612"

def test_req_posted_before_title_alert_is_not_new():
    seen = {}
    poll.mark_alerted(JOBRIGHT, seen, AUG)       # title alerted from a board copy
    old = {**CAMBRIDGE, "posted_at": "2026-08-01"}
    new = {**CAMBRIDGE, "posted_at": "2026-10-23"}
    assert poll.alert_suppressed(old, seen)
    assert not poll.alert_suppressed(new, seen)
