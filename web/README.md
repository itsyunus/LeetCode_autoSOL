# LeetCode Control Center

A mobile-first, static PWA for controlling the existing `LeetCode_autoSOL` GitHub Actions workflow. It does not modify the solver or the Cookie Pusher extension.

## Deploy on Vercel

1. Import `itsyunus/LeetCode_autoSOL` into Vercel.
2. Set **Root Directory** to `web`.
3. Set Framework Preset to **Other**; no build command is required and the output directory is the project root.
4. Deploy. Vercel will publish the static PWA and subsequent commits to the selected production branch will redeploy it.

The app has no server-side environment variables and never sends your GitHub token to Vercel. All GitHub API calls happen in your browser.

## Connect

Create a fine-grained GitHub personal access token scoped to this repository with **Actions: Read and write**. Enter it in the dashboard. The token is stored in `sessionStorage` for the current browser tab only; it is not stored in localStorage, source files, or a backend. Use HTTPS and do not share the browser session.

The dashboard can:
- Read recent runs and workflow job metadata.
- Dispatch the existing `daily_solve.yml` workflow with its current dry-run and language inputs.
- Display the latest committed `logs/result_YYYY-MM-DD.json` result.
- Link to the authoritative GitHub Actions run and artifacts.
- Poll for status while the page is open.

## Authentication boundary

A website on a phone cannot read cookies from a separate LeetCode browser session, and GitHub does not reveal the values of Actions secrets. The existing Cookie Pusher extension remains the secure desktop helper for refreshing `LEETCODE_SESSION` and `LEETCODE_CSRF_TOKEN`. Do not paste those cookies into this website. If they expire, refresh them with the extension, then return to this dashboard.

## Existing automation preserved

The daily cron remains in `.github/workflows/daily_solve.yml` at `30 0 * * *` (06:00 Asia/Kolkata). The dashboard only calls the existing workflow_dispatch endpoint; it does not change the solver code or schedule.
