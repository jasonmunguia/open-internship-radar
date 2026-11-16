"""Watch-page hashing: site chrome must not fire [watch] alerts (2026-11-15).

nasa.gov served a rotating news feed inside its menu; hashing the whole page fired
30-48 false alerts a day per NASA page. Only <main> is program content.
"""
import hashlib

from radar import fetchers
from radar.fetchers import WATCH_V, watch_changed, watch_page, watch_text

PAGE = ("<html><header><nav>News: ESCAPADE flyby article {age} ago</nav></header>"
        "<main><h1>Pathways</h1><p>{body}</p></main><footer>x</footer></html>")


def _hash(monkeypatch, html):
    monkeypatch.setattr(fetchers, "_get", lambda url: html)
    return watch_page("n", "https://example.gov/")


def test_menu_news_rotation_does_not_change_hash(monkeypatch):
    a = _hash(monkeypatch, PAGE.format(age="3 days", body="Applications closed."))
    b = _hash(monkeypatch, PAGE.format(age="4 days", body="Applications closed."))
    assert a == b and not watch_changed(a, b)


def test_main_content_change_alerts(monkeypatch):
    a = _hash(monkeypatch, PAGE.format(age="3 days", body="Applications closed."))
    b = _hash(monkeypatch, PAGE.format(age="3 days", body="Apply Feb 9-13."))
    assert watch_changed(a, b)


def test_page_without_main_hashes_whole_text():
    assert watch_text("<div>Hello <b>there</b></div>") == "Hello there"


def test_old_unversioned_hash_rebaselines_silently(monkeypatch):
    legacy = hashlib.sha1(b"whole page").hexdigest()
    new = _hash(monkeypatch, PAGE.format(age="3 days", body="x"))
    assert new.startswith(WATCH_V)
    assert not watch_changed(legacy, new)
    assert not watch_changed(None, new)
