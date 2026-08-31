# LEARNINGS — incidents and the doctrine they minted

Read this after CLAUDE.md. Each entry is a real incident from a real run: what
happened, what it cost, and the rule that now exists because of it. If you are
about to re-learn one of these the expensive way, stop.

## 1. Uncommitted data in the production clone is already gone (2026-08-30)
The new verdict-JD stage captured 20 job descriptions at 2:40am; selfheal's
30-minute `reset --hard && clean -fd` stash-wiped the untracked file before the
nightly's end-of-run commit at 4:19. Separately, rows appended by hand to a
TRACKED file (feedback_replies.jsonl) were destroyed outright by the digest's
sync, which resets WITHOUT stashing. Recovery required digging `stash@{1}^3`.
**Rule: the writer commits and pushes its own output the moment it writes
(see verdict_jd.capture); any manual data edit lands at ORIGIN via commit,
never as a bare append in the production clone. This is the third time this
class of bug has cost a night's output (2026-08-10 discovery rows, 2026-08-10
nightly report, 2026-08-30 JDs). It is never transient; it is the architecture.**

## 2. Lid-closed Macs run launchd jobs in frozen slices — power state decides everything (2026-08-30)
On AC power a lid-closed Mac dark-wakes every 5–15 minutes; launchd starts jobs
on those wakes and the kernel freezes/thaws the SAME process across sleep
slices — a 17-minute digest ran 6:00→6:17 lid-closed and sent a byte-identical
email to a lid-open run. On battery, wakes drop to ~1/hour and the same job
smears across half the night. `caffeinate -i` does NOT survive lid close.
**Rule: quality is gate-guaranteed (clean pass or no send), so power state only
moves WHEN. Verify schedule claims against `pmset -g log` timestamps
cross-referenced with the job log's own timestamps — never against assumptions
about what "asleep" means.**

## 3. Numbers written in prose rot; only files are true (2026-08-30/31)
The docs disagreed with the code on the joint count three ways at once ("five"
in install.sh, "six" in four docs, seven in the registry), and source counts
drifted across ~150/~164/171 in the same README. A sweep "fixed" them and still
missed the launchd plist example because the sweep's glob was `.md`/`.py`.
**Rule: prose points at the source of truth (`config/sources.yaml`, `JOINTS`)
instead of restating it, and any count change greps EVERY committed extension —
including `.example`, `.plist`, `.sh` — before it claims done.**

## 4. Append-only files + parallel CI writers = dropped data, even with a concurrency queue (2026-08-29)
Three verdict taps in 30 seconds: each repository_dispatch run checks out the
SHA pinned at dispatch time, so the queued third run rebased a stale tail of
feedback.jsonl against a sibling's push, conflicted, and silently dropped a
tap. **Rule: append-only jsonl gets `merge=union` in .gitattributes, CI writers
check out `ref: main` (the live tip), and a dropped-write bug is found by
counting taps against rows — not by whether the workflow shows green.**

## 5. Audit categorizations by re-sampling reality, not by re-reading labels (2026-08-30)
Two self-audits both corrected the system's own story: 5 of 30 sampled "dead"
postings read live on a fresh probe (jobright extends validThrough after the
verdict), and all 33 "below score floor" rows turned out to be role-family
mismatches — the label in the report was simply wrong. **Rule: any bucket you
summarize for the operator gets a sample re-verified against the live source
first; the operator then RULES on the trade-off (here: dead-is-permanent was
reviewed and deliberately kept, 2026-08-30 — do not re-propose it from the same
evidence).**

## 6. An email that looks corrupted in an API is perfect on the wire (2026-08-31)
A mail API's decoded htmlBody showed mangled button URLs (`?jT70bb...`); panic
was one commit away. The RAW MIME showed textbook quoted-printable
(`?j=3D5470bb7d91f4`) that every real client decodes correctly — the reading
tool's decoder was the bug. **Rule: before declaring a send-path bug, pull the
RAW message and decode it yourself. Judge the wire, not a viewer.**

## 7. Anti-bot pages hide their data in predictable places (2026-08-29)
apmlist.org has no API, but its full dataset rides the Next.js RSC flight
payload in the homepage HTML, and its status enum (`OPEN:1,SOON:2,NOT_YET:3,
CLOSED:4`) sat readable in a JS chunk. Flock Safety's board was invisible on
/careers but exposed on the rendered /careers/positions route, behind a
URL-encoded-space Ashby token. A member-gated page yielded 12x more text
through an authenticated browser session than anonymous render. **Rule: before
calling a source unreachable — read the flight payload, render the deeper
route, mine the JS for enums, and try the operator's own logged-in session.
Parse failures must RAISE (0 records = format changed), never return a quiet
empty list.**

## 8. Click-tracker URLs poison downstream gates (2026-08-29)
Simplify click links match the liveness gate's job-path regex while their
redirect targets sometimes don't — rows kept on tracker URLs would be falsely
judged "pulled req". **Rule: resolve tracking redirects to the real ATS URL at
fetch time (geturl() needs no body read), strip utm params, and keep the
tracker URL only as the fallback when resolution fails.**

## 9. The 40-row LLM re-vet cap is display polish, not the safety gate (2026-08-30)
"Only 40 rows got the model this morning" looked like 95 rows shipped unvetted.
They didn't: every row is joint-vetted the morning it first enters (the rescue
pass is uncapped over new rows and gate-enforced); the display pass only
refreshes reasoning text on the visible top-40. **Rule: know which pass is the
gate and which is cosmetic before "fixing" either; notes are not persisted, so
a blank Why column means vetted-earlier, not never-vetted.**

## 10. Verify the deployed surface, not the push (standing, re-proven all sprint)
The Vercel relay deploys only via `vercel --prod` (the project is not
GitHub-linked); production runs `~/.internship-radar`, which moves only on
pull/reset; the public twin moves only through sync_public.py. Every change
this sprint landed three places and was then CURL'd / log-read / re-run on the
deployed copy. **Rule: a claim of "live" names the surface it was verified on
and the command that proved it. A green push proves nothing about any of the
three surfaces.**
