#!/bin/bash
# install.sh — resolve every dependency in DEPENDENCIES.md that can be resolved
# automatically, verify the rest, and say plainly what happened. Idempotent: run it
# twice, the second run changes nothing and still exits 0.
#
# What it does NOT do: store your email password (interactive: tools/mailer.py add),
# install the Claude CLI (needs your login), create launchd jobs (SETUP.md — they
# hardcode paths you should read first), or touch any config.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OK=0; WARN=0

say()  { printf '%s\n' "$*"; }
good() { say "  [ok]   $*"; OK=$((OK+1)); }
warn() { say "  [MISS] $*"; WARN=$((WARN+1)); }

say "== internship-radar install =="

# 1. Python + requirements
if command -v python3 >/dev/null; then
  good "python3 $(python3 -V 2>&1 | cut -d' ' -f2)"
  python3 -m pip install -q -r "$HERE/requirements.txt" && good "requirements.txt installed"
else
  warn "python3 not found — install from python.org, then re-run"
fi

# 2. Scrapling (anti-bot fetching; tiering + local scrape die without it)
if python3 -c "import scrapling" 2>/dev/null; then
  good "scrapling importable"
else
  say "  installing scrapling (+ browser binaries — one-time, ~a minute)..."
  python3 -m pip install -q scrapling && python3 -m scrapling install >/dev/null 2>&1 \
    && good "scrapling installed" || warn "scrapling install failed — run: pip3 install scrapling && scrapling install"
fi

# 3. SSL certs (every HTTPS call fails without this in a bare shell)
CERT=$(python3 -c "import certifi; print(certifi.where())" 2>/dev/null || true)
if [ -n "$CERT" ] && [ -f "$CERT" ]; then
  good "certifi bundle at $CERT (launchd plists must set SSL_CERT_FILE to this)"
else
  python3 -m pip install -q certifi && good "certifi installed" || warn "certifi missing"
fi

# 4. Claude CLI (the five LLM joints; digest DEFERS without it, by design)
if command -v claude >/dev/null || [ -x "$HOME/.local/bin/claude" ]; then
  good "claude CLI present"
else
  warn "claude CLI not found — https://claude.com/claude-code (joints defer/skip until it exists)"
fi

# 5. gh CLI (self-heal issue closing; optional)
if command -v gh >/dev/null || [ -x "$HOME/.local/bin/gh" ]; then
  good "gh CLI present"
else
  warn "gh CLI not found (optional) — https://cli.github.com"
fi

# 6. mailer -> ~/.claude/tools/ (digest imports it from there)
mkdir -p "$HOME/.claude/tools"
if ! cmp -s "$HERE/tools/mailer.py" "$HOME/.claude/tools/mailer.py" 2>/dev/null; then
  cp "$HERE/tools/mailer.py" "$HOME/.claude/tools/mailer.py"
fi
good "mailer at ~/.claude/tools/mailer.py (store a password: python3 tools/mailer.py add personal you@gmail.com)"

# 7. Skills -> ~/.claude/skills/ (routing descriptions for agent sessions)
mkdir -p "$HOME/.claude/skills"
for s in "$HERE"/skills/*/; do
  name=$(basename "$s")
  if [ ! -d "$HOME/.claude/skills/$name" ]; then
    cp -R "$s" "$HOME/.claude/skills/$name" && good "skill installed: $name"
  else
    good "skill already present: $name (left untouched)"
  fi
done

# 8. Tests prove the spine imports and gates behave
if (cd "$HERE" && python3 -m pytest tests/ -q >/dev/null 2>&1); then
  good "pytest green"
else
  warn "pytest failed — run: python3 -m pytest tests/ -q"
fi
if (cd "$HERE" && python3 -m tests.test_location >/dev/null 2>&1); then
  good "location gate suite green"
else
  warn "location suite failed — run: python3 -m tests.test_location"
fi

say ""
say "== done: $OK ok, $WARN missing =="
say "Next: SETUP.md (config + launchd + Actions). Agents: read AGENT_ONBOARDING.md first."
exit 0
