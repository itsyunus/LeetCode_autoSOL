#!/usr/bin/env python3
"""
Axiom Instant Session Refresher & Secret Synchronizer
One-shot CLI to update LeetCode session secrets and verify against GitHub Actions.
"""

import json
import os
import re
import subprocess
import sys
import requests

REPO = os.environ.get("GITHUB_REPOSITORY", "itsyunus/LeetCode_autoSOL")
GH_BIN = "/opt/homebrew/bin/gh" if os.path.exists("/opt/homebrew/bin/gh") else "gh"
LEETCODE_GRAPHQL = "https://leetcode.com/graphql"


def validate_session(session: str, csrf: str) -> tuple[bool, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/",
        "X-CSRFToken": csrf,
    }
    cookies = {"LEETCODE_SESSION": session, "csrftoken": csrf}
    try:
        r = requests.post(
            LEETCODE_GRAPHQL,
            json={"query": "query { userStatus { isSignedIn username activeSessionId } }"},
            headers=headers,
            cookies=cookies,
            timeout=12,
        )
        if r.status_code != 200:
            return False, f"HTTP Error {r.status_code}"
        data = r.json().get("data", {}).get("userStatus", {})
        if data.get("isSignedIn"):
            return True, data.get("username", "Unknown")
        return False, "LeetCode returned isSignedIn = False"
    except Exception as exc:
        return False, str(exc)


def push_secret(name: str, val: str) -> bool:
    cmd = [GH_BIN, "secret", "set", name, "--repo", REPO, "--body", val]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/update_session.py <LEETCODE_SESSION_OR_COOKIE_STRING>")
        print("Example: python3 scripts/update_session.py 'LEETCODE_SESSION=eyJ...; csrftoken=...'")
        sys.exit(1)

    raw_input = " ".join(sys.argv[1:]).strip()

    sess_m = re.search(r"LEETCODE_SESSION=([^\s;]+)", raw_input)
    csrf_m = re.search(r"csrftoken=([^\s;]+)", raw_input)

    session = sess_m.group(1) if sess_m else None
    csrf = csrf_m.group(1) if csrf_m else None

    if not session:
        tokens = raw_input.split()
        for tok in tokens:
            cleaned = tok.strip(";\r\n\t ,\"'")
            if len(cleaned) > 50 and not session:
                session = cleaned
            elif len(cleaned) >= 20 and not csrf:
                csrf = cleaned

    if not session:
        print("❌ Could not extract LEETCODE_SESSION value.")
        sys.exit(1)

    if not csrf:
        csrf = "temp_csrf_token"

    print(f"⏳ Verifying session with LeetCode GraphQL...")
    ok, user = validate_session(session, csrf)
    if not ok:
        print(f"❌ Verification failed: {user}")
        print("Make sure you are logged into leetcode.com and copied a fresh cookie.")
        sys.exit(1)

    print(f"✅ Authenticated as: {user}!")
    print(f"⏳ Pushing secrets to GitHub Actions ({REPO})...")

    bundle = json.dumps({"LEETCODE_SESSION": session, "LEETCODE_CSRF_TOKEN": csrf}, separators=(",", ":"))
    push_secret("LEETCODE_COOKIE_BUNDLE", bundle)
    push_secret("LEETCODE_SESSION", session)
    push_secret("LEETCODE_CSRF_TOKEN", csrf)

    print(f"🚀 Triggering preflight & test run on GitHub Actions...")
    cmd = [GH_BIN, "workflow", "run", "daily_solve.yml", "--repo", REPO, "-f", "dry_run=true"]
    subprocess.run(cmd)

    print(f"\n🎉 Done, boss man! Secrets updated and test solve dispatched.")
    print(f"Check your runs at: https://github.com/{REPO}/actions")


if __name__ == "__main__":
    main()

