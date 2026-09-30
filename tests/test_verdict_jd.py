"""JD capture v2 (2026-09-30): the deterministic halves, transports monkeypatched.

Two bugs this guards. (1) Scrapling >=0.4 returns page.body as BYTES and the text
cleaner ran a str regex over it: TypeError, so every Scrapling fallback failed — 42 of
143 captures, never retried. (2) A careers site whose GET returns its menu before the
posting stored that menu as the "JD": long enough to pass a length test, zero role
content, and it was the whole 600-char excerpt the pattern joint saw.
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import verdict_jd as vj  # noqa: E402

MENU = ("Diversity & Inclusion Our Philosophy Teams Advertising Corporate Functions Design "
        "Engineering Global Operations Early Careers Blog Jobs Apply Company About Newsroom "
        "Contact Programs Resources Help center Safety Center Legal Privacy Policy ") * 3
JD = ("Product Manager Intern\nResponsibilities\nYou will own the roadmap for our ads "
      "integrity tools and work with engineering.\nMinimum Qualifications\nCurrently "
      "pursuing a bachelor's degree. Experience with SQL preferred. Strong skills in "
      "written communication. " * 2)


def test_visible_text_accepts_bytes_and_unescapes():
    html = b"<html><body><p>We&#x27;re hiring</p><script>x=1</script></body></html>"
    assert vj.visible_text(html) == "We're hiring"


def test_jd_text_starts_at_the_title():
    assert vj.jd_text(MENU + JD, "Product Manager Intern").startswith("Product Manager Intern")


def test_jd_text_handles_truncated_titles_and_headings():
    # boards truncate titles with "..."; the section heading is the fallback anchor
    assert vj.jd_text(MENU + "Job Description Come join", "Business Operations Mana...") \
        .startswith("Job Description")
    assert vj.jd_text("plain text", "") == "plain text"


def test_looks_like_jd():
    assert vj.looks_like_jd(JD)
    assert not vj.looks_like_jd(MENU)


def test_chrome_get_escalates_to_scrapling(monkeypatch):
    """GET returns only the menu -> render with Scrapling, whose body is BYTES."""
    monkeypatch.setattr("radar.fetchers._get", lambda url, timeout=20, retries=1:
                        f"<html><body>{MENU}</body></html>")
    page = types.SimpleNamespace(body=f"<html><body>{MENU}{JD}</body></html>".encode())
    monkeypatch.setitem(sys.modules, "radar.scrapling_fetch",
                        types.SimpleNamespace(_stealth=lambda url: page))
    text, how = vj._fetch_jd("https://example.com/job/1", "Product Manager Intern")
    assert how == "scrapling" and text.startswith("Product Manager Intern")


def test_rendered_chrome_is_recorded_empty(monkeypatch):
    monkeypatch.setattr("radar.fetchers._get", lambda url, timeout=20, retries=1: MENU)
    page = types.SimpleNamespace(body=MENU.encode())
    monkeypatch.setitem(sys.modules, "radar.scrapling_fetch",
                        types.SimpleNamespace(_stealth=lambda url: page))
    assert vj._fetch_jd("https://example.com/job/2", "Analyst") == ("", "error:NoJDText")


def test_capture_retries_v1_failures_once(monkeypatch, tmp_path):
    for name in ("FEEDBACK", "QUEUE", "OUT"):
        monkeypatch.setattr(vj, name, str(tmp_path / f"{name}.jsonl"))
    monkeypatch.setattr(vj, "ROOT", str(tmp_path))      # git calls fail harmlessly here
    verdicts = ["bytesbug", "menu", "good", "v2fail", "fresh"]
    with open(vj.FEEDBACK, "w") as fh:
        for jid in verdicts:
            fh.write(json.dumps({"job_id": jid, "action": "no", "ts": 1,
                                 "url": f"https://x.test/{jid}"}) + "\n")
    open(vj.QUEUE, "w").close()                          # every row has left the queue
    with open(vj.OUT, "w") as fh:
        for rec in ({"job_id": "bytesbug", "how": "error:TypeError", "jd": "",
                     "company": "GE Vernova", "title": "Ops Intern"},
                    {"job_id": "menu", "how": "get", "jd": MENU, "title": "PM Intern"},
                    {"job_id": "good", "how": "get", "jd": JD, "title": "Product Manager Intern"},
                    {"job_id": "v2fail", "how": "error:NoJDText", "jd": "", "v": 2}):
            fh.write(json.dumps(rec) + "\n")
    fetched = []
    monkeypatch.setattr(vj, "_fetch_jd", lambda url, title="": fetched.append(url) or (JD, "get"))
    res = vj.capture(limit=10)
    assert sorted(u.rsplit("/", 1)[1] for u in fetched) == ["bytesbug", "fresh", "menu"]
    assert res["new"] == 1 and res["retried"] == 2
    latest = {}
    for line in open(vj.OUT):
        r = json.loads(line)
        latest[r["job_id"]] = r
    # a retried row that left the queue keeps its tap-time identity
    assert latest["bytesbug"]["company"] == "GE Vernova" and latest["bytesbug"]["v"] == 2
    # second night: nothing left to retry
    fetched.clear()
    vj.capture(limit=10)
    assert fetched == []


def test_excerpts_drop_menus_and_trim(monkeypatch, tmp_path):
    monkeypatch.setattr(vj, "OUT", str(tmp_path / "out.jsonl"))
    with open(vj.OUT, "w") as fh:
        fh.write(json.dumps({"job_id": "a", "jd": MENU, "title": "PM Intern"}) + "\n")
        fh.write(json.dumps({"job_id": "b", "jd": MENU + JD,
                             "title": "Product Manager Intern"}) + "\n")
    ex = vj.excerpts()
    assert "a" not in ex and ex["b"].startswith("Product Manager Intern")
