# LeetCode Control Center

A mobile-first, installable static PWA for controlling the existing `LeetCode_autoSOL` GitHub Actions workflow. It does not modify the solver or the Cookie Pusher extension.

## Publish free with GitHub Pages

1. Merge the control-center pull request into `main`.
2. In the repository, open **Settings → Pages**.
3. Under **Build and deployment**, set **Source** to **GitHub Actions**.
4. Open **Actions → Deploy LeetCode Control Center** and run it once if it has not started automatically.
5. When the deployment succeeds, the site will be available at:
   `https://itsyunus.github.io/LeetCode_autoSOL/`

The included `.github/workflows/deploy-control-center.yml` redeploys the site whenever files under `web/` change on `main`. The existing daily solver workflow and its 06:00 IST schedule are untouched.

## Optional: deploy on Vercel

1. Import `itsyunus/LeetCode_autoSOL` into Vercel.
2. Set **Root Directory** to `web`.
3. Set Framework Preset to **Other**; no build command is required and the output directory is the project root.
4. Deploy.

## Connect securely

The dashboard is protected by a passcode screen. A successful unlock creates a 12-hour HttpOnly, Secure, SameSite session cookie. GitHub API requests are proxied through Vercel and use a server-side `GITHUB_TOKEN` environment variable; the token is never sent to browser JavaScript.

In Vercel, add `GITHUB_TOKEN` to the Production environment for this project. Use a fine-grained GitHub token scoped only to `itsyunus/LeetCode_autoSOL` with **Actions: Read and write** and **Contents: Read-only**. Never put the token in the repository or chat. The passcode is stored as an encrypted Vercel environment variable.

The existing Cookie Pusher extension remains the desktop helper for refreshing `LEETCODE_SESSION` and `LEETCODE_CSRF_TOKEN`. Do not paste LeetCode cookies into this website.

The app can:
- Read recent workflow runs and workflow job metadata.
- Dispatch the existing `daily_solve.yml` workflow with its current dry-run and language inputs.
- Display the latest committed `logs/result_YYYY-MM-DD.json` result.
- Link to the authoritative GitHub Actions run and its artifacts.
- Poll for status while the page is open.

## Existing automation preserved

The daily cron remains in `.github/workflows/daily_solve.yml` at `30 0 * * *` (06:00 Asia/Kolkata). The dashboard only calls the existing workflow-dispatch endpoint; it does not change the solver code or schedule.
