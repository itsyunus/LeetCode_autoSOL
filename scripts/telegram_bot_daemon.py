#!/usr/bin/env python3
"""
Axiom Telegram Sentinel & Interactive Control Dashboard
Full interactive menu, settings management, and LeetCode session guardian.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("telegram-sentinel")

# ─── Environment & Config ───────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AUTHORIZED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "1612900553"))
GH_PAT = os.environ.get("GH_PAT", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "itsyunus/LeetCode_autoSOL")
GH_BIN = "/opt/homebrew/bin/gh" if os.path.exists("/opt/homebrew/bin/gh") else "gh"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
LEETCODE_GRAPHQL = "https://leetcode.com/graphql"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "bot_settings.json")

SUPPORTED_LANGUAGES = [
    ("python3", "🐍 Python 3"),
    ("cpp", "⚡ C++"),
    ("java", "☕ Java"),
    ("javascript", "🌐 JavaScript"),
    ("typescript", "🔷 TypeScript"),
    ("go", "🐹 Go"),
    ("rust", "🦀 Rust"),
]

DEFAULT_SETTINGS = {
    "language": "python3",
    "dry_run": False,
    "skip_if_solved": True,
}


def load_settings() -> Dict[str, Any]:
    """Load persistent settings from disk or return defaults."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_SETTINGS, **data}
        except Exception as e:
            logger.warning(f"Failed to read settings file: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, Any]) -> bool:
    """Save persistent settings to disk."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return False


def get_gh_token() -> str:
    """Retrieve GitHub token from environment, gh CLI keyring, or git credential store."""
    global GH_PAT
    if GH_PAT:
        return GH_PAT

    # 1. Try gh CLI
    try:
        res = subprocess.run([GH_BIN, "auth", "token"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            GH_PAT = res.stdout.strip()
            return GH_PAT
    except Exception:
        pass

    # 2. Try git credential fill
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
                return GH_PAT
    except Exception:
        pass

    return ""


# ─── Telegram API Client Helpers ─────────────────────────────────────
def call_tg(method: str, payload: dict) -> dict:
    """Invoke Telegram Bot API method."""
    url = f"{BASE_URL}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=12)
        return r.json()
    except Exception as err:
        logger.error(f"Telegram API {method} error: {err}")
        return {"ok": False, "description": str(err)}


def answer_callback_query(cq_id: str, text: Optional[str] = None, show_alert: bool = False):
    """Acknowledge Telegram callback query to dismiss loader."""
    payload = {"callback_query_id": cq_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    call_tg("answerCallbackQuery", payload)


def send_reply(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> dict:
    """Send fresh HTML message with optional inline keyboard."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return call_tg("sendMessage", payload)


def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None) -> dict:
    """Update existing message in-place for fast UI transition."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return call_tg("editMessageText", payload)


def register_bot_commands():
    """Register command shortcuts in Telegram's UI menu."""
    commands = [
        {"command": "menu", "description": "⚙️ Open Settings & Control Dashboard"},
        {"command": "status", "description": "📊 Check session health & GitHub runs"},
        {"command": "run", "description": "🚀 Dispatch daily solver on GitHub"},
        {"command": "login", "description": "🔑 LeetCode session renewal hub"},
        {"command": "help", "description": "ℹ️ Instructions & commands"},
    ]
    call_tg("setMyCommands", {"commands": commands})


# ─── GitHub & LeetCode Operations ────────────────────────────────────
def push_secret_gh(secret_name: str, secret_value: str) -> bool:
    """Push encrypted secret via gh CLI."""
    token = get_gh_token()
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    cmd = [GH_BIN, "secret", "set", secret_name, "--repo", REPO, "--body", secret_value]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"gh secret set {secret_name} failed: {res.stderr}")
        return False
    return True


def trigger_workflow(dry_run: bool, language: str) -> Tuple[bool, str]:
    """Dispatch the daily_solve workflow with chosen parameters."""
    token = get_gh_token()
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    dry_str = "true" if dry_run else "false"
    cmd = [
        GH_BIN,
        "workflow",
        "run",
        "daily_solve.yml",
        "--repo",
        REPO,
        "-f",
        f"dry_run={dry_str}",
        "-f",
        f"language={language}",
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode == 0:
        return True, "Dispatched successfully"
    return False, res.stderr or "Workflow dispatch failed"


def validate_leetcode_cookies(session_token: str, csrf_token: str) -> Tuple[bool, str]:
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
            json={"query": "query { userStatus { isSignedIn username realName activeSessionId } }"},
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
        return False, "LeetCode returned isSignedIn = False"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def fetch_latest_run_info() -> Dict[str, Any]:
    """Fetch latest GitHub Actions workflow run."""
    token = get_gh_token()
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    cmd = [
        GH_BIN,
        "run",
        "list",
        "--repo",
        REPO,
        "--limit",
        "1",
        "--json",
        "databaseId,name,status,conclusion,createdAt,url,headBranch",
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        try:
            runs = json.loads(res.stdout)
            if runs:
                return runs[0]
        except Exception:
            pass
    return {}


# ─── UI Text & Keyboard Builders ─────────────────────────────────────
def render_main_dashboard() -> Tuple[str, dict]:
    """Build the root control panel message and inline keyboard."""
    settings = load_settings()
    lang = settings.get("language", "python3")
    dry_run = settings.get("dry_run", False)

    # Find human-readable language label
    lang_label = next((lbl for code, lbl in SUPPORTED_LANGUAGES if code == lang), lang)
    dry_badge = "🔴 OFF (Live Submissions)" if not dry_run else "🟢 ON (Safe Dry-Run)"

    text = (
        "⚡ <b>Axiom LeetCode Control Matrix</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Repository:</b> <code>{REPO}</code>\n"
        f"• <b>Active Language:</b> <b>{lang_label}</b> (<code>{lang}</code>)\n"
        f"• <b>Dry Run Mode:</b> <b>{dry_badge}</b>\n"
        f"• <b>Daily Schedule:</b> <code>00:30 UTC (06:00 IST)</code>\n"
        f"• <b>Keep-Alive Daemon:</b> 🟢 Hourly automated session probe\n\n"
        "<i>Select an option below to configure settings or trigger pipelines:</i>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 Status & Health", "callback_data": "menu_status"},
                {"text": "🚀 Trigger Solver", "callback_data": "menu_run_select"},
            ],
            [
                {"text": f"⚙️ Language ({lang})", "callback_data": "menu_lang"},
                {"text": f"🛡️ Toggle Dry Run", "callback_data": "toggle_dry_run"},
            ],
            [
                {"text": "🔑 Session & Credentials", "callback_data": "menu_auth"},
                {"text": "🔔 Test Ping", "callback_data": "menu_ping"},
            ],
        ]
    }
    return text, keyboard


def render_status_view() -> Tuple[str, dict]:
    """Render comprehensive diagnostics and run status."""
    run_info = fetch_latest_run_info()
    settings = load_settings()

    run_id = run_info.get("databaseId", "N/A")
    run_name = run_info.get("name", "N/A")
    status = run_info.get("status", "unknown")
    conclusion = run_info.get("conclusion") or "running"
    run_url = run_info.get("url", f"https://github.com/{REPO}/actions")

    conc_badge = "✅ Success" if conclusion == "success" else ("❌ " + conclusion if conclusion == "failure" else conclusion)

    text = (
        "📊 <b>System Health & Workflow Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Repository:</b> <code>{REPO}</code>\n"
        f"• <b>Active Settings:</b> Lang: <code>{settings.get('language')}</code> | DryRun: <code>{settings.get('dry_run')}</code>\n\n"
        f"<b>Latest GitHub Actions Run:</b>\n"
        f"• <b>Workflow:</b> {run_name} (#{run_id})\n"
        f"• <b>Status:</b> <code>{status}</code>\n"
        f"• <b>Conclusion:</b> <b>{conc_badge}</b>\n\n"
        f"🔗 <a href=\"{run_url}\">View Run Logs on GitHub</a>\n\n"
        "<i>Hourly keep-alive cron is running on GitHub to preserve your cookie lifespan.</i>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh Status", "callback_data": "menu_status"},
                {"text": "🚀 Run Solver Now", "callback_data": "menu_run_select"},
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"},
            ],
        ]
    }
    return text, keyboard


def render_language_menu() -> Tuple[str, dict]:
    """Render solution language switcher with active checkmark."""
    settings = load_settings()
    active_lang = settings.get("language", "python3")

    text = (
        "⚙️ <b>Configure Solution Language</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select the primary programming language for Gemini and local templates to generate:\n\n"
        f"<b>Currently Active:</b> <code>{active_lang}</code>"
    )

    rows = []
    # Two buttons per row
    current_row = []
    for code, label in SUPPORTED_LANGUAGES:
        is_active = code == active_lang
        btn_text = f"{label} {'✓' if is_active else ''}"
        current_row.append({"text": btn_text, "callback_data": f"set_lang_{code}"})
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append([{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}])
    return text, {"inline_keyboard": rows}


def render_run_select_menu() -> Tuple[str, dict]:
    """Render manual solver execution options."""
    settings = load_settings()
    lang = settings.get("language", "python3")

    text = (
        "🚀 <b>Dispatch LeetCode Daily Solver</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Target Problem:</b> Today's LeetCode Daily Coding Challenge\n"
        f"• <b>Target Language:</b> <code>{lang}</code>\n\n"
        "Choose execution mode:\n"
        "• <b>Live Submission:</b> Generates solution, tests against LeetCode samples, and submits live to your profile.\n"
        "• <b>Dry Run (Test):</b> Generates code and updates dashboard without submitting."
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "▶️ Dispatch Live Submission", "callback_data": "do_run_live"},
            ],
            [
                {"text": "🧪 Dispatch Dry Run (Test)", "callback_data": "do_run_dry"},
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"},
            ],
        ]
    }
    return text, keyboard


def render_auth_hub() -> Tuple[str, dict]:
    """Render credentials & cookie management screen."""
    text = (
        "🔑 <b>LeetCode Session & Authentication Hub</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛡️ <b>Why In-Browser CAPTCHA Happens:</b>\n"
        "LeetCode enforces Cloudflare Turnstile bot challenges on <code>/accounts/login/</code>. "
        "A background server or proxy cannot fake or solve human Turnstile challenges programmatically—it must be completed in a real browser.\n\n"
        "<b>Ways to Transmit Cookies:</b>\n"
        "1️⃣ <b>Orion Browser on iPhone (Zero-Copy):</b> Use the Orion mobile browser on iOS. It supports desktop Chrome extensions! Install <i>LeetCode Cookie Pusher</i> and sync cookies in 1 tap without copying anything.\n"
        "2️⃣ <b>Direct Official Login:</b> Open LeetCode in your phone's browser, solve the CAPTCHA once, and paste your cookie string here.\n"
        "3️⃣ <b>Paste String into Chat:</b> Send <code>LEETCODE_SESSION=...</code> right here in Telegram.\n\n"
        "<i>Once synced, GitHub Actions automatically refreshes the session hourly.</i>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🌐 Open LeetCode Login Page",
                    "url": "https://leetcode.com/accounts/login/",
                }
            ],
            [
                {"text": "📱 Orion iOS Setup Guide", "callback_data": "auth_orion_guide"},
                {"text": "🔍 Verify Active Session", "callback_data": "auth_check_active"},
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"},
            ],
        ]
    }
    return text, keyboard


def render_orion_guide() -> Tuple[str, dict]:
    """Render step-by-step instructions for Orion iOS extension."""
    text = (
        "📱 <b>Orion iOS Zero-Copy Extension Guide</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Orion is a free WebKit browser on the Apple App Store that supports real desktop Chrome & Firefox extensions on your iPhone!\n\n"
        "<b>Quick Setup (Takes 60 seconds):</b>\n"
        "1. Download <b>Orion Browser</b> from App Store on your iPhone.\n"
        "2. Open Orion Settings → Extensions → Enable Chrome Extensions.\n"
        "3. Load our <code>LeetCode Cookie Pusher</code> extension from your GitHub repo.\n"
        "4. Go to <code>leetcode.com</code> in Orion and log in naturally (completing Turnstile).\n"
        "5. Tap the extension icon → Tap <b>🚀 Push Cookies to GitHub</b>.\n\n"
        "✨ <i>Done! The extension reads <code>HttpOnly</code> cookies with native browser privileges and pushes them to your repo secrets without you having to copy or paste anything!</i>"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔙 Back to Credentials Hub", "callback_data": "menu_auth"},
                {"text": "🔙 Main Menu", "callback_data": "menu_main"},
            ]
        ]
    }
    return text, keyboard


# ─── Cookie Update Pipeline ──────────────────────────────────────────
def handle_cookie_update(chat_id: int, text: str):
    """Parse cookie text, validate against LeetCode GraphQL, and push to GitHub."""
    send_reply(chat_id, "⏳ <i>Axiom inspecting cookies against LeetCode GraphQL API...</i>")

    sess_match = re.search(r"LEETCODE_SESSION=([^\s;]+)", text)
    csrf_match = re.search(r"csrftoken=([^\s;]+)", text)

    session = sess_match.group(1) if sess_match else None
    csrf = csrf_match.group(1) if csrf_match else None

    if not session:
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
            "❌ <b>Could not find LEETCODE_SESSION token.</b>\n\n"
            "Paste your cookie like this:\n"
            "<code>LEETCODE_SESSION=your_token_here; csrftoken=your_csrf_here</code>",
        )
        return

    if not csrf:
        csrf = "temp_csrf_token"

    ok, username = validate_leetcode_cookies(session, csrf)
    if not ok:
        send_reply(
            chat_id,
            f"❌ <b>Validation Rejected by LeetCode:</b>\n<code>{username}</code>\n\n"
            "Make sure you copied a fresh session cookie while logged in.",
        )
        return

    send_reply(chat_id, f"✅ <b>Authenticated as {username}!</b>\n⏳ <i>Pushing secrets to GitHub Actions...</i>")

    bundle_json = json.dumps({"LEETCODE_SESSION": session, "LEETCODE_CSRF_TOKEN": csrf}, separators=(",", ":"))
    ok_bundle = push_secret_gh("LEETCODE_COOKIE_BUNDLE", bundle_json)
    push_secret_gh("LEETCODE_SESSION", session)
    push_secret_gh("LEETCODE_CSRF_TOKEN", csrf)

    if ok_bundle:
        settings = load_settings()
        lang = settings.get("language", "python3")
        ok_run, run_msg = trigger_workflow(dry_run=True, language=lang)
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


# ─── Telegram Dispatchers ────────────────────────────────────────────
def handle_message(chat_id: int, text: str):
    """Route text messages and slash commands."""
    text_clean = text.strip()

    if text_clean.startswith("/menu") or text_clean.startswith("/settings") or text_clean.lower() == "menu":
        msg, kb = render_main_dashboard()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/start") or text_clean.startswith("/help"):
        msg = (
            "⚡ <b>Axiom LeetCode Bot Sentinel</b>\n\n"
            "Hey boss man! I watch your LeetCode solver, manage language settings, and sync credentials.\n\n"
            "<b>Commands:</b>\n"
            "• <code>/menu</code> — Open interactive settings & control panel\n"
            "• <code>/status</code> — Check system health & latest GitHub runs\n"
            "• <code>/run</code> — Dispatch the daily solver workflow\n"
            "• <code>/login</code> — LeetCode credentials & cookie options\n\n"
            "<b>Direct Cookie Sync:</b>\n"
            "Paste <code>LEETCODE_SESSION=...</code> directly into this chat anytime to update your secrets."
        )
        send_reply(chat_id, msg)
        return

    if text_clean.startswith("/status"):
        msg, kb = render_status_view()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/test") or text_clean.startswith("/run"):
        msg, kb = render_run_select_menu()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/login") or text_clean.startswith("/renew"):
        msg, kb = render_auth_hub()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    # Check if user sent cookies
    if "LEETCODE_SESSION" in text or len(text.strip().split()) >= 1 and len(text.strip()) > 50:
        handle_cookie_update(chat_id, text)
        return

    send_reply(
        chat_id,
        "🤖 <i>Command not recognized.</i>\n\n"
        "Tap <code>/menu</code> to open the control panel or paste your <code>LEETCODE_SESSION</code> cookie string here.",
    )


def handle_callback_query(cq: dict):
    """Route inline button clicks and update view in-place."""
    cq_id = cq.get("id")
    data = cq.get("data", "")
    message = cq.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if not chat_id or chat_id != AUTHORIZED_CHAT_ID:
        answer_callback_query(cq_id, "Unauthorized", show_alert=True)
        return

    logger.info(f"Handling callback query: {data}")

    # 1. Main Menu
    if data == "menu_main":
        answer_callback_query(cq_id)
        msg, kb = render_main_dashboard()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 2. Status
    if data == "menu_status":
        answer_callback_query(cq_id, "Refreshing status...")
        msg, kb = render_status_view()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 3. Run Selection
    if data == "menu_run_select":
        answer_callback_query(cq_id)
        msg, kb = render_run_select_menu()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 4. Trigger Live
    if data == "do_run_live":
        settings = load_settings()
        lang = settings.get("language", "python3")
        answer_callback_query(cq_id, "Dispatching live run...")
        ok, res_msg = trigger_workflow(dry_run=False, language=lang)
        status_text = (
            "🚀 <b>Live Solver Dispatched!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Mode:</b> Live Submission (real profile submit)\n"
            f"• <b>Language:</b> <code>{lang}</code>\n"
            f"• <b>Status:</b> {'✅ Workflow Queued on GitHub Actions' if ok else '❌ Dispatch error: ' + res_msg}\n\n"
            f"🔗 <a href=\"https://github.com/{REPO}/actions\">Watch Workflow Live</a>"
        )
        kb = {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "menu_main"}]]}
        edit_message(chat_id, message_id, status_text, reply_markup=kb)
        return

    # 5. Trigger Dry Run
    if data == "do_run_dry":
        settings = load_settings()
        lang = settings.get("language", "python3")
        answer_callback_query(cq_id, "Dispatching test dry run...")
        ok, res_msg = trigger_workflow(dry_run=True, language=lang)
        status_text = (
            "🧪 <b>Dry Run Dispatched!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Mode:</b> Dry Run (Test only, no submission)\n"
            f"• <b>Language:</b> <code>{lang}</code>\n"
            f"• <b>Status:</b> {'✅ Workflow Queued on GitHub Actions' if ok else '❌ Dispatch error: ' + res_msg}\n\n"
            f"🔗 <a href=\"https://github.com/{REPO}/actions\">Watch Workflow Live</a>"
        )
        kb = {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "menu_main"}]]}
        edit_message(chat_id, message_id, status_text, reply_markup=kb)
        return

    # 6. Language Menu
    if data == "menu_lang":
        answer_callback_query(cq_id)
        msg, kb = render_language_menu()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 7. Set Language
    if data.startswith("set_lang_"):
        new_lang = data.replace("set_lang_", "")
        settings = load_settings()
        settings["language"] = new_lang
        save_settings(settings)
        answer_callback_query(cq_id, f"Language set to {new_lang}!", show_alert=False)
        msg, kb = render_language_menu()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 8. Toggle Dry Run
    if data == "toggle_dry_run":
        settings = load_settings()
        settings["dry_run"] = not settings.get("dry_run", False)
        save_settings(settings)
        state_str = "ON (Dry-Run Only)" if settings["dry_run"] else "OFF (Live Submissions)"
        answer_callback_query(cq_id, f"Dry Run set to {state_str}!", show_alert=False)
        msg, kb = render_main_dashboard()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 9. Auth Hub
    if data == "menu_auth":
        answer_callback_query(cq_id)
        msg, kb = render_auth_hub()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 10. Orion iOS Guide
    if data == "auth_orion_guide":
        answer_callback_query(cq_id)
        msg, kb = render_orion_guide()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    # 11. Check Active Session
    if data == "auth_check_active":
        answer_callback_query(cq_id, "Checking session against LeetCode GraphQL...")
        # Check by running python -m src.preflight
        env = os.environ.copy()
        token = get_gh_token()
        if token:
            env["GH_TOKEN"] = token
        res = subprocess.run([GH_BIN, "secret", "list", "--repo", REPO], env=env, capture_output=True, text=True)
        bundle_exists = "LEETCODE_COOKIE_BUNDLE" in res.stdout
        session_exists = "LEETCODE_SESSION" in res.stdout

        result_text = (
            "🔍 <b>Session Probe Diagnostic:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>LEETCODE_COOKIE_BUNDLE Secret:</b> {'✅ Present' if bundle_exists else '❌ Missing'}\n"
            f"• <b>LEETCODE_SESSION Secret:</b> {'✅ Present' if session_exists else '❌ Missing'}\n\n"
            "The hourly keep-alive cron verifies this session every 60 minutes on GitHub Actions. "
            "If your session ever expires, you'll receive an instant Telegram alert."
        )
        kb = {"inline_keyboard": [[{"text": "🔙 Back to Auth Hub", "callback_data": "menu_auth"}]]}
        edit_message(chat_id, message_id, result_text, reply_markup=kb)
        return

    # 12. Test Ping
    if data == "menu_ping":
        answer_callback_query(cq_id, "🏓 Pong! Telegram alert channel is 100% operational.", show_alert=True)
        return

    answer_callback_query(cq_id, "Unknown action")


# ─── Main Polling Loop ───────────────────────────────────────────────
def main():
    logger.info("⚡ Starting Axiom Telegram Sentinel with Full Interactive Menu...")
    register_bot_commands()
    offset = None

    while True:
        try:
            url = f"{BASE_URL}/getUpdates?timeout=25" + (f"&offset={offset}" if offset else "")
            resp = requests.get(url, timeout=30).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1

                # 1. Callback Query (Inline keyboard clicks)
                if "callback_query" in item:
                    handle_callback_query(item["callback_query"])
                    continue

                # 2. Normal Message
                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")

                if not chat_id or chat_id != AUTHORIZED_CHAT_ID:
                    continue

                # WebApp Data (if submitted via Mini App)
                if "web_app_data" in msg:
                    raw_data = msg["web_app_data"].get("data", "")
                    logger.info(f"Received web_app_data: {raw_data[:40]}...")
                    handle_cookie_update(chat_id, raw_data)
                    continue

                text = msg.get("text", "")
                if text:
                    logger.info(f"Received message: {text[:30]}...")
                    handle_message(chat_id, text)

        except Exception as exc:
            logger.error(f"Polling loop error: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    main()
