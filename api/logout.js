module.exports = async (_req, res) => {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Set-Cookie", "lc_dashboard_session=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0");
  return res.status(200).json({ ok: true });
};