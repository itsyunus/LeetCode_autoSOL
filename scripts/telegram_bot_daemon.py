#!/usr/bin/env python3
"""
Axiom Telegram Sentinel Daemon
Listens for user commands and cookie updates directly on Telegram.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("telegram-sentinel")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AUTHORIZED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "1612900553"))
GH_PAT = os.environ.get("GH_PAT", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "itsyunus/LeetCode_autoSOL")
GH_BIN = "/opt/homebrew/bin/gh" if os.path.exists("/opt/homebrew/bin/gh") else "gh"

if not GH_PAT:
    # Read from local git credential store if not in environment
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("password="):
                GH_PAT = line.split("=", 1)[1]
                break
    except Exception:
        pass

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
LEETCODE_GRAPHQL = "https://leetcode.com/graphql"


def send_reply(chat_id: int, text: str):
    """Send HTML reply back to the Telegram user."""
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send reply: {e}")


def validate_leetcode_cookies(session_token: str, csrf_token: str) -> tuple[bool, str]:
    """Test candidate cookies against LeetCode GraphQL API."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/",
        "X-CSRFToken": csrf_token,
    }
    cookies = {"LEETCODE_SESSION": session_token, "csrftoken": csrf_token}

    try:
        resp = requests.post(
            LEETCODE_GRAPHQL,
            json={"query": "query { userStatus { isSignedIn username realName avatar } }"},
            headers=headers,
            cookies=cookies,
            timeout=15,
        )
        if resp.status_code != 200:
            return False, f"LeetCode HTTP {resp.status_code}"
        data = resp.json().get("data", {}).get("userStatus", {})
        if data.get("isSignedIn"):
            username = data.get("username", "Unknown")
            return True, username
        return False, "LeetCode reported isSignedIn = False (Expired or Invalid)"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def push_secret_gh(secret_name: str, secret_value: str) -> bool:
    """Push secret via gh CLI."""
    env = os.environ.copy()
    env["GH_TOKEN"] = GH_PAT
    cmd = [GH_BIN, "secret", "set", secret_name, "--repo", REPO, "--body", secret_value]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"gh secret set {secret_name} failed: {res.stderr}")
        return False
    return True


def trigger_workflow(dry_run: bool = True) -> tuple[bool, str]:
    """Dispatch the daily_solve workflow."""
    env = os.environ.copy()
    env["GH_TOKEN"] = GH_PAT
    dry_str = "true" if dry_run else "false"
    cmd = [GH_BIN, "workflow", "run", "daily_solve.yml", "--repo", REPO, "-f", f"dry_run={dry_str}"]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode == 0:
        return True, "Dispatched successfully"
    return False, res.stderr


def handle_cookie_update(chat_id: int, text: str):
    """Parse cookie text, validate, and update secrets."""
    send_reply(chat_id, "⏳ <i>Axiom inspecting cookies against LeetCode GraphQL...</i>")

    sess_match = re.search(r"LEETCODE_SESSION=([^\s;]+)", text)
    csrf_match = re.search(r"csrftoken=([^\s;]+)", text)

    session = sess_match.group(1) if sess_match else None
    csrf = csrf_match.group(1) if csrf_match else None

    if not session:
        # Fallback: check if user pasted raw session string
        tokens = text.strip().split()
        for tok in tokens:
            cleaned = tok.strip(";\r\n\t ,\"'")
            if len(cleaned) > 50 and not session:
                session = cleaned
            elif len(cleaned) >= 20 and not csrf:
                csrf = cleaned

    if not session:
        send_reply(
            chat_id,
            "❌ <b>Could not find LEETCODE_SESSION.</b>\n\n"
            "Paste your cookie like this:\n"
            "<code>LEETCODE_SESSION=your_token_here; csrftoken=your_csrf_here</code>",
        )
        return

    if not csrf:
        csrf = "temp_csrf_token"

    # Validate against GraphQL
    ok, username = validate_leetcode_cookies(session, csrf)
    if not ok:
        send_reply(
            chat_id,
            f"❌ <b>Validation Rejected by LeetCode:</b>\n<code>{username}</code>\n\n"
            "Make sure you copied a fresh session cookie while logged in.",
        )
        return

    send_reply(chat_id, f"✅ <b>Authenticated as {username}!</b>\n⏳ <i>Pushing secrets to GitHub Actions...</i>")

    # Push to GitHub
    bundle_json = json.dumps({"LEETCODE_SESSION": session, "LEETCODE_CSRF_TOKEN": csrf}, separators=(",", ":"))
    ok_bundle = push_secret_gh("LEETCODE_COOKIE_BUNDLE", bundle_json)
    push_secret_gh("LEETCODE_SESSION", session)
    push_secret_gh("LEETCODE_CSRF_TOKEN", csrf)

    if ok_bundle:
        ok_run, run_msg = trigger_workflow(dry_run=True)
        reply = (
            f"🎉 <b>Success, boss man!</b>\n\n"
            f"• <b>LeetCode User:</b> <code>{username}</code>\n"
            f"• <b>GitHub Secrets:</b> <code>LEETCODE_COOKIE_BUNDLE</code> Updated ✅\n"
            f"• <b>Test Solver:</b> {'🚀 Workflow Queued on GitHub Actions' if ok_run else '⚠️ Trigger error'}\n\n"
            f"<a href=\"https://github.com/{REPO}/actions\">Open GitHub Actions Runs</a>"
        )
        send_reply(chat_id, reply)
    else:
        send_reply(chat_id, "❌ <b>GitHub Error:</b> Failed to update repo secrets. Check PAT permissions.")


def handle_message(chat_id: int, text: str):
    """Route user messages."""
    text_clean = text.strip()

    if text_clean.startswith("/start") or text_clean.startswith("/help"):
        msg = (
            "⚡ <b>Axiom LeetCode Bot Sentinel</b>\n\n"
            "Hey boss man! I watch your LeetCode solver and manage credentials right from Telegram.\n\n"
            "<b>Commands:</b>\n"
            "• <code>/test</code> — Fire a test run of the daily solver on GitHub\n"
            "• <code>/status</code> — Check if your repo & LeetCode session are alive\n\n"
            "<b>Renew Session Anytime:</b>\n"
            "Paste your cookie string right here into chat:\n"
            "<code>LEETCODE_SESSION=...; csrftoken=...</code>\n\n"
            "I'll verify it with LeetCode GraphQL and push it to GitHub Secrets automatically."
        )
        send_reply(chat_id, msg)
        return

    if text_clean.startswith("/status"):
        send_reply(chat_id, "🔎 <i>Checking GitHub Actions status...</i>")
        env = os.environ.copy()
        env["GH_TOKEN"] = GH_PAT
        res = subprocess.run(
            [GH_BIN, "run", "list", "--repo", REPO, "--limit", "1", "--json", "status,conclusion,number,headSha"],
            env=env,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)[0]
            num = data.get("number")
            status = data.get("status")
            conclusion = data.get("conclusion")
            send_reply(
                chat_id,
                f"📊 <b>Repo Status:</b> <code>{REPO}</code>\n\n"
                f"• <b>Latest Run:</b> #{num}\n"
                f"• <b>Status:</b> {status}\n"
                f"• <b>Conclusion:</b> {'✅ ' + conclusion if conclusion == 'success' else conclusion}\n"
                f"• <b>Auto-Schedule:</b> Daily at 00:30 UTC (06:00 IST)",
            )
        else:
            send_reply(chat_id, "❌ Could not fetch GitHub Actions status.")
        return

    if text_clean.startswith("/test") or text_clean.startswith("/run"):
        send_reply(chat_id, "🚀 <i>Dispatching test solver run on GitHub Actions...</i>")
        ok, msg = trigger_workflow(dry_run=True)
        if ok:
            send_reply(
                chat_id,
                f"✅ <b>Test Run Queued!</b>\n\n"
                f"Dry run started on GitHub Actions. It will generate today's solution and dashboard without submitting.\n\n"
                f"<a href=\"https://github.com/{REPO}/actions\">Watch Live Run</a>",
            )
        else:
            send_reply(chat_id, f"❌ Failed to dispatch workflow: {msg}")
        return

    # Check if user sent cookies
    if "LEETCODE_SESSION" in text or len(text.strip().split()) >= 1 and len(text.strip()) > 50:
        handle_cookie_update(chat_id, text)
        return

    send_reply(
        chat_id,
        "🤖 <i>Unrecognized command.</i>\n\n"
        "Try <code>/status</code>, <code>/test</code>, or paste your <code>LEETCODE_SESSION</code> cookie string here to update.",
    )


def main():
    logger.info("⚡ Starting Axiom Telegram Sentinel Polling Loop...")
    offset = None

    while True:
        try:
            url = f"{BASE_URL}/getUpdates?timeout=25" + (f"&offset={offset}" if offset else "")
            resp = requests.get(url, timeout=30).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                if not chat_id or not text:
                    continue

                if chat_id != AUTHORIZED_CHAT_ID:
                    logger.warning(f"Unauthorized chat_id {chat_id} ignored.")
                    continue

                logger.info(f"Received message from {chat_id}: {text[:30]}...")
                handle_message(chat_id, text)

        except Exception as exc:
            logger.error(f"Polling loop error: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    main()
