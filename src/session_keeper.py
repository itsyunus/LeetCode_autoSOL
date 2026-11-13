"""
LeetCode Session Health Check & Cookie-Rotation Capture
══════════════════════════════════════════════════════
Runs entirely on GitHub Actions — NO local machine needed.

Strategy:
  1. Check LeetCode's authenticated userStatus endpoint with current cookies
  2. Capture Set-Cookie headers if LeetCode happens to rotate cookies
  3. Persist detected cookie changes to GitHub Secrets

This hourly check detects authentication loss sooner; it cannot force
LeetCode to extend a server-side session or prevent revocation. Cookie
rotation is opportunistic and is not guaranteed. If authentication expires,
normal interactive login may be required.
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
from .cookie_bundle import load_cookie_pair, serialize_cookie_pair
from .preflight import run_preflight

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
    Checks LeetCode authentication and captures rotated cookies when returned.

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
        self.original_session = (session_token or "").strip()
        self.original_csrf = (csrf_token or "").strip()
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
            logger.info("  📦 [%s] Set-Cookie header detected (cookie values redacted).", endpoint)

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
        """Verify authentication first; distinguish expiry from transient API failure."""
        logger.info("Starting LeetCode session probe")
        last_error = None
        for attempt in range(3):
            try:
                resp = self.http.post(
                    LEETCODE_GRAPHQL,
                    json={"query": QUERY_USER_STATUS},
                    timeout=20,
                )
                self._extract_cookies_from_response(resp, "user_status")
                resp.raise_for_status()
                data = resp.json()
                if data.get("errors"):
                    raise RuntimeError(f"LeetCode userStatus GraphQL error: {data['errors']}")
                user_status = data.get("data", {}).get("userStatus")
                if not isinstance(user_status, dict) or "isSignedIn" not in user_status:
                    raise RuntimeError("LeetCode returned no usable userStatus; authentication could not be verified.")
                if not user_status.get("isSignedIn"):
                    logger.error("LeetCode explicitly reports isSignedIn=False.")
                    return False
                self.username = user_status.get("username") or "unknown"
                logger.info("Session valid for user: %s", self.username)
                break
            except Exception as exc:
                last_error = exc
                logger.warning("Authentication probe %s/3 failed: %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(
                "Could not verify LeetCode authentication after 3 attempts. "
                "This may be a network, rate-limit, or security-challenge issue; "
                "the session is not being labelled expired."
            ) from last_error

        # Additional authenticated requests may return rotated cookies.
        # They are non-critical once userStatus has confirmed the login.
        probes = [
            ("daily_challenge", QUERY_DAILY_CHALLENGE, None),
            ("user_progress", QUERY_USER_PROGRESS, {"userSlug": self.username}),
            ("recent_submissions", QUERY_RECENT_SUBMISSIONS, {"username": self.username, "limit": 5}),
        ]
        for name, query, variables in probes:
            try:
                payload = {"query": query}
                if variables:
                    payload["variables"] = variables
                resp = self.http.post(LEETCODE_GRAPHQL, json=payload, timeout=20)
                self._extract_cookies_from_response(resp, name)
                resp.raise_for_status()
                data = resp.json()
                if data.get("errors"):
                    logger.warning("GraphQL warning on %s: %s", name, data["errors"])
            except Exception as exc:
                logger.warning("Non-critical probe %s failed: %s", name, exc)
            time.sleep(1)
        return True

    def push_refreshed_cookies(self) -> Dict[str, bool]:
        """Verify a complete candidate pair, then write it as one atomic bundle secret.

        GitHub Actions secret values are write-only through the REST API. A
        multi-secret rollback cannot reliably recover old values. The canonical
        bundle therefore stores both cookies in one secret and requires one PUT.
        """
        if not self.new_session and not self.new_csrf:
            logger.info("No cookie rotation detected; GitHub Secrets remain unchanged.")
            return {}

        if not self.gh_manager:
            raise RuntimeError(
                "LeetCode returned refreshed cookies, but GH_PAT is missing. "
                "Cannot persist the candidate cookie bundle."
            )

        candidate_session = (self.new_session or self.original_session or "").strip()
        candidate_csrf = (self.new_csrf or self.original_csrf or "").strip()
        bundle = serialize_cookie_pair(candidate_session, candidate_csrf)

        # Verify the complete candidate pair in a fresh client before writing.
        ok, status, reason = run_preflight(candidate_session, candidate_csrf)
        if not ok:
            logger.error(
                "Rejected candidate cookie bundle; existing GitHub secret was not changed (%s): %s",
                status, reason,
            )
            raise RuntimeError("Candidate cookie bundle verification failed: " + reason)

        if candidate_session == self.original_session and candidate_csrf == self.original_csrf:
            logger.info("Candidate pair is unchanged; no GitHub secret update is needed.")
            return {}

        if not self.gh_manager.update_secret("LEETCODE_COOKIE_BUNDLE", bundle):
            raise RuntimeError(
                "Failed to update LEETCODE_COOKIE_BUNDLE. The previous bundle remains the canonical credential."
            )

        logger.info("Verified LEETCODE_COOKIE_BUNDLE updated with one GitHub Secrets write.")
        self.http.cookies.set("LEETCODE_SESSION", candidate_session, domain=".leetcode.com")
        self.http.cookies.set("csrftoken", candidate_csrf, domain=".leetcode.com")
        self.http.headers["x-csrftoken"] = candidate_csrf
        return {"LEETCODE_COOKIE_BUNDLE": True}

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
    try:
        session_tok, csrf_tok = load_cookie_pair()
    except ValueError as exc:
        logger.warning("Cookie refresh skipped: %s", exc)
        return
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
    try:
        session_tok, csrf_tok = load_cookie_pair()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
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

