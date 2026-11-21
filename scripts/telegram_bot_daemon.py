#!/usr/bin/env python3
"""
Axiom Telegram Sentinel & High-Speed Interactive Control Dashboard
Optimized for ultra-low latency, concurrent worker threadpools, and connection reuse.
"""

import os
import re
import sys
import json
import time
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("telegram-sentinel")

# ─── Environment & Config ───────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
AUTHORIZED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "1612900553"))
GH_PAT = os.environ.get("GH_PAT", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "itsyunus/LeetCode_autoSOL").strip()
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

# ─── High-Performance Persistent Connection Pools ──────────────────
tg_session = requests.Session()
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=30, max_retries=1)
tg_session.mount("https://", adapter)

gh_session = requests.Session()
gh_session.mount("https://", adapter)

# Thread pool for non-blocking asynchronous event handling
thread_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tg-worker")

# ─── In-Memory Low-Latency Caching ──────────────────────────────────
CACHE_CHALLENGE = {"data": {}, "expires_at": 0}
CACHE_RUN = {"data": {}, "expires_at": 0}
CACHE_STREAK = {"streak": 0, "expires_at": 0}


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
    """Retrieve GitHub token with in-memory caching."""
    global GH_PAT
    if GH_PAT:
        return GH_PAT

    try:
        res = subprocess.run([GH_BIN, "auth", "token"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            GH_PAT = res.stdout.strip()
            return GH_PAT
    except Exception:
        pass

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


# ─── Instant Telegram Client Helpers (Keep-Alive Reused) ─────────────
def call_tg(method: str, payload: dict) -> dict:
    """Invoke Telegram Bot API method with persistent connection pooling."""
    if not BOT_TOKEN:
        return {"ok": False, "description": "BOT_TOKEN not configured"}
    url = f"{BASE_URL}/{method}"
    try:
        r = tg_session.post(url, json=payload, timeout=8)
        return r.json()
    except Exception as err:
        logger.error(f"Telegram API {method} error: {err}")
        return {"ok": False, "description": str(err)}


def answer_callback_query(cq_id: str, text: Optional[str] = None, show_alert: bool = False):
    """Acknowledge Telegram callback query immediately to dismiss client loader."""
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
    """Update existing message in-place for instantaneous UI transition."""
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
        {"command": "streak", "description": "🔥 Check Streak, Solved Problem & Expiry"},
        {"command": "status", "description": "📊 Check session health & GitHub runs"},
        {"command": "run", "description": "🚀 Dispatch daily solver on GitHub"},
        {"command": "login", "description": "🔑 LeetCode session renewal hub"},
        {"command": "help", "description": "ℹ️ Instructions & commands"},
    ]
    call_tg("setMyCommands", {"commands": commands})


# ─── Low-Latency GitHub & LeetCode Operations ────────────────────────
def push_secret_gh(secret_name: str, secret_value: str) -> bool:
    """Push encrypted secret via gh CLI."""
    token = get_gh_token()
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    cmd = [GH_BIN, "secret", "set", secret_name, "--repo", REPO, "--body", secret_value]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return res.returncode == 0


def trigger_workflow(dry_run: bool, language: str) -> Tuple[bool, str]:
    """Dispatch workflow via GitHub REST API with zero CLI overhead."""
    token = get_gh_token()
    if token:
        try:
            resp = gh_session.post(
                f"https://api.github.com/repos/{REPO}/actions/workflows/daily_solve.yml/dispatches",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"ref": "main", "inputs": {"dry_run": str(dry_run).lower(), "language": language}},
                timeout=6,
            )
            if resp.status_code == 204:
                return True, "Dispatched successfully"
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            logger.warning(f"REST dispatch error: {e}")

    dry_str = "true" if dry_run else "false"
    cmd = [
        GH_BIN, "workflow", "run", "daily_solve.yml", "--repo", REPO,
        "-f", f"dry_run={dry_str}", "-f", f"language={language}",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return True, "Dispatched successfully"
    return False, res.stderr or "Workflow dispatch failed"


def fetch_latest_run_info(force: bool = False) -> Dict[str, Any]:
    """Fetch latest run via direct REST API with 30s TTL cache (sub-100ms)."""
    now = time.time()
    if not force and now < CACHE_RUN["expires_at"] and CACHE_RUN["data"]:
        return CACHE_RUN["data"]

    token = get_gh_token()
    if token:
        try:
            resp = gh_session.get(
                f"https://api.github.com/repos/{REPO}/actions/runs?per_page=1",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=4,
            )
            if resp.status_code == 200:
                runs = resp.json().get("workflow_runs", [])
                if runs:
                    r = runs[0]
                    res = {
                        "databaseId": r.get("id"),
                        "name": r.get("name"),
                        "status": r.get("status"),
                        "conclusion": r.get("conclusion"),
                        "createdAt": r.get("created_at"),
                        "url": r.get("html_url"),
                    }
                    CACHE_RUN["data"] = res
                    CACHE_RUN["expires_at"] = now + 30
                    return res
        except Exception:
            pass

    cmd = [
        GH_BIN, "run", "list", "--repo", REPO, "--limit", "1",
        "--json", "databaseId,name,status,conclusion,createdAt,url,headBranch",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        try:
            runs = json.loads(res.stdout)
            if runs:
                CACHE_RUN["data"] = runs[0]
                CACHE_RUN["expires_at"] = now + 30
                return runs[0]
        except Exception:
            pass
    return {}


def fetch_today_challenge() -> dict:
    """Fetch daily challenge with 15-minute in-memory caching."""
    now = time.time()
    if now < CACHE_CHALLENGE["expires_at"] and CACHE_CHALLENGE["data"]:
        return CACHE_CHALLENGE["data"]

    try:
        q = """
        query questionOfToday {
            activeDailyCodingChallengeQuestion {
                date
                link
                question {
                    questionFrontendId
                    title
                    titleSlug
                    difficulty
                }
            }
        }
        """
        resp = gh_session.post(LEETCODE_GRAPHQL, json={"query": q}, timeout=4)
        if resp.status_code == 200:
            data = resp.json().get("data", {}).get("activeDailyCodingChallengeQuestion", {})
            if data:
                CACHE_CHALLENGE["data"] = data
                CACHE_CHALLENGE["expires_at"] = now + 900
                return data
    except Exception as e:
        logger.warning(f"LeetCode challenge fetch error: {e}")

    return CACHE_CHALLENGE["data"] or {}


def get_cached_streak(repo_root: str) -> int:
    """Retrieve streak count with 2-minute TTL cache."""
    now = time.time()
    if now < CACHE_STREAK["expires_at"]:
        return CACHE_STREAK["streak"]
    try:
        from src.notify import calculate_streak
        s = calculate_streak(repo_root)
        CACHE_STREAK["streak"] = s
        CACHE_STREAK["expires_at"] = now + 120
        return s
    except Exception:
        return 0


# ─── UI Text & Keyboard Builders ─────────────────────────────────────
def render_main_dashboard() -> Tuple[str, dict]:
    """Build root control matrix with zero latency."""
    settings = load_settings()
    lang = settings.get("language", "python3")
    dry_run = settings.get("dry_run", False)

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
                {"text": "🔥 Streak & Expiry", "callback_data": "menu_streak"},
                {"text": "📊 Status & Health", "callback_data": "menu_status"},
            ],
            [
                {"text": "🚀 Trigger Solver", "callback_data": "menu_run_select"},
                {"text": f"⚙️ Language ({lang})", "callback_data": "menu_lang"},
            ],
            [
                {"text": "🔑 Session & Credentials", "callback_data": "menu_auth"},
                {"text": f"🛡️ Dry Run ({'ON' if dry_run else 'OFF'})", "callback_data": "toggle_dry_run"},
            ],
        ]
    }
    return text, keyboard


def render_streak_view() -> Tuple[str, dict]:
    """Render instantaneous streak metrics, current problem, and countdown."""
    challenge = fetch_today_challenge()
    q_data = challenge.get("question", {}) if isinstance(challenge, dict) else {}
    pid = q_data.get("questionFrontendId", "3331")
    title = q_data.get("title", "Find Subtree Sizes After Changes")
    difficulty = q_data.get("difficulty", "Medium")
    slug = q_data.get("titleSlug", "find-subtree-sizes-after-changes")
    url = f"https://leetcode.com/problems/{slug}/" if slug else "https://leetcode.com/problemset/all/"

    repo_root = os.path.dirname(SCRIPT_DIR)
    streak = get_cached_streak(repo_root)

    try:
        from src.notify import get_expiry_countdown
        countdown, deadline = get_expiry_countdown()
    except Exception:
        countdown, deadline = "N/A", "00:00 UTC (05:30 IST)"

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    log_file = os.path.join(repo_root, "logs", f"result_{today_str}.json")
    is_solved = False
    status_label = "Unsolved (Pending Solve Run)"
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                d = json.load(f)
            if d.get("status") in ("accepted", "already_solved"):
                is_solved = True
                status_label = "✅ Solved & Accepted"
        except Exception:
            pass

    if not is_solved:
        latest_run = fetch_latest_run_info()
        if latest_run.get("conclusion") == "success":
            is_solved = True
            status_label = "✅ Solved (Verified in GitHub Actions)"

    if is_solved:
        streak_display = max(1, streak)
        status_badge = "🛡️ <b>SECURED FOR TODAY</b>"
        expiry_info = (
            f"• <b>Streak Status:</b> {status_badge}\n"
            f"• <b>Challenge Reset:</b> ⏳ <b>{countdown}</b> (at {deadline})"
        )
    else:
        streak_display = streak
        status_badge = "⚠️ <b>EXPIRES SOON!</b>"
        expiry_info = (
            f"• <b>Streak Status:</b> {status_badge}\n"
            f"• <b>Time Remaining To Solve:</b> ⏳ <b>{countdown}</b> (Deadline: {deadline})"
        )

    text = (
        "🔥 <b>LeetCode Streak & Challenge Sentinel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Today's Problem:</b> #{pid} <b>{title}</b> (<code>{difficulty}</code>)\n"
        f"• <b>Solve Status:</b> <b>{status_label}</b>\n"
        f"• <b>Current Streak:</b> 🔥 <b>{streak_display} Days Active</b>\n"
        f"{expiry_info}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <a href=\"{url}\">Open Daily Question on LeetCode</a>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh Streak", "callback_data": "menu_streak"},
                {"text": "🚀 Run Solver Now", "callback_data": "menu_run_select"},
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"},
            ],
        ]
    }
    return text, keyboard


def render_status_view() -> Tuple[str, dict]:
    """Render status with cached GitHub Action metrics."""
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

    buttons = []
    for code, label in SUPPORTED_LANGUAGES:
        is_active = (code == active_lang)
        btn_text = f"✅ {label}" if is_active else label
        buttons.append([{"text": btn_text, "callback_data": f"set_lang_{code}"}])

    buttons.append([{"text": "🔙 Back to Menu", "callback_data": "menu_main"}])

    text = (
        "⚙️ <b>Select Solution Language</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Current choice: <b>{active_lang}</b>\n\n"
        "Tap a language below to set it for automated submissions:"
    )
    return text, {"inline_keyboard": buttons}


def render_run_select_menu() -> Tuple[str, dict]:
    """Render modal prompt choosing between live submission and dry-run."""
    settings = load_settings()
    lang = settings.get("language", "python3")
    dry_mode = settings.get("dry_run", False)

    text = (
        "🚀 <b>Dispatch Daily Solver</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Repository:</b> <code>{REPO}</code>\n"
        f"• <b>Language:</b> <code>{lang}</code>\n"
        f"• <b>Default Mode:</b> {'Dry-Run' if dry_mode else 'Live Submission'}\n\n"
        "Choose an execution mode below:"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "⚡ Run Live (Submit)", "callback_data": "do_run_live"},
                {"text": "🧪 Run Dry (No Submit)", "callback_data": "do_run_dry"},
            ],
            [
                {"text": "🔙 Back to Menu", "callback_data": "menu_main"},
            ],
        ]
    }
    return text, keyboard


def render_auth_hub() -> Tuple[str, dict]:
    """Render credentials management hub."""
    text = (
        "🔑 <b>Session & Credentials Hub</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "• <b>Direct Paste:</b> Send <code>LEETCODE_SESSION=...</code> right into chat.\n"
        "• <b>Extension:</b> Open the Chrome extension popup for 1-click sync.\n"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔍 Probe Session Status", "callback_data": "auth_check_active"},
            ],
            [
                {"text": "🔙 Back to Menu", "callback_data": "menu_main"},
            ],
        ]
    }
    return text, keyboard


# ─── Event Dispatchers (Concurrent Async Execution) ─────────────────
def handle_callback_query(cq: dict):
    """Route inline button clicks with zero blocking overhead."""
    cq_id = cq.get("id")
    data = cq.get("data", "")
    message = cq.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if not chat_id or chat_id != AUTHORIZED_CHAT_ID:
        answer_callback_query(cq_id, "Unauthorized", show_alert=True)
        return

    # Acknowledge immediately to extinguish client loader
    answer_callback_query(cq_id)

    if data == "menu_main":
        msg, kb = render_main_dashboard()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "menu_status":
        msg, kb = render_status_view()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "menu_streak":
        msg, kb = render_streak_view()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "menu_run_select":
        msg, kb = render_run_select_menu()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "do_run_live":
        settings = load_settings()
        lang = settings.get("language", "python3")
        ok, res_msg = trigger_workflow(dry_run=False, language=lang)
        status_text = (
            "🚀 <b>Live Solver Dispatched!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Mode:</b> Live Submission\n"
            f"• <b>Language:</b> <code>{lang}</code>\n"
            f"• <b>Status:</b> {'✅ Queued on GitHub Actions' if ok else '❌ Error: ' + res_msg}\n\n"
            f"🔗 <a href=\"https://github.com/{REPO}/actions\">Watch Workflow Live</a>"
        )
        kb = {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "menu_main"}]]}
        edit_message(chat_id, message_id, status_text, reply_markup=kb)
        return

    if data == "do_run_dry":
        settings = load_settings()
        lang = settings.get("language", "python3")
        ok, res_msg = trigger_workflow(dry_run=True, language=lang)
        status_text = (
            "🧪 <b>Dry Run Dispatched!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Mode:</b> Dry Run (Test only)\n"
            f"• <b>Language:</b> <code>{lang}</code>\n"
            f"• <b>Status:</b> {'✅ Queued on GitHub Actions' if ok else '❌ Error: ' + res_msg}\n\n"
            f"🔗 <a href=\"https://github.com/{REPO}/actions\">Watch Workflow Live</a>"
        )
        kb = {"inline_keyboard": [[{"text": "🔙 Back to Menu", "callback_data": "menu_main"}]]}
        edit_message(chat_id, message_id, status_text, reply_markup=kb)
        return

    if data == "menu_lang":
        msg, kb = render_language_menu()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data.startswith("set_lang_"):
        new_lang = data.replace("set_lang_", "")
        settings = load_settings()
        settings["language"] = new_lang
        save_settings(settings)
        msg, kb = render_language_menu()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "toggle_dry_run":
        settings = load_settings()
        settings["dry_run"] = not settings.get("dry_run", False)
        save_settings(settings)
        msg, kb = render_main_dashboard()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "menu_auth":
        msg, kb = render_auth_hub()
        edit_message(chat_id, message_id, msg, reply_markup=kb)
        return

    if data == "auth_check_active":
        res = subprocess.run([GH_BIN, "secret", "list", "--repo", REPO], capture_output=True, text=True)
        bundle_exists = "LEETCODE_COOKIE_BUNDLE" in res.stdout
        session_exists = "LEETCODE_SESSION" in res.stdout
        result_text = (
            "🔍 <b>Session Probe Diagnostic:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>LEETCODE_COOKIE_BUNDLE:</b> {'✅ Present' if bundle_exists else '❌ Missing'}\n"
            f"• <b>LEETCODE_SESSION:</b> {'✅ Present' if session_exists else '❌ Missing'}\n"
        )
        kb = {"inline_keyboard": [[{"text": "🔙 Back to Auth Hub", "callback_data": "menu_auth"}]]}
        edit_message(chat_id, message_id, result_text, reply_markup=kb)
        return


def handle_message(chat_id: int, text: str):
    """Handle text commands asynchronously."""
    text_clean = text.strip()

    if text_clean.startswith("/menu") or text_clean.startswith("/settings") or text_clean.lower() == "menu":
        msg, kb = render_main_dashboard()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/streak") or text_clean.lower() == "streak":
        msg, kb = render_streak_view()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/status"):
        msg, kb = render_status_view()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/start") or text_clean.startswith("/help"):
        msg = (
            "⚡ <b>Axiom LeetCode Bot Sentinel (High-Speed Engine)</b>\n\n"
            "Hey boss man! I watch your LeetCode solver, manage language settings, and monitor streaks.\n\n"
            "<b>Commands:</b>\n"
            "• <code>/streak</code> — Check active streak, solved problem & countdown\n"
            "• <code>/menu</code> — Open interactive control matrix\n"
            "• <code>/status</code> — Check system health & latest GitHub runs\n"
            "• <code>/run</code> — Dispatch the daily solver workflow\n"
            "• <code>/login</code> — LeetCode credentials hub"
        )
        send_reply(chat_id, msg)
        return

    if text_clean.startswith("/run"):
        msg, kb = render_run_select_menu()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    if text_clean.startswith("/login"):
        msg, kb = render_auth_hub()
        send_reply(chat_id, msg, reply_markup=kb)
        return

    send_reply(
        chat_id,
        "🤖 <i>Command not recognized.</i>\n\nTap <code>/menu</code> or <code>/streak</code> to view metrics.",
    )


# ─── Non-Blocking Event-Driven Polling Loop ──────────────────────────
def main():
    logger.info("⚡ Starting Axiom Telegram Sentinel (High-Speed Multi-Threaded Engine)...")
    register_bot_commands()
    offset = None

    while True:
        try:
            url = f"{BASE_URL}/getUpdates?timeout=15" + (f"&offset={offset}" if offset else "")
            resp = tg_session.get(url, timeout=20).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1

                if "callback_query" in item:
                    thread_pool.submit(handle_callback_query, item["callback_query"])
                    continue

                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")

                if not chat_id or chat_id != AUTHORIZED_CHAT_ID:
                    continue

                text = msg.get("text", "")
                if text:
                    thread_pool.submit(handle_message, chat_id, text)

        except Exception as exc:
            logger.error(f"Polling loop error: {exc}")
            time.sleep(2)


if __name__ == "__main__":
    main()
