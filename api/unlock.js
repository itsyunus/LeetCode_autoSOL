const crypto = require("crypto");
const attempts = new Map();
module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  const ip = (req.headers["x-forwarded-for"] || "unknown").split(",")[0].trim();
  const now = Date.now();
  const entry = attempts.get(ip) || { count: 0, start: now };
  if (now - entry.start > 900000) { entry.count = 0; entry.start = now; }
  if (entry.count >= 12) return res.status(429).json({ error: "Too many attempts. Try again in 15 minutes." });
  const supplied = String((req.body && req.body.passcode) || "");
  const expected = String(process.env.DASHBOARD_PASSCODE || "");
  const a = Buffer.from(supplied), b = Buffer.from(expected);
  const valid = expected.length > 0 && a.length === b.length && crypto.timingSafeEqual(a, b);
  if (!valid) { entry.count += 1; attempts.set(ip, entry); return res.status(401).json({ error: "Incorrect passcode. Try again." }); }
  attempts.delete(ip);
  const expires = Math.floor(Date.now() / 1000) + 43200;
  const payload = String(expires);
  const signature = crypto.createHmac("sha256", process.env.SESSION_SECRET).update(payload).digest("hex");
  res.setHeader("Set-Cookie", "lc_dashboard_session=" + payload + "." + signature + "; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=43200");
  return res.status(200).json({ authenticated: true, expiresAt: expires });
};