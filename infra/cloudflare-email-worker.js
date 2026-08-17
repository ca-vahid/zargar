/**
 * Cloudflare Email Worker → Zargar ingestion webhook.
 *
 * Setup:
 *  1. Add your domain to Cloudflare and enable Email Routing.
 *  2. Create a Worker with this script; add two secrets/vars:
 *       ZARGAR_URL        e.g. https://your-tailnet-host:8420  (or a tunnel URL)
 *       ZARGAR_INGEST_KEY same value as ZARGAR_INGEST_KEY in backend/.env
 *  3. Route  signals@yourdomain.com  →  this worker.
 *  4. Re-subscribe your newsletters with that address.
 *
 * The worker forwards the parsed email as JSON to POST /api/ingest/email and
 * (optionally) forwards a copy to your personal inbox.
 */
import PostalMime from "postal-mime";

export default {
  async email(message, env, ctx) {
    const parser = new PostalMime();
    const raw = await new Response(message.raw).arrayBuffer();
    const email = await parser.parse(raw);

    const payload = {
      from: message.from,
      to: message.to,
      subject: email.subject || message.headers.get("subject") || "",
      text: email.text || "",
      html: email.html || "",
      headers: Object.fromEntries(message.headers),
      // Email Routing only delivers mail that passed SPF/DKIM/DMARC checks,
      // but pass the auth results header along for the audit trail.
      spf: message.headers.get("authentication-results") || "",
      dkim: "",
    };

    ctx.waitUntil(
      fetch(`${env.ZARGAR_URL}/api/ingest/email`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Zargar-Ingest-Key": env.ZARGAR_INGEST_KEY,
        },
        body: JSON.stringify(payload),
      }),
    );

    // Optional: keep a copy in your personal inbox.
    // await message.forward("you@personal-inbox.com");
  },
};
