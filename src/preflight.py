"""Fail-closed LeetCode session and Cloudflare preflight.

This checks the current runner's access before solution lookup or Gemini use.
It does not claim to prove that every write endpoint will accept the session.
"""
import json
import os
import sys
import requests

BASE = "https://leetcode.com"
GRAPHQL = BASE + "/graphql"
PROBLEM_URL = BASE + "/problems/two-sum/"
USER_STATUS_QUERY = "query { userStatus { isSignedIn username } }"
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "attention required",
    "verify you are human",
)


def _is_challenge(response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    body = (response.text or "")[:12000].lower()
    return (
        "text/html" in content_type
        and any(marker in body for marker in CHALLENGE_MARKERS)
    )


def run_preflight(session_token: str, csrf_token: str) -> tuple[bool, str, str]:
    session_token = (session_token or "").strip()
    csrf_token = (csrf_token or "").strip()
    if not session_token or not csrf_token:
        return False, "auth_rejected", "LeetCode cookie pair is missing."

    client = requests.Session()
    client.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
    client.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
    headers = {
        "Origin": BASE,
        "Referer": PROBLEM_URL,
        "X-CSRFToken": csrf_token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        page = client.get(PROBLEM_URL, headers={"Referer": BASE + "/"}, timeout=20)
        if page.status_code in (403, 503) or _is_challenge(page):
            return False, "cloudflare_challenged", (
                "Cloudflare challenged the GitHub Actions runner. "
                "Manual session push required."
            )
        if page.status_code in (401,):
            return False, "auth_rejected", "LeetCode rejected the session cookie."
        if page.status_code >= 500 or page.status_code == 429:
            return False, "infra_inconclusive", (
                f"LeetCode preflight temporarily unavailable (HTTP {page.status_code})."
            )
        if page.status_code != 200:
            return False, "infra_inconclusive", (
                f"LeetCode problem-page preflight returned HTTP {page.status_code}."
            )

        response = client.post(
            GRAPHQL,
            json={"query": USER_STATUS_QUERY},
            headers=headers,
            timeout=20,
        )
        if response.status_code in (403, 503) or _is_challenge(response):
            return False, "cloudflare_challenged", (
                "Cloudflare challenged the GitHub Actions runner. "
                "Manual session push required."
            )
        if response.status_code in (401,):
            return False, "auth_rejected", "LeetCode rejected the session."
        if response.status_code == 429 or response.status_code >= 500:
            return False, "infra_inconclusive", (
                f"LeetCode authentication preflight unavailable (HTTP {response.status_code})."
            )
        if response.status_code != 200:
            return False, "infra_inconclusive", (
                f"LeetCode authentication preflight returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError:
            return False, "cloudflare_challenged", (
                "LeetCode returned a non-JSON response. Manual session push required."
            )
        status = (payload.get("data") or {}).get("userStatus") or {}
        if status.get("isSignedIn") is not True:
            return False, "auth_rejected", "LeetCode reports that the session is signed out."
        username = status.get("username") or "unknown"
        return True, "valid", f"LeetCode preflight passed for {username}."
    except requests.RequestException as exc:
        return False, "infra_inconclusive", (
            f"LeetCode preflight network error: {type(exc).__name__}."
        )
    finally:
        client.close()


def main() -> int:
    from .cookie_bundle import load_cookie_pair
    try:
        session, csrf = load_cookie_pair()
    except ValueError as exc:
        print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
        return 21

    ok, status, message = run_preflight(session, csrf)
    print(f"PRE-FLIGHT {status.upper()}: {message}")
    if ok:
        return 0
    if status == "cloudflare_challenged":
        return 20
    if status == "auth_rejected":
        return 21
    return 22


if __name__ == "__main__":
    sys.exit(main())
