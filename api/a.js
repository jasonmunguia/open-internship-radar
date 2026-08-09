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
  const action = ["applied", "networked"].includes(k) ? k : "applied";

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
  return `<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font:16px -apple-system,sans-serif;padding:44px;max-width:34rem;margin:auto">
<h2 style="margin:0 0 6px">Logged: ${action}</h2>
<p style="color:#555;margin:0 0 22px">This one drops off tomorrow's email.</p>
<a href="/api/a?j=${encodeURIComponent(j)}&k=undo"
   style="color:#b45309;text-decoration:none">Undo — put it back</a></body>`;
}
