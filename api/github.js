const crypto = require("crypto");
function validSession(req) {
  const raw = (req.headers.cookie || "").split(";").map(v => v.trim()).find(v => v.startsWith("lc_dashboard_session="));
  if (!raw) return false;
  const parts = raw.slice("lc_dashboard_session=".length).split(".");
  if (parts.length !== 2 || !/^\d+$/.test(parts[0])) return false;
  const now = Math.floor(Date.now() / 1000), expires = Number(parts[0]);
  if (expires < now || expires > now + 46800) return false;
  const expected = crypto.createHmac("sha256", process.env.SESSION_SECRET).update(parts[0]).digest("hex");
  const a = Buffer.from(parts[1]), b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (!validSession(req)) return res.status(401).json({ message: "Dashboard session expired." });
  if (!process.env.GITHUB_TOKEN) return res.status(503).json({ message: "GitHub server token is not configured. Add GITHUB_TOKEN to this Vercel project's Production environment variables." });
  const path = String(req.query.path || "");
  if (!(path === "/repos/itsyunus/LeetCode_autoSOL" || path.startsWith("/repos/itsyunus/LeetCode_autoSOL/"))) return res.status(400).json({ message: "This dashboard is restricted to its configured solver repository." });
  if (!["GET", "POST"].includes(req.method)) return res.status(405).json({ message: "Method not allowed." });
  try {
    const response = await fetch("https://api.github.com" + path, {
      method: req.method,
      headers: { "Accept": "application/vnd.github+json", "Authorization": "Bearer " + process.env.GITHUB_TOKEN, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "LeetCode-Control-Center", ...(req.method === "POST" ? { "Content-Type": "application/json" } : {}) },
      ...(req.method === "POST" ? { body: JSON.stringify(req.body || {}) } : {})
    });
    const body = await response.text();
    res.status(response.status);
    if (response.status === 204 || !body) return res.end();
    res.setHeader("Content-Type", response.headers.get("content-type") || "application/json");
    return res.send(body);
  } catch (_) { return res.status(502).json({ message: "Unable to reach GitHub. Please try again." }); }
};