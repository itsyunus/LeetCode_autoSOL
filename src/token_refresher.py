"""
Automatic LeetCode Session Refresher
Logs into LeetCode using username/password, extracts fresh session
cookies, and updates GitHub Secrets automatically via the GitHub API.

Two login strategies:
  1. Direct API login (fast, no browser needed)
  2. Playwright headless browser (fallback if API login gets blocked)

This runs as a GitHub Actions job BEFORE the solver, ensuring
tokens are always fresh. No manual cookie copying ever again.
"""

import os
import sys
import json
import time
import logging
import base64
import requests
from typing import Optional, Tuple, Dict
from nacl import encoding, public  # PyNaCl for GitHub secret encryption

logger = logging.getLogger(__name__)


class LeetCodeAuthenticator:
    """Handles LeetCode login and cookie extraction."""

    LOGIN_URL = "https://leetcode.com/accounts/login/"
    GRAPHQL_URL = "https://leetcode.com/graphql"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://leetcode.com",
            "Origin": "https://leetcode.com",
        })

    def login_via_api(self) -> Tuple[str, str]:
        """
        Strategy 1: Direct API login.
        POST credentials to LeetCode's login endpoint, extract cookies.
        """
        logger.info("Attempting direct API login...")

        # Step 1: GET the login page to grab initial CSRF token
        resp = self.session.get(self.LOGIN_URL, timeout=30)
        resp.raise_for_status()

        csrf_token = self.session.cookies.get("csrftoken", "")
        if not csrf_token:
            # Try to extract from page
            import re
            match = re.search(r"csrfmiddlewaretoken.*?value=['\"](.+?)['\"]", resp.text)
            if match:
                csrf_token = match.group(1)

        if not csrf_token:
            raise RuntimeError("Could not obtain initial CSRF token")

        # Step 2: POST login credentials
        self.session.headers.update({"x-csrftoken": csrf_token})
        login_data = {
            "login": self.username,
            "password": self.password,
            "csrfmiddlewaretoken": csrf_token,
        }

        resp = self.session.post(
            self.LOGIN_URL,
            data=login_data,
            timeout=30,
            allow_redirects=True,
        )

        # Step 3: Extract session cookies
        session_token = self.session.cookies.get("LEETCODE_SESSION", domain=".leetcode.com")
        new_csrf = self.session.cookies.get("csrftoken", domain=".leetcode.com")

        if not session_token:
            # Try without domain filter
            session_token = self.session.cookies.get("LEETCODE_SESSION")
            new_csrf = self.session.cookies.get("csrftoken")

        if not session_token:
            raise RuntimeError(
                f"Login failed — no session token received. "
                f"Status: {resp.status_code}, URL: {resp.url}"
            )

        logger.info("✅ API login successful!")
        return session_token, new_csrf or csrf_token

    def login_via_browser(self) -> Tuple[str, str]:
        """
        Strategy 2: Headless browser login using Playwright.
        More robust — handles JS challenges, CAPTCHAs, CloudFlare, etc.
        """
        logger.info("Attempting headless browser login...")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )

            page = context.new_page()

            # Navigate to login page
            page.goto("https://leetcode.com/accounts/login/", wait_until="networkidle")
            time.sleep(2)

            # Fill in credentials
            # LeetCode's login form uses id="id_login" and id="id_password"
            username_selectors = [
                'input[name="login"]',
                '#id_login',
                'input[type="text"]',
                'input[autocomplete="username"]',
            ]
            password_selectors = [
                'input[name="password"]',
                '#id_password',
                'input[type="password"]',
            ]

            username_filled = False
            for selector in username_selectors:
                try:
                    el = page.wait_for_selector(selector, timeout=5000)
                    if el:
                        el.fill(self.username)
                        username_filled = True
                        break
                except Exception:
                    continue

            if not username_filled:
                raise RuntimeError("Could not find username input field")

            password_filled = False
            for selector in password_selectors:
                try:
                    el = page.wait_for_selector(selector, timeout=5000)
                    if el:
                        el.fill(self.password)
                        password_filled = True
                        break
                except Exception:
                    continue

            if not password_filled:
                raise RuntimeError("Could not find password input field")

            # Click sign in button
            submit_selectors = [
                'button[type="submit"]',
                '#signin_btn',
                'button:has-text("Sign In")',
                'input[type="submit"]',
            ]

            submitted = False
            for selector in submit_selectors:
                try:
                    btn = page.wait_for_selector(selector, timeout=3000)
                    if btn:
                        btn.click()
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                # Try pressing Enter as fallback
                page.keyboard.press("Enter")

            # Wait for navigation after login
            try:
                page.wait_for_url("**/", timeout=15000)
            except Exception:
                pass

            time.sleep(3)

            # Extract cookies
            cookies = context.cookies("https://leetcode.com")
            session_token = None
            csrf_token = None

            for cookie in cookies:
                if cookie["name"] == "LEETCODE_SESSION":
                    session_token = cookie["value"]
                elif cookie["name"] == "csrftoken":
                    csrf_token = cookie["value"]

            browser.close()

            if not session_token:
                raise RuntimeError("Browser login failed — no session token in cookies")

            logger.info("✅ Browser login successful!")
            return session_token, csrf_token or ""

    def login(self) -> Tuple[str, str]:
        """
        Try all login strategies in order.
        Returns (LEETCODE_SESSION, csrftoken).
        """
        strategies = [
            ("API Login", self.login_via_api),
            ("Browser Login", self.login_via_browser),
        ]

        last_error = None
        for name, strategy in strategies:
            try:
                logger.info(f"━━━ Trying: {name} ━━━")
                session_token, csrf_token = strategy()
                self._validate_session(session_token, csrf_token)
                return session_token, csrf_token
            except Exception as e:
                logger.warning(f"{name} failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All login strategies failed. Last error: {last_error}")

    def _validate_session(self, session_token: str, csrf_token: str):
        """Verify the tokens actually work by hitting the GraphQL API."""
        logger.info("Validating session tokens...")

        session = requests.Session()
        session.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
        session.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
        session.headers.update({
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com",
            "x-csrftoken": csrf_token,
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
            self.GRAPHQL_URL,
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


class GitHubSecretsUpdater:
    """Updates GitHub repository secrets via the GitHub API."""

    API_BASE = "https://api.github.com"

    def __init__(self, token: str, repo: str):
        """
        Args:
            token: GitHub Personal Access Token with `repo` scope
            repo: Full repo name like "YunuZCodes/leetcode-auto-solver"
        """
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get_public_key(self) -> Tuple[str, str]:
        """Fetch the repo's public key for encrypting secrets."""
        url = f"{self.API_BASE}/repos/{self.repo}/actions/secrets/public-key"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data["key"], data["key_id"]

    def _encrypt_secret(self, public_key: str, secret_value: str) -> str:
        """Encrypt a secret value using the repo's public key (libsodium sealed box)."""
        pk = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        sealed_box = public.SealedBox(pk)
        encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")

    def update_secret(self, secret_name: str, secret_value: str):
        """Create or update a GitHub Actions secret."""
        pub_key, key_id = self._get_public_key()
        encrypted_value = self._encrypt_secret(pub_key, secret_value)

        url = f"{self.API_BASE}/repos/{self.repo}/actions/secrets/{secret_name}"
        payload = {
            "encrypted_value": encrypted_value,
            "key_id": key_id,
        }

        resp = requests.put(url, headers=self.headers, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info(f"✅ Updated GitHub secret: {secret_name}")

    def update_leetcode_tokens(self, session_token: str, csrf_token: str):
        """Update both LeetCode secrets in one call."""
        self.update_secret("LEETCODE_SESSION", session_token)
        self.update_secret("LEETCODE_CSRF_TOKEN", csrf_token)
        logger.info("✅ Both LeetCode secrets updated in GitHub!")


class TokenRefreshPipeline:
    """
    Full pipeline: Login to LeetCode → Get fresh tokens → Update GitHub Secrets.
    Runs before the solver to ensure tokens are always valid.
    """

    def __init__(
        self,
        leetcode_username: str,
        leetcode_password: str,
        github_token: str,
        github_repo: str,
    ):
        self.auth = LeetCodeAuthenticator(leetcode_username, leetcode_password)
        self.github = GitHubSecretsUpdater(github_token, github_repo)

    def refresh(self) -> Dict[str, str]:
        """Execute the full token refresh pipeline."""
        logger.info("=" * 60)
        logger.info("🔄 LeetCode Token Auto-Refresh Pipeline")
        logger.info("=" * 60)

        # Step 1: Login and get fresh tokens
        session_token, csrf_token = self.auth.login()

        # Step 2: Update GitHub Secrets
        self.github.update_leetcode_tokens(session_token, csrf_token)

        logger.info("=" * 60)
        logger.info("✅ TOKEN REFRESH COMPLETE")
        logger.info("=" * 60)

        return {
            "session_token": session_token,
            "csrf_token": csrf_token,
        }


def main():
    """Entry point — reads config from environment variables."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    username = os.environ.get("LEETCODE_USERNAME")
    password = os.environ.get("LEETCODE_PASSWORD")
    gh_token = os.environ.get("GH_PAT")  # Personal Access Token
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")  # Auto-set by GitHub Actions

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
        # Also export to env for the current workflow run
        gh_env = os.environ.get("GITHUB_ENV")
        if gh_env:
            with open(gh_env, "a") as f:
                f.write(f"LEETCODE_SESSION={result['session_token']}\n")
                f.write(f"LEETCODE_CSRF_TOKEN={result['csrf_token']}\n")
            logger.info("Exported fresh tokens to GITHUB_ENV for this run")
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

