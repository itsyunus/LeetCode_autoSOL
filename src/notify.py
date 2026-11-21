"""Mobile alerts and Telegram streak/progress dispatcher for LeetCode Auto-Solver."""
import os
import glob
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
import requests

logger = logging.getLogger(__name__)


def calculate_streak(repo_root: Optional[str] = None) -> int:
    """Calculate consecutive daily accepted solutions from result logs."""
    if not repo_root:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(repo_root, "logs")
    if not os.path.exists(logs_dir):
        return 0

    log_files = sorted(glob.glob(os.path.join(logs_dir, "result_*.json")))
    if not log_files:
        return 0

    daily_statuses = {}
    for filepath in log_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            basename = os.path.basename(filepath)
            date_str = basename.replace("result_", "").replace(".json", "")
            status = data.get("status", "")
            daily_statuses[date_str] = status in ("accepted", "already_solved")
        except Exception:
            continue

    if not daily_statuses:
        return 0

    # Count consecutive active days backwards from today or yesterday
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    yesterday_str = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")

    curr_date = now_utc.date()
    if today_str not in daily_statuses or not daily_statuses[today_str]:
        # If not yet recorded for today, start from yesterday
        curr_date = (now_utc - timedelta(days=1)).date()

    streak = 0
    while True:
        d_str = curr_date.strftime("%Y-%m-%d")
        if daily_statuses.get(d_str):
            streak += 1
            curr_date -= timedelta(days=1)
        else:
            break

    return streak


def get_expiry_countdown() -> Tuple[str, str]:
    """Calculate time remaining until the daily challenge expires at 00:00:00 UTC."""
    now_utc = datetime.now(timezone.utc)
    midnight_utc = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc) + timedelta(days=1)
    diff = midnight_utc - now_utc
    total_seconds = max(0, int(diff.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    countdown_str = f"{hours}h {minutes}m"
    deadline_str = "00:00 UTC (05:30 IST)"
    return countdown_str, deadline_str


def send_streak_report(result: Dict[str, Any]) -> bool:
    """Send rich Telegram notification with streak count, solved question, and expiration."""
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

    if not (bot_token and chat_id):
        logger.info("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
        return False

    status = result.get("status", "unknown")
    problem = result.get("problem", {})
    submission = result.get("submission") or {}
    error = result.get("error")

    pid = problem.get("id") or problem.get("questionFrontendId") or "?"
    title = problem.get("title", "Daily Coding Challenge")
    slug = problem.get("slug") or problem.get("titleSlug") or ""
    difficulty = problem.get("difficulty", "Medium")
    url = f"https://leetcode.com/problems/{slug}/" if slug else "https://leetcode.com/problemset/all/"

    streak = calculate_streak()
    countdown, deadline = get_expiry_countdown()

    is_success = status in ("accepted", "already_solved")

    if is_success:
        streak_display = max(1, streak)
        status_label = "✅ Solved & Accepted" if status == "accepted" else "⚡ Already Solved Today"
        headline = "🎯 <b>LEETCODE STREAK SECURED!</b>"
        streak_banner = f"🛡️ <b>Streak Status:</b> SECURED FOR TODAY (Next reset in {countdown})"
    else:
        streak_display = streak
        status_label = f"⚠️ Pipeline Failed ({status})"
        headline = "🚨 <b>LEETCODE STREAK AT RISK!</b>"
        streak_banner = f"⏳ <b>URGENT: Streak expires in {countdown}!</b> (Deadline: {deadline})"

    # Performance stats if available
    perf_lines = ""
    if submission and submission.get("runtime"):
        runtime = submission.get("runtime", "N/A")
        memory = submission.get("memory", "N/A")
        lang = submission.get("language", "python3")
        perf_lines = (
            f"• <b>Language:</b> <code>{lang}</code>\n"
            f"• <b>Runtime:</b> <code>{runtime}</code> | <b>Memory:</b> <code>{memory}</code>\n"
        )

    err_line = f"\n• <b>Diagnostic:</b> <code>{error}</code>\n" if (error and not is_success) else ""

    text = (
        f"{headline}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Question:</b> #{pid} <b>{title}</b> (<code>{difficulty}</code>)\n"
        f"• <b>Status:</b> <b>{status_label}</b>\n"
        f"• <b>Active Streak:</b> 🔥 <b>{streak_display} Days</b>\n"
        f"{perf_lines}"
        f"• <b>Challenge Reset:</b> <b>{countdown}</b> (at {deadline})\n"
        f"{err_line}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{streak_banner}\n"
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "🌐 Open Question on LeetCode", "url": url}]
            ]
        }
    }

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=15
        )
        resp.raise_for_status()
        logger.info("Telegram streak report delivered successfully.")
        return True
    except Exception as exc:
        logger.error(f"Failed to deliver Telegram streak report: {exc}")
        return False


def send_alert(message: str) -> bool:
    """Legacy failure alert."""
    sent = False
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

    if bot_token and chat_id:
        countdown, deadline = get_expiry_countdown()
        import html
        escaped_msg = html.escape(message)
        text_payload = (
            f"🚨 <b>LEETCODE STREAK AT RISK!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> ⚠️ Daily Solve Pipeline Failed\n"
            f"• <b>Diagnostic:</b> <code>{escaped_msg}</code>\n"
            f"• <b>Expires In:</b> ⏳ <b>{countdown}</b> (Deadline: {deadline})\n\n"
            f"⚠️ <b>Action Required:</b> Your daily streak is at risk!\n"
            f"Solve today's challenge manually or update session tokens."
        )

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text_payload,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "🌐 Open LeetCode Today", "url": "https://leetcode.com/problemset/all/"}]
                        ]
                    }
                },
                timeout=15,
            )
            response.raise_for_status()
            sent = True
        except Exception:
            pass

    discord_url = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if discord_url:
        try:
            requests.post(discord_url, json={"content": message}, timeout=15)
            sent = True
        except Exception:
            pass

    return sent


if __name__ == "__main__":
    text = os.environ.get(
        "ALERT_MESSAGE",
        "LeetCode automation needs attention. Open the latest GitHub Actions run.",
    )
    print("Mobile alert sent." if send_alert(text) else "No mobile alert provider configured.")
