const crypto = require("crypto");
module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  const raw = (req.headers.cookie || "").split(";").map(v => v.trim()).find(v => v.startsWith("lc_dashboard_session="));
  if (!raw) return res.status(401).json({ authenticated: false });
  const parts = raw.slice("lc_dashboard_session=".length).split(".");
  if (parts.length !== 2 || !/^\d+$/.test(parts[0])) return res.status(401).json({ authenticated: false });
  const now = Math.floor(Date.now() / 1000), expires = Number(parts[0]);
  if (expires < now || expires > now + 46800) return res.status(401).json({ authenticated: false });
  const expected = crypto.createHmac("sha256", process.env.SESSION_SECRET).update(parts[0]).digest("hex");
  const a = Buffer.from(parts[1]), b = Buffer.from(expected);
  const valid = a.length === b.length && crypto.timingSafeEqual(a, b);
  return res.status(valid ? 200 : 401).json({ authenticated: valid, expiresAt: valid ? expires : null });
};