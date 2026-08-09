"""Wayback snapshots — so a pulled req is still readable when the operator gets to it.

The apply queue deliberately keeps rows until tapped, which means a row can outlive its
posting. Without a snapshot the link 404s and the role is simply lost. Fire-and-forget:
archiving must never slow or break the poll.
"""
import urllib.request

UA = {"User-Agent": "internship-radar (archival snapshot)"}


def snapshot(url, timeout=8):
    """Ask the Wayback Machine to capture a URL. Returns True on acceptance. Free, no key."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        req = urllib.request.Request(f"https://web.archive.org/save/{url}", headers=UA)
        return urllib.request.urlopen(req, timeout=timeout).status < 400
    except Exception:
        return False            # archival is a nicety; never let it break the pipeline


def archived_url(url):
    """Stable read-back URL for the most recent snapshot."""
    return f"https://web.archive.org/web/2/{url}" if url else ""
