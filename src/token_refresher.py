"""
Automatic LeetCode Session Refresher — nodriver Edition
═══════════════════════════════════════════════════════════
Logs into LeetCode using username/password through an undetectable
Chrome instance (nodriver), extracts fresh session cookies, and
pushes them to GitHub Secrets automatically.

Strategies (in priority order):
  1. nodriver — undetectable Chrome, invisible to Cloudflare
  2. Direct API login — fast, no browser, but often 403'd
  3. requests session with cookie rotation headers

Runs as a standalone GitHub Actions workflow on a 3-day schedule,
or as a pre-step in the daily solver. Zero human intervention.
"""

import os
import sys
import json
import time
import asyncio
import logging
import base64
import random
import requests
from typing import Optional, Tuple, Dict
from nacl import encoding, public  # PyNaCl for GitHub secret encryption

try:
    import nodriver.cdp as cdp
except ImportError:
    cdp = None

logger = logging.getLogger(__name__)

# ─── Randomized browser fingerprint data ────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    (1920, 1080), (1536, 864), (1440, 900),
    (1366, 768), (2560, 1440), (1680, 1050),
]


class NodriverAuthenticator:
    """
    Uses nodriver (undetected Chrome) to login to LeetCode.
    nodriver bypasses Cloudflare Turnstile by:
      - Not injecting CDP flags that Playwright/Selenium do
      - Using real Chrome binary with no automation indicators
      - Randomized fingerprinting (viewport, user-agent, timing)
    """

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    async def login(self) -> Tuple[str, str]:
        """
        Launch undetectable Chrome, navigate to LeetCode login,
        fill credentials with human-like timing, extract cookies.
        """
        import nodriver as uc

        logger.info("Launching undetectable Chrome via nodriver...")

        # Randomize fingerprint
        viewport = random.choice(VIEWPORTS)
        ua = random.choice(USER_AGENTS)

        # Find the best Chrome binary — prefer google-chrome-stable over snap chromium
        import shutil
        chrome_path = None
        for candidate in [
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            shutil.which("google-chrome-stable"),
            shutil.which("google-chrome"),
            shutil.which("chromium-browser"),
            shutil.which("chromium"),
        ]:
            if candidate and os.path.isfile(candidate):
                chrome_path = candidate
                break

        logger.info(f"Using Chrome binary: {chrome_path or 'auto-detect'}")

        # Use Config object for better control over connection retries
        config = uc.Config(
            headless=True,
            sandbox=False,
            browser_connection_max_tries=15,   # More retries for slow CI runners
            browser_connection_timeout=5,       # Seconds per retry
            browser_args=[
                f"--window-size={viewport[0]},{viewport[1]}",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "--disable-extensions",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-zygote",
                f"--user-agent={ua}",
            ],
        )
        if chrome_path:
            config.browser_executable_path = chrome_path

        # Retry browser launch — CI runners can be flaky
        browser = None
        for attempt in range(3):
            try:
                logger.info(f"Browser launch attempt {attempt + 1}/3...")
                browser = await uc.Browser.create(config=config)
                logger.info("Browser connected successfully!")
                break
            except Exception as e:
                logger.warning(f"Launch attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(3)
                else:
                    raise

        if not browser:
            raise RuntimeError("Failed to launch Chrome after 3 attempts")

        try:
            tab = await browser.get("https://leetcode.com/accounts/login/")

            # Let Cloudflare challenge resolve naturally
            logger.info("Waiting for Cloudflare challenge to clear...")
            await asyncio.sleep(random.uniform(4, 7))

            # Check if we're past Cloudflare
            for attempt in range(5):
                current_url = tab.url or ""
                try:
                    source = await tab.evaluate("document.documentElement.outerHTML")
                except Exception:
                    source = ""
                if "accounts/login" in current_url or "sign-in" in current_url.lower():
                    logger.info("Login page loaded successfully")
                    break
                if "challenge" in current_url.lower() or "ray id" in source.lower():
                    logger.info(f"Cloudflare challenge still active, waiting... (attempt {attempt + 1})")
                    await asyncio.sleep(random.uniform(3, 6))
                else:
                    break

            # Human-like pause before typing
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # ── Find and fill username ──────────────────────────────
            # nodriver uses tab.select() (CSS) and tab.find() (text content)
            username_input = None
            username_selectors = [
                'input[name="login"]',
                '#id_login',
                'input[autocomplete="username"]',
                'input[type="text"]',
                'input[name="email"]',
            ]
            for selector in username_selectors:
                try:
                    username_input = await asyncio.wait_for(
                        tab.select(selector), timeout=3
                    )
                    if username_input:
                        logger.info(f"Found username field with: {selector}")
                        break
                except (asyncio.TimeoutError, Exception):
                    continue

            if not username_input:
                try:
                    username_input = await asyncio.wait_for(
                        tab.find("Username or E-mail", best_match=True), timeout=3
                    )
                    if username_input:
                        logger.info("Found username field by text content")
                except (asyncio.TimeoutError, Exception):
                    pass

            if not username_input:
                # Last resort: use JS to find and focus the first text input
                try:
                    await tab.evaluate("""
                        const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input:not([type])');
                        if (inputs.length > 0) inputs[0].focus();
                    """)
                    username_input = await asyncio.wait_for(
                        tab.select("input:focus"), timeout=3
                    )
                    if username_input:
                        logger.info("Found username field via JS focus")
                except (asyncio.TimeoutError, Exception):
                    pass

            if not username_input:
                try:
                    source = await tab.evaluate("document.documentElement.outerHTML")
                except Exception:
                    source = ""
                logger.error(f"Could not find username field. Page URL: {tab.url}")
                logger.info(f"Page HTML (first 3000 chars): {source[:3000]}")
                raise RuntimeError("Username field not found on login page")

            # Fill username using both native keystrokes and React synthetic event setter
            await username_input.click()
            await asyncio.sleep(random.uniform(0.2, 0.4))
            await username_input.clear_input()
            for char in self.username:
                await username_input.send_keys(char)
                await asyncio.sleep(random.uniform(0.02, 0.06))

            # Force React 18 / Next.js to register the state update
            await tab.evaluate(f"""
                (() => {{
                    const el = document.querySelector('input[name="login"], #id_login, input[type="text"], input[autocomplete="username"]');
                    if (el) {{
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                        if (setter) setter.call(el, {json.dumps(self.username)});
                        else el.value = {json.dumps(self.username)};
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }})()
            """)
            logger.info("Username filled and React state synced")
            await asyncio.sleep(random.uniform(0.4, 0.8))

            # ── Find and fill password ──────────────────────────────
            password_input = None
            password_selectors = [
                'input[name="password"]',
                '#id_password',
                'input[type="password"]',
            ]
            for selector in password_selectors:
                try:
                    password_input = await asyncio.wait_for(
                        tab.select(selector), timeout=3
                    )
                    if password_input:
                        logger.info(f"Found password field with: {selector}")
                        break
                except (asyncio.TimeoutError, Exception):
                    continue

            if not password_input:
                try:
                    password_input = await asyncio.wait_for(
                        tab.find("Password", best_match=True), timeout=3
                    )
                except (asyncio.TimeoutError, Exception):
                    pass

            if not password_input:
                raise RuntimeError("Password field not found on login page")

            await password_input.click()
            await asyncio.sleep(random.uniform(0.2, 0.4))
            await password_input.clear_input()
            for char in self.password:
                await password_input.send_keys(char)
                await asyncio.sleep(random.uniform(0.02, 0.06))

            # Force React state sync on password field
            await tab.evaluate(f"""
                (() => {{
                    const el = document.querySelector('input[name="password"], #id_password, input[type="password"]');
                    if (el) {{
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                        if (setter) setter.call(el, {json.dumps(self.password)});
                        else el.value = {json.dumps(self.password)};
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }})()
            """)
            logger.info("Password filled and React state synced")

            # Human pause before submitting
            await asyncio.sleep(random.uniform(1.0, 1.8))

            # ── Submit the login form ────────────────────────────────
            # 1. First attempt: click the submit button
            submit_btn = None
            submit_selectors = [
                '#signin_btn',
                'button[type="submit"]',
                'button[data-cy="sign-in-btn"]',
            ]
            for selector in submit_selectors:
                try:
                    submit_btn = await asyncio.wait_for(
                        tab.select(selector), timeout=3
                    )
                    if submit_btn:
                        logger.info(f"Found submit button with: {selector}")
                        break
                except (asyncio.TimeoutError, Exception):
                    continue

            # Check if button is disabled in DOM and enable it if needed
            btn_state = await tab.evaluate("""
                (() => {
                    const btn = document.querySelector('#signin_btn, button[type="submit"]');
                    if (!btn) return { exists: false };
                    return {
                        exists: true,
                        disabled: btn.disabled,
                        innerText: btn.innerText,
                        classes: btn.className
                    };
                })()
            """)
            logger.info(f"Submit button state: {btn_state}")

            if submit_btn:
                await submit_btn.click()
                logger.info("Clicked submit button via nodriver")

            # 2. Also dispatch form submit and press Enter via JavaScript & keyboard
            await tab.evaluate("""
                (() => {
                    const btn = document.querySelector('#signin_btn, button[type="submit"]');
                    if (btn) {
                        btn.disabled = false;
                        btn.click();
                    }
                    const form = document.querySelector('form');
                    if (form) {
                        try { form.requestSubmit(); } catch (e) { form.submit(); }
                    }
                })()
            """)
            await password_input.send_keys("\r")
            logger.info("Dispatched form submit and Enter key")

            # Wait for redirect after login
            logger.info("Waiting for login redirect...")
            for i in range(20):
                await asyncio.sleep(1.5)
                current_url = tab.url or ""
                if "login" not in current_url.lower() and "accounts" not in current_url.lower():
                    logger.info(f"Redirected to: {current_url}")
                    break
                if i == 5:
                    # At ~9 seconds, capture page state for debugging
                    try:
                        page_text = await tab.evaluate("document.body.innerText")
                        logger.info(f"Page text at 9s (first 1000 chars): {page_text[:1000]}")
                    except Exception:
                        pass
                if i == 19:
                    # Capture final page state
                    try:
                        page_text = await tab.evaluate("document.body.innerText")
                        page_html = await tab.evaluate("document.body.innerHTML")
                        logger.warning(f"Still on login page after 30s. URL: {current_url}")
                        logger.info(f"Final page text: {page_text[:2000]}")
                        logger.info(f"Final page HTML (first 2000 chars): {page_html[:2000]}")
                    except Exception as e:
                        logger.warning(f"Still on login page after 30s. URL: {current_url}. Could not capture page state: {e}")

            # Extra settle time for cookies
            await asyncio.sleep(random.uniform(2, 4))

            # ── Extract cookies ──────────────────────────────────────
            logger.info("Extracting cookies...")
            session_token = None
            csrf_token = None

            # Method 1: nodriver cookie API
            try:
                cookies = await browser.cookies.get_all()
                cookie_names = [getattr(c, 'name', '') or (c.get('name', '') if isinstance(c, dict) else '') for c in cookies]
                logger.info(f"Retrieved {len(cookies)} cookies: {cookie_names}")
                for cookie in cookies:
                    name = getattr(cookie, 'name', '') or (cookie.get('name', '') if isinstance(cookie, dict) else '')
                    value = getattr(cookie, 'value', '') or (cookie.get('value', '') if isinstance(cookie, dict) else '')
                    if name == "LEETCODE_SESSION":
                        session_token = value
                    elif name == "csrftoken":
                        csrf_token = value
            except Exception as e:
                logger.warning(f"Cookie API failed: {e}")

            # Method 2: Raw CDP storage/network domain
            if not session_token and cdp:
                try:
                    logger.info("Querying CDP storage.get_cookies directly...")
                    raw_cookies = await tab.send(cdp.storage.get_cookies())
                    for c in raw_cookies:
                        name = getattr(c, 'name', '')
                        value = getattr(c, 'value', '')
                        if name == "LEETCODE_SESSION":
                            session_token = value
                        elif name == "csrftoken":
                            csrf_token = value
                except Exception as e:
                    logger.warning(f"CDP storage.get_cookies failed: {e}")

            # Method 2: JS document.cookie
            if not session_token:
                try:
                    js_cookies = await tab.evaluate("document.cookie")
                    logger.info(f"JS cookies (truncated): {js_cookies[:200]}...")
                    for part in js_cookies.split(";"):
                        part = part.strip()
                        if part.startswith("LEETCODE_SESSION="):
                            session_token = part.split("=", 1)[1]
                        elif part.startswith("csrftoken="):
                            csrf_token = part.split("=", 1)[1]
                except Exception as e:
                    logger.warning(f"JS cookie extraction failed: {e}")

            # Method 3: Navigate to problemset then retry
            if not session_token:
                logger.info("No session cookie yet — navigating to problemset...")
                try:
                    await browser.get("https://leetcode.com/problemset/")
                    await asyncio.sleep(4)
                    cookies = await browser.cookies.get_all()
                    for cookie in cookies:
                        name = getattr(cookie, 'name', '') or (cookie.get('name', '') if isinstance(cookie, dict) else '')
                        value = getattr(cookie, 'value', '') or (cookie.get('value', '') if isinstance(cookie, dict) else '')
                        if name == "LEETCODE_SESSION":
                            session_token = value
                        elif name == "csrftoken":
                            csrf_token = value
                except Exception as e:
                    logger.warning(f"Problemset cookie extraction failed: {e}")

            if not session_token:
                raise RuntimeError(
                    "Login completed but no LEETCODE_SESSION cookie found. "
                    "Cloudflare may have blocked the login attempt."
                )

            logger.info("✅ nodriver login successful — cookies extracted!")
            return session_token, csrf_token or ""

        finally:
            browser.stop()


class DirectAPIAuthenticator:
    """Fallback: Direct HTTP login (often blocked by Cloudflare but worth trying)."""

    LOGIN_URL = "https://leetcode.com/accounts/login/"
    GRAPHQL_URL = "https://leetcode.com/graphql"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        ua = random.choice(USER_AGENTS)
        self.session.headers.update({
            "User-Agent": ua,
            "Referer": "https://leetcode.com",
            "Origin": "https://leetcode.com",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        })

    def login(self) -> Tuple[str, str]:
        import re

        logger.info("Attempting direct API login...")

        # Step 1: GET login page for CSRF token
        resp = self.session.get(self.LOGIN_URL, timeout=30)
        resp.raise_for_status()

        csrf_token = self.session.cookies.get("csrftoken", "")
        if not csrf_token:
            match = re.search(r"csrfmiddlewaretoken.*?value=['\"](.+?)['\"]", resp.text)
            if match:
                csrf_token = match.group(1)
        if not csrf_token:
            raise RuntimeError("Could not obtain initial CSRF token from login page")

        # Step 2: POST credentials
        self.session.headers.update({"x-csrftoken": csrf_token})
        login_data = {
            "login": self.username,
            "password": self.password,
            "csrfmiddlewaretoken": csrf_token,
        }

        resp = self.session.post(
            self.LOGIN_URL, data=login_data,
            timeout=30, allow_redirects=True,
        )

        # Step 3: Extract cookies
        session_token = (
            self.session.cookies.get("LEETCODE_SESSION", domain=".leetcode.com")
            or self.session.cookies.get("LEETCODE_SESSION")
        )
        new_csrf = (
            self.session.cookies.get("csrftoken", domain=".leetcode.com")
            or self.session.cookies.get("csrftoken")
        )

        if not session_token:
            raise RuntimeError(
                f"API login failed — no session token. "
                f"Status: {resp.status_code}, URL: {resp.url}"
            )

        logger.info("✅ API login successful!")
        return session_token, new_csrf or csrf_token


class GitHubSecretsUpdater:
    """Updates GitHub repository secrets via the GitHub API."""

    API_BASE = "https://api.github.com"

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get_public_key(self) -> Tuple[str, str]:
        url = f"{self.API_BASE}/repos/{self.repo}/actions/secrets/public-key"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data["key"], data["key_id"]

    def _encrypt_secret(self, public_key: str, secret_value: str) -> str:
        pk = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        sealed_box = public.SealedBox(pk)
        encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")

    def update_secret(self, secret_name: str, secret_value: str):
        pub_key, key_id = self._get_public_key()
        encrypted_value = self._encrypt_secret(pub_key, secret_value)

        url = f"{self.API_BASE}/repos/{self.repo}/actions/secrets/{secret_name}"
        payload = {"encrypted_value": encrypted_value, "key_id": key_id}

        resp = requests.put(url, headers=self.headers, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info(f"✅ Updated GitHub secret: {secret_name}")

    def update_leetcode_tokens(self, session_token: str, csrf_token: str):
        self.update_secret("LEETCODE_SESSION", session_token)
        self.update_secret("LEETCODE_CSRF_TOKEN", csrf_token)
        logger.info("✅ Both LeetCode secrets updated in GitHub!")


def validate_session(session_token: str, csrf_token: str) -> str:
    """Verify tokens work by querying LeetCode GraphQL. Returns username."""
    logger.info("Validating session tokens...")

    session = requests.Session()
    session.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
    session.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
    session.headers.update({
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "x-csrftoken": csrf_token,
        "User-Agent": random.choice(USER_AGENTS),
    })

    query = """
    query globalData {
        userStatus {
            username
            isSignedIn
        }
    }
    """
    resp = session.post(
        "https://leetcode.com/graphql",
        json={"query": query},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    user_status = data.get("data", {}).get("userStatus", {})
    if not user_status.get("isSignedIn"):
        raise RuntimeError("Token validation failed — not signed in")

    username = user_status.get("username", "unknown")
    logger.info(f"✅ Session valid — logged in as: {username}")
    return username


class TokenRefreshPipeline:
    """
    Full pipeline: Login → Validate → Push to GitHub Secrets.
    Strategies tried in order: nodriver → direct API.
    """

    def __init__(
        self,
        leetcode_username: str,
        leetcode_password: str,
        github_token: str,
        github_repo: str,
    ):
        self.username = leetcode_username
        self.password = leetcode_password
        self.github = GitHubSecretsUpdater(github_token, github_repo)

    async def _try_nodriver(self) -> Tuple[str, str]:
        auth = NodriverAuthenticator(self.username, self.password)
        return await auth.login()

    def _try_api(self) -> Tuple[str, str]:
        auth = DirectAPIAuthenticator(self.username, self.password)
        return auth.login()

    async def refresh_async(self) -> Dict[str, str]:
        """Execute full token refresh (async version for nodriver)."""
        logger.info("=" * 60)
        logger.info("🔄 LeetCode Token Auto-Refresh Pipeline")
        logger.info("=" * 60)

        session_token = None
        csrf_token = None
        strategy_used = None

        # Strategy 1: nodriver (undetectable Chrome)
        try:
            logger.info("━━━ Strategy 1: nodriver (undetectable Chrome) ━━━")
            session_token, csrf_token = await self._try_nodriver()
            strategy_used = "nodriver"
        except Exception as e:
            logger.warning(f"nodriver login failed: {e}")

        # Strategy 2: Direct API
        if not session_token:
            try:
                logger.info("━━━ Strategy 2: Direct API login ━━━")
                session_token, csrf_token = self._try_api()
                strategy_used = "direct_api"
            except Exception as e:
                logger.warning(f"API login failed: {e}")

        if not session_token:
            raise RuntimeError(
                "All login strategies failed. LeetCode may require manual intervention. "
                "Try refreshing cookies manually via the Chrome extension."
            )

        # Validate before pushing
        username = validate_session(session_token, csrf_token)

        # Push to GitHub Secrets
        self.github.update_leetcode_tokens(session_token, csrf_token)

        logger.info("=" * 60)
        logger.info(f"✅ TOKEN REFRESH COMPLETE (via {strategy_used})")
        logger.info(f"   Logged in as: {username}")
        logger.info("=" * 60)

        return {
            "session_token": session_token,
            "csrf_token": csrf_token,
            "username": username,
            "strategy": strategy_used,
        }

    def refresh(self) -> Dict[str, str]:
        """Sync wrapper around the async refresh pipeline."""
        # Use a fresh event loop to avoid 'Event loop is closed' errors
        # when nodriver's browser subprocess cleanup races with loop shutdown.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.refresh_async())
        finally:
            # Graceful shutdown: cancel remaining tasks, then close
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()


def main():
    """Entry point — reads config from environment variables."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    username = os.environ.get("LEETCODE_USERNAME")
    password = os.environ.get("LEETCODE_PASSWORD")
    gh_token = os.environ.get("GH_PAT")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")

    if not all([username, password, gh_token, gh_repo]):
        missing = []
        if not username: missing.append("LEETCODE_USERNAME")
        if not password: missing.append("LEETCODE_PASSWORD")
        if not gh_token: missing.append("GH_PAT")
        if not gh_repo: missing.append("GITHUB_REPOSITORY")
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        sys.exit(1)

    pipeline = TokenRefreshPipeline(username, password, gh_token, gh_repo)

    try:
        result = pipeline.refresh()
        # Export to GITHUB_ENV for downstream steps
        gh_env = os.environ.get("GITHUB_ENV")
        if gh_env:
            with open(gh_env, "a") as f:
                f.write(f"LEETCODE_SESSION={result['session_token']}\n")
                f.write(f"LEETCODE_CSRF_TOKEN={result['csrf_token']}\n")
            logger.info("Exported fresh tokens to GITHUB_ENV for this run")
        print(f"::notice::Token refresh successful via {result['strategy']} — logged in as {result['username']}")
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        print(f"::error::Token refresh failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
