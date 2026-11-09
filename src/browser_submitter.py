"""
LeetCode Browser Submitter
Uses Playwright (headless Chromium) to submit solutions.
Bypasses Cloudflare protection that blocks raw HTTP requests.

This is the primary submission method — the requests-based API
is used only for reading (fetching problems, checking status).
"""

import json
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class BrowserSubmitter:
    """Submit LeetCode solutions through a real headless browser."""

    def __init__(self, session_token: str, csrf_token: str):
        self.session_token = session_token
        self.csrf_token = csrf_token
        self._pw = None
        self._browser = None
        self._context = None

    def _ensure_browser(self):
        """Lazily start the browser on first use."""
        if self._context:
            return

        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )

        # Inject LeetCode session cookies
        self._context.add_cookies([
            {
                "name": "LEETCODE_SESSION",
                "value": self.session_token,
                "domain": ".leetcode.com",
                "path": "/",
            },
            {
                "name": "csrftoken",
                "value": self.csrf_token,
                "domain": ".leetcode.com",
                "path": "/",
            },
        ])
        logger.info("Browser context ready with session cookies")

    def submit_solution(
        self,
        slug: str,
        question_id: str,
        code: str,
        lang_slug: str = "python3",
    ) -> Dict[str, Any]:
        """
        Submit a solution via the browser.
        Navigates to the problem page first (Cloudflare pass-through),
        then submits via the GraphQL/REST API from within the browser context.
        """
        self._ensure_browser()
        page = self._context.new_page()

        try:
            problem_url = f"https://leetcode.com/problems/{slug}/"
            logger.info(f"Navigating to {problem_url}...")

            # Step 1: Visit the problem page to pass Cloudflare
            page.goto(problem_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Step 2: Submit via fetch() inside the browser context
            # This inherits all cookies + Cloudflare clearance
            submit_script = """
            async (params) => {
                const { slug, questionId, code, langSlug } = params;
                const csrfToken = document.cookie
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                    ?.split('=')[1] || '';

                const response = await fetch(`/problems/${slug}/submit/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'x-csrftoken': csrfToken,
                        'Referer': `https://leetcode.com/problems/${slug}/`,
                    },
                    body: JSON.stringify({
                        lang: langSlug,
                        question_id: questionId,
                        typed_code: code,
                    }),
                });

                const contentType = response.headers.get('content-type') || '';
                const body = await response.text();
                if (!contentType.toLowerCase().includes('application/json')) {
                    const preview = body.slice(0, 240).replace(/\s+/g, ' ');
                    throw new Error('LeetCode returned non-JSON response (HTTP ' + response.status +
                        ', ' + (contentType || 'unknown content type') +
                        '). Check session validity, rate limits, or security challenge. Preview: ' + preview);
                }
                let data;
                try { data = JSON.parse(body); }
                catch (error) { throw new Error('LeetCode returned invalid JSON: ' + error.message); }
                return { status: response.status, data };
            }
            """

            result = page.evaluate(
                submit_script,
                {
                    "slug": slug,
                    "questionId": question_id,
                    "code": code,
                    "langSlug": lang_slug,
                },
            )

            if result["status"] != 200:
                raise RuntimeError(
                    f"Submit returned {result['status']}: {json.dumps(result['data'])}"
                )

            submission_id = result["data"].get("submission_id")
            logger.info(f"✅ Submitted! Submission ID: {submission_id}")
            return result["data"]

        finally:
            page.close()

    def poll_submission_result(
        self, submission_id: int, max_retries: int = 20, interval: float = 2.0
    ) -> Dict[str, Any]:
        """Poll submission status via the browser context."""
        self._ensure_browser()
        page = self._context.new_page()

        try:
            # Navigate to a LeetCode page first for cookie context
            page.goto("https://leetcode.com", wait_until="domcontentloaded", timeout=15000)
            time.sleep(1)

            for attempt in range(max_retries):
                check_script = """
                async (submissionId) => {
                    const response = await fetch(
                        `/submissions/detail/${submissionId}/check/`,
                        { headers: { 'Referer': 'https://leetcode.com/' } }
                    );
                    const contentType = response.headers.get('content-type') || '';
                    const body = await response.text();
                    if (!contentType.toLowerCase().includes('application/json')) {
                        throw new Error('LeetCode status check returned non-JSON HTTP ' + response.status);
                    }
                    try { return JSON.parse(body); }
                    catch (error) { throw new Error('Invalid JSON from LeetCode status check: ' + error.message); }
                }
                """
                result = page.evaluate(check_script, submission_id)
                state = result.get("state")

                if state == "SUCCESS":
                    status_msg = result.get("status_msg", "Unknown")
                    if status_msg == "Accepted":
                        runtime = result.get("status_runtime", "N/A")
                        memory = result.get("status_memory", "N/A")
                        logger.info(f"✅ ACCEPTED — Runtime: {runtime}, Memory: {memory}")
                    else:
                        logger.warning(f"❌ {status_msg}")
                    return result

                logger.debug(f"Poll {attempt + 1}/{max_retries}, state={state}")
                time.sleep(interval)

            raise TimeoutError(f"Submission {submission_id} still pending")
        finally:
            page.close()

    def run_code(
        self,
        slug: str,
        question_id: str,
        code: str,
        test_input: str,
        lang_slug: str = "python3",
    ) -> Dict[str, Any]:
        """Run code against test cases via the browser."""
        self._ensure_browser()
        page = self._context.new_page()

        try:
            page.goto(
                f"https://leetcode.com/problems/{slug}/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(3)

            run_script = """
            async (params) => {
                const { slug, questionId, code, testInput, langSlug } = params;
                const csrfToken = document.cookie
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                    ?.split('=')[1] || '';

                const response = await fetch(`/problems/${slug}/interpret_solution/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'x-csrftoken': csrfToken,
                        'Referer': `https://leetcode.com/problems/${slug}/`,
                    },
                    body: JSON.stringify({
                        lang: langSlug,
                        question_id: questionId,
                        typed_code: code,
                        data_input: testInput,
                    }),
                });

                const contentType = response.headers.get('content-type') || '';
                const body = await response.text();
                if (!contentType.toLowerCase().includes('application/json')) {
                    throw new Error('LeetCode run endpoint returned non-JSON HTTP ' + response.status);
                }
                let data;
                try { data = JSON.parse(body); }
                catch (error) { throw new Error('Invalid JSON from LeetCode run endpoint: ' + error.message); }
                return { status: response.status, data };
            }
            """

            result = page.evaluate(
                run_script,
                {
                    "slug": slug,
                    "questionId": question_id,
                    "code": code,
                    "testInput": test_input,
                    "langSlug": lang_slug,
                },
            )

            if result["status"] != 200:
                raise RuntimeError(f"Run returned {result['status']}")

            interpret_id = result["data"].get("interpret_id")

            # Poll for result
            for _ in range(20):
                check_script = """
                async (id) => {
                    const r = await fetch(`/submissions/detail/${id}/check/`);
                    const contentType = r.headers.get('content-type') || '';
                    const body = await r.text();
                    if (!contentType.toLowerCase().includes('application/json')) {
                        throw new Error('LeetCode run status returned non-JSON HTTP ' + r.status);
                    }
                    try { return JSON.parse(body); }
                    catch (error) { throw new Error('Invalid JSON from LeetCode run status: ' + error.message); }
                }
                """
                check = page.evaluate(check_script, interpret_id)
                if check.get("state") == "SUCCESS":
                    return check
                time.sleep(1.5)

            raise TimeoutError("Code run timed out")
        finally:
            page.close()

    def close(self):
        """Clean up browser resources."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

