// Click relay: every job link in every email points here, not at the posting.
//
//   /api/a?j=<job_id>&u=<encoded url>&k=<applied|networked>
//
// It records the tap, then 302s to the real posting. the operator notices nothing; the queue
// learns. Writes go through GitHub repository_dispatch rather than a direct contents
// commit so concurrent taps serialise inside Actions instead of racing on a file SHA.
//
// Never blocks the redirect: if logging fails, the user still lands on the posting. A
// dropped log line costs one duplicate row tomorrow; a broken redirect costs the application.

export default async function handler(req, res) {
  const { j = "", u = "", k = "applied" } = req.query || {};
  const target = safeUrl(u);
  // "undo" must be whitelisted or the Undo link below LOGS ANOTHER APPLY — shipped
  // that way until a 2026-08-10 cold audit traced k=undo into the coercion.
  // queue_state.py has handled "undo" all along.
  // "yes"/"no" are verdict taps (👍/👎 per row) — routed to feedback.jsonl by the
  // Action, never to applied.jsonl: a verdict must not clear a row as if applied.
  const action = ["applied", "networked", "undo", "yes", "no"].includes(k) ? k : "applied";

  try {
    await fetch(`https://api.github.com/repos/${process.env.GH_REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        event_type: "radar-click",
        client_payload: { job_id: String(j).slice(0, 200), action, ts: Date.now(), url: target || "" },
      }),
    });
  } catch (_) { /* logging is best-effort — the redirect is not */ }

  if (!target) {
    // "networked" links have nowhere to go; confirm inline with an undo path.
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    return res.status(200).send(page(j, action));
  }
  res.setHeader("Cache-Control", "no-store");   // a re-tap must re-log, not hit a CDN copy
  return res.redirect(302, target);
}

function safeUrl(u) {
  try {
    const d = decodeURIComponent(u || "");
    const p = new URL(d);
    return ["http:", "https:"].includes(p.protocol) ? d : null;  // no javascript:/data: redirects
  } catch { return null; }
}

function page(j, action) {
  // Verdict taps get their own copy + a flip link (last verdict wins downstream),
  // NOT the undo link — k=undo would write an apply-undo for a row never applied to.
  if (action === "yes" || action === "no") {
    const yes = action === "yes";
    const flip = yes ? "no" : "yes";
    // Auto-close so a verdict tap costs zero attention (2026-08-29 per the operator: the
    // confirmation tab was the slowest part of filtering). The dispatch above is awaited
    // BEFORE this page is sent, so the tap is already recorded — the tab closes the moment
    // the script parses — zero timer. window.close() works on a fresh tab with no history (desktop
    // Gmail, the operator's whole flow); mobile in-app browsers ignore it, so the copy stays.
    // To flip a verdict, tap the other button in the email (last verdict wins).
    return `<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font:16px -apple-system,sans-serif;padding:44px;max-width:34rem;margin:auto">
<h2 style="margin:0 0 6px">Saved: ${yes ? "👍 more like this" : "👎 not for me"} — closing…</h2>
<p style="color:#555;margin:0 0 22px">You can close this tab.
<a href="/api/a?j=${encodeURIComponent(j)}&k=${flip}"
   style="color:#b45309;text-decoration:none">Tapped wrong? Mark ${yes ? "👎" : "👍"} instead</a></p>
<script>window.close()</script></body>`;
  }
  return `<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font:16px -apple-system,sans-serif;padding:44px;max-width:34rem;margin:auto">
<h2 style="margin:0 0 6px">Logged: ${action}</h2>
<p style="color:#555;margin:0 0 22px">This one drops off tomorrow's email.</p>
<a href="/api/a?j=${encodeURIComponent(j)}&k=undo"
   style="color:#b45309;text-decoration:none">Undo — put it back</a></body>`;
}
