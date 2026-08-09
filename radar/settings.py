"""Single source of person-specific settings.

Modules import from here instead of hardcoding a name, address, or repo, so forking the radar for
someone else means editing config/person.yaml — not hunting through code. Falls back to safe
defaults when the file is absent, so a fresh clone never crashes.
"""
import os

try:
    import yaml
except ImportError:      # never let a missing dep take down the watchdog
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(ROOT, "config", "person.yaml")

_DEFAULTS = {
    "identity": {"name": "the candidate", "github_handle": "", "repo": "",
                 "contact_email": "radar@example.com"},
    "delivery": {"to": "", "send_as": "personal", "work_domains": [], "relay_base": ""},
}


def _load():
    cfg = {k: dict(v) for k, v in _DEFAULTS.items()}
    if yaml is None:
        return cfg
    try:
        with open(_PATH) as fh:
            loaded = yaml.safe_load(fh) or {}
        for section, values in loaded.items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
    except FileNotFoundError:
        pass
    return cfg


PERSON = _load()

NAME = PERSON["identity"]["name"]
HANDLE = PERSON["identity"]["github_handle"]
REPO = PERSON["identity"]["repo"]
CONTACT_EMAIL = PERSON["identity"]["contact_email"]

TO_ADDR = PERSON["delivery"]["to"]
SEND_AS = PERSON["delivery"]["send_as"]
WORK_DOMAINS = tuple(PERSON["delivery"]["work_domains"] or ())

USER_AGENT = f"internship-radar ({CONTACT_EMAIL})"
MENTION = f"@{HANDLE}" if HANDLE else ""

RELAY_BASE = PERSON["delivery"].get("relay_base", "") or os.environ.get("RADAR_RELAY_BASE", "")
