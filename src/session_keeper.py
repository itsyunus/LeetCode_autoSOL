"""
LeetCode Session Keep-Alive & Auto-Refresh Engine
══════════════════════════════════════════════════════
Runs entirely on GitHub Actions — NO local machine needed.

Strategy:
  1. Hit LeetCode's GraphQL API with current session cookies
  2. Capture any Set-Cookie headers (LeetCode rotates cookies on active use)
  3. If new cookies detected, push them to GitHub Secrets automatically
  4. Run every 6 hours to ensure session never expires from inactivity

The key insight: LeetCode sessions die from INACTIVITY. If we ping
the API periodically, the session stays alive. Many sites also send
refreshed cookies (extended expiry) in response Set-Cookie headers —
we capture those and auto-update secrets so the session effectively
lives forever.

Zero CAPTCHA. Zero login. Zero local dependency. Pure server-side.
"""

import os
import sys
import json
import time
import logging
import hashlib
import requests
from typing import Optional, Tuple, Dict, Any
from base64 import b64encode
from datetime import datetime, timezone

try:
    from nacl import encoding, public
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── LeetCode API Endpoints ────────────────────────────────────────
LEETCODE_GRAPHQL  = "https://leetcode.com/graphql"
LEETCODE_BASE     = "https://leetcode.com"
GITHUB_API        = "https://api.github.com"

# ─── Lightweight GraphQL queries for session probing ───────────────
QUERY_USER_STATUS = """
query {
    userStatus {
        isSignedIn
        username
        realName
        avatar
        activeSessionId
    }
}
"""

QUERY_DAILY_CHALLENGE = """
query questionOfToday {
    activeDailyCodingChallengeQuestion {
        date
        link
        question {
            questionId
            title
            difficulty
            acRate
        }
    }
}
"""

QUERY_USER_PROGRESS = """
query userProfileUserQuestionProgressV2($userSlug: String!) {
    userProfileUserQuestionProgressV2(userSlug: $userSlug) {
        numAcceptedQuestions { count difficulty }
        numFailedQuestions { count difficulty }
        numUntouchedQuestions { count difficulty }
    }
}
"""

QUERY_RECENT_SUBMISSIONS = """
query recentAcSubmissions($username: String!, $limit: Int!) {
    recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
    }
}
"""

# ─── Multiple probing endpoints to maximize Set-Cookie chances ─────
PROBE_ENDPOINTS = [
    # (name, query, variables_factory)
    ("user_status",       QUERY_USER_STATUS,          lambda u: None),
    ("daily_challenge",   QUERY_DAILY_CHALLENGE,      lambda u: None),
    ("user_progress",     QUERY_USER_PROGRESS,        lambda u: {"userSlug": u}),
    ("recent_submissions",QUERY_RECENT_SUBMISSIONS,   lambda u: {"username": u, "limit": 5}),
]


class GitHubSecretsManager:
    """Handles encrypted GitHub Secrets updates via the REST API."""

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._public_key: Optional[Dict[str, str]] = None

    def _get_public_key(self) -> Dict[str, str]:
        """Fetch the repo's public key for secret encryption."""
        if self._public_key:
            return self._public_key
        url = f"{GITHUB_API}/repos/{self.repo}/actions/secrets/public-key"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        self._public_key = resp.json()
        return self._public_key

    def _encrypt_secret(self, value: str) -> str:
        """Encrypt a secret value using the repo's public key (libsodium sealed box)."""
        if not NACL_AVAILABLE:
            raise RuntimeError("PyNaCl is required for secret encryption. pip install pynacl")
        pk_data = self._get_public_key()
        public_key = public.PublicKey(
            pk_data["key"].encode("utf-8"),
            encoding.Base64Encoder,
        )
        sealed = public.SealedBox(public_key).encrypt(value.encode("utf-8"))
        return b64encode(sealed).decode("utf-8")

    def update_secret(self, name: str, value: str) -> bool:
        """Create or update a repository secret."""
        try:
            pk_data = self._get_public_key()
            encrypted = self._encrypt_secret(value)
            url = f"{GITHUB_API}/repos/{self.repo}/actions/secrets/{name}"
            payload = {
                "encrypted_value": encrypted,
                "key_id": pk_data["key_id"],
            }
            resp = requests.put(url, headers=self.headers, json=payload, timeout=15)
            if resp.status_code in (201, 204):
                logger.info(f"✅ Secret '{name}' updated successfully")
                return True
            else:
                logger.error(f"❌ Failed to update secret '{name}': HTTP {resp.status_code} — {resp.text}")
                return False
        except Exception as exc:
            logger.error(f"❌ Secret update error for '{name}': {exc}")
            return False


class SessionKeeper:
    """
    Keeps LeetCode session alive and captures rotated cookies.

    The core loop:
      1. Build a requests.Session with current cookies
      2. Hit multiple LeetCode GraphQL endpoints
      3. Inspect ALL response Set-Cookie headers for refreshed tokens
      4. If new cookies found → push to GitHub Secrets
      5. If session is dead → exit with error (triggers alert workflow)
    """

    def __init__(
        self,
        session_token: str,
        csrf_token: str,
        gh_token: Optional[str] = None,
        gh_repo: Optional[str] = None,
    ):
        self.original_session = session_token
        self.original_csrf = csrf_token
        self.gh_manager = GitHubSecretsManager(gh_token, gh_repo) if gh_token and gh_repo else None

        # Build the HTTP session
        self.http = requests.Session()
        self.http.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
        self.http.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
        self.http.headers.update({
            "Content-Type": "application/json",
            "Referer": LEETCODE_BASE,
            "Origin": LEETCODE_BASE,
            "x-csrftoken": csrf_token,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        })

        self.username: Optional[str] = None
        self.new_session: Optional[str] = None
        self.new_csrf: Optional[str] = None

    def _extract_cookies_from_response(self, resp: requests.Response, endpoint: str) -> None:
        """
        Extract Set-Cookie headers and cookie jar updates from a response.
        LeetCode may rotate session/csrf tokens on any API hit.
        """
        # Method 1: Check Set-Cookie headers directly
        set_cookies = resp.headers.get("Set-Cookie", "")
        if set_cookies:
            logger.info(f"  📦 [{endpoint}] Set-Cookie header detected: {set_cookies[:120]}...")

        # Method 2: Check the session cookie jar (requests auto-updates it)
        for cookie in self.http.cookies:
            if cookie.name == "LEETCODE_SESSION" and cookie.value != self.original_session:
                logger.info(f"  🔄 [{endpoint}] NEW LEETCODE_SESSION detected! (hash: {hashlib.sha256(cookie.value.encode()).hexdigest()[:12]})")
                self.new_session = cookie.value

            if cookie.name == "csrftoken" and cookie.value != self.original_csrf:
                logger.info(f"  🔄 [{endpoint}] NEW csrftoken detected! (hash: {hashlib.sha256(cookie.value.encode()).hexdigest()[:12]})")
                self.new_csrf = cookie.value

        # Method 3: Parse raw Set-Cookie for cookies that requests might miss
        raw_headers = resp.raw.headers if hasattr(resp, 'raw') and resp.raw else {}
        if hasattr(raw_headers, 'getlist'):
            for sc in raw_headers.getlist("Set-Cookie"):
                if "LEETCODE_SESSION=" in sc:
                    val = sc.split("LEETCODE_SESSION=")[1].split(";")[0]
                    if val and val != self.original_session:
                        logger.info(f"  🔄 [{endpoint}] NEW LEETCODE_SESSION from raw header!")
                        self.new_session = val
                if "csrftoken=" in sc:
                    val = sc.split("csrftoken=")[1].split(";")[0]
                    if val and val != self.original_csrf:
                        logger.info(f"  🔄 [{endpoint}] NEW csrftoken from raw header!")
                        self.new_csrf = val

    def probe_session(self) -> bool:
        """
        Hit multiple LeetCode endpoints to:
          a) Verify the session is still valid
          b) Capture any rotated cookies
          c) Keep the session alive through activity

        Returns True if session is valid, False if expired.
        """
        logger.info("═" * 60)
        logger.info("🫀 LeetCode Session Keep-Alive — Starting probe cycle")
        logger.info("═" * 60)

        session_valid = False

        for name, query, var_factory in PROBE_ENDPOINTS:
            logger.info(f"\n── Probing: {name} ──")

            variables = None
            if self.username and name in ("user_progress", "recent_submissions"):
                variables = var_factory(self.username)
            elif name in ("user_progress", "recent_submissions"):
                # Skip user-specific queries until we know the username
                if not self.username:
                    logger.info(f"  ⏭️  Skipping {name} (username not yet known)")
                    continue
                variables = var_factory(self.username)

            payload = {"query": query}
            if variables:
                payload["variables"] = variables

            try:
                resp = self.http.post(
                    LEETCODE_GRAPHQL,
                    json=payload,
                    timeout=20,
                )

                # Always extract cookies, even on error responses
                self._extract_cookies_from_response(resp, name)

                if resp.status_code == 200:
                    data = resp.json()

                    if name == "user_status":
                        user_status = data.get("data", {}).get("userStatus", {})
                        if user_status.get("isSignedIn"):
                            self.username = user_status.get("username", "unknown")
                            session_id = user_status.get("activeSessionId", "N/A")
                            logger.info(f"  ✅ Session VALID — User: {self.username} | Session ID: {session_id}")
                            session_valid = True
                        else:
                            logger.warning(f"  ❌ Session EXPIRED — isSignedIn=False")
                            return False

                    elif name == "daily_challenge":
                        q = data.get("data", {}).get("activeDailyCodingChallengeQuestion", {})
                        if q:
                            question = q.get("question", {})
                            logger.info(
                                f"  📋 Daily: #{question.get('questionId')} "
                                f"{question.get('title')} [{question.get('difficulty')}] "
                                f"({q.get('date')})"
                            )

                    elif name == "user_progress":
                        progress = data.get("data", {}).get("userProfileUserQuestionProgressV2", {})
                        if progress:
                            accepted = progress.get("numAcceptedQuestions", [])
                            total = sum(item.get("count", 0) for item in accepted)
                            logger.info(f"  📊 Total accepted: {total}")

                    elif name == "recent_submissions":
                        subs = data.get("data", {}).get("recentAcSubmissionList", [])
                        if subs:
                            latest = subs[0]
                            ts = datetime.fromtimestamp(int(latest["timestamp"]), tz=timezone.utc)
                            logger.info(f"  📝 Latest AC: {latest['title']} ({ts.strftime('%Y-%m-%d %H:%M UTC')})")

                else:
                    logger.warning(f"  ⚠️  HTTP {resp.status_code} on {name}")

                # Small delay between probes to look natural
                time.sleep(1.5)

            except requests.exceptions.Timeout:
                logger.warning(f"  ⏱️  Timeout on {name}")
            except Exception as exc:
                logger.error(f"  💥 Error on {name}: {exc}")

        return session_valid

    def push_refreshed_cookies(self) -> Dict[str, bool]:
        """Push any newly detected cookies to GitHub Secrets."""
        results = {}

        if not self.gh_manager:
            logger.warning("⚠️  No GitHub credentials — cannot push refreshed cookies")
            return results

        if not self.new_session and not self.new_csrf:
            logger.info("ℹ️  No cookie rotation detected — secrets unchanged")
            return results

        logger.info("\n🔐 Pushing refreshed cookies to GitHub Secrets...")

        if self.new_session:
            results["LEETCODE_SESSION"] = self.gh_manager.update_secret(
                "LEETCODE_SESSION", self.new_session
            )

        if self.new_csrf:
            results["LEETCODE_CSRF_TOKEN"] = self.gh_manager.update_secret(
                "LEETCODE_CSRF_TOKEN", self.new_csrf
            )

            # Also update x-csrftoken header for subsequent requests
            self.http.headers["x-csrftoken"] = self.new_csrf

        return results

    def run(self) -> int:
        """
        Full keep-alive cycle:
          1. Probe session with multiple endpoints
          2. Push any rotated cookies to GitHub
          3. Return exit code (0 = healthy, 1 = expired, 2 = error)
        """
        try:
            is_valid = self.probe_session()

            if not is_valid:
                logger.error("\n" + "═" * 60)
                logger.error("💀 SESSION IS DEAD — Manual cookie refresh required")
                logger.error("═" * 60)
                return 1

            # Push any rotated cookies
            push_results = self.push_refreshed_cookies()

            # Summary
            logger.info("\n" + "═" * 60)
            logger.info("🫀 Session Keep-Alive — COMPLETE")
            logger.info(f"   User: {self.username}")
            logger.info(f"   Session: ✅ ALIVE")
            logger.info(f"   Cookie rotation: {'🔄 YES — secrets updated' if push_results else '⏸️  No rotation detected'}")
            if push_results:
                for name, success in push_results.items():
                    logger.info(f"   → {name}: {'✅' if success else '❌'}")
            logger.info("═" * 60)

            return 0

        except Exception as exc:
            logger.error(f"\n💥 Unexpected error in keep-alive cycle: {exc}")
            import traceback
            traceback.print_exc()
            return 2


# ─── Also integrate with the daily solver ──────────────────────────
def post_solve_cookie_refresh() -> None:
    """
    Call this AFTER the daily solver runs.
    Checks if the solver's API calls triggered any cookie rotation,
    and pushes refreshed cookies to GitHub Secrets.
    
    This is the "passive refresh" strategy — every time the solver
    uses the API, there's a chance LeetCode sends back fresh cookies.
    """
    session_tok = os.environ.get("LEETCODE_SESSION", "")
    csrf_tok = os.environ.get("LEETCODE_CSRF_TOKEN", "")
    gh_token = os.environ.get("GH_PAT", "")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")

    if not all([session_tok, csrf_tok, gh_token, gh_repo]):
        return

    keeper = SessionKeeper(session_tok, csrf_tok, gh_token, gh_repo)
    # Quick single probe — just user_status
    keeper.probe_session()
    keeper.push_refreshed_cookies()


# ─── CLI Entry Point ───────────────────────────────────────────────
def main() -> int:
    session_tok = os.environ.get("LEETCODE_SESSION", "")
    csrf_tok = os.environ.get("LEETCODE_CSRF_TOKEN", "")
    gh_token = os.environ.get("GH_PAT", "")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")

    if not session_tok or not csrf_tok:
        logger.error("❌ LEETCODE_SESSION and LEETCODE_CSRF_TOKEN environment variables required")
        return 1

    keeper = SessionKeeper(
        session_token=session_tok,
        csrf_token=csrf_tok,
        gh_token=gh_token if gh_token else None,
        gh_repo=gh_repo if gh_repo else None,
    )

    return keeper.run()


if __name__ == "__main__":
    sys.exit(main())

