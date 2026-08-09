"""LOCAL-only fetchers using Scrapling (stealth browser) for bot-walled but PUBLIC
(no-login) career pages the cloud poller's plain HTTP can't reach. Runs on the operator's Mac.
Confirmed working: Apple. Best-effort: Google, Meta. (Tesla stays 403 even via stealth.)
Never used to defeat login/auth walls — public listings only."""
import re

def _stealth(url):
    from scrapling.fetchers import StealthyFetcher
    return StealthyFetcher.fetch(url, headless=True, network_idle=True)

def fetch_apple():
    p = _stealth("https://jobs.apple.com/en-us/search?search=intern&sort=relevance")
    if p.status != 200:
        return []
    out, seen = [], set()
    for a in p.css('a[href*="/details/"]'):
        title = (a.text or "").strip()
        href = a.attrib.get("href", "")
        if not title or title.lower().startswith("see full role") or href in seen:
            continue
        seen.add(href)
        out.append({"company": "Apple", "title": title,
                    "location": "", "url": "https://jobs.apple.com" + href,
                    "department": "", "posted_at": "", "source": "scrapling:apple"})
    return out

def fetch_google():
    try:
        p = _stealth("https://www.google.com/about/careers/applications/jobs/results/?q=intern&target_level=INTERN_AND_APPRENTICE")
        if p.status != 200:
            return []
        out, seen = [], set()
        for a in p.css('a[href*="/jobs/results/"]'):
            title = (a.text or "").strip()
            href = a.attrib.get("href", "")
            if not title or len(title) < 6 or href in seen:
                continue
            seen.add(href)
            url = href if href.startswith("http") else "https://www.google.com/about/careers/applications" + href
            out.append({"company": "Google", "title": title, "location": "", "url": url,
                        "department": "", "posted_at": "", "source": "scrapling:google"})
        return out
    except Exception:
        return []

def fetch_meta():
    try:
        p = _stealth("https://www.metacareers.com/jobs?q=intern")
        if p.status != 200:
            return []
        out, seen = [], set()
        for a in p.css('a[href*="/jobs/"]'):
            title = (a.text or "").strip()
            href = a.attrib.get("href", "")
            if not title or len(title) < 6 or href in seen:
                continue
            seen.add(href)
            url = href if href.startswith("http") else "https://www.metacareers.com" + href
            out.append({"company": "Meta", "title": title, "location": "", "url": url,
                        "department": "", "posted_at": "", "source": "scrapling:meta"})
        return out
    except Exception:
        return []

def fetch_all_scrapling():
    out, errors = [], []
    for name, fn in [("apple", fetch_apple), ("google", fetch_google), ("meta", fetch_meta)]:
        try:
            out.extend(fn())
        except Exception as ex:
            errors.append(f"{name}: {ex}")
    return out, errors
